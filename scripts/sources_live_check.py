"""Live health check for every data source (what works *right now*).

The docs describe the sources as if they always work.  This script measures the
truth, politely (the adapters already pace at 0.25 s/request, and each source gets
at most a couple of tiny queries):

    .venv\\Scripts\\python.exe scripts\\sources_live_check.py [--json OUT] [--markdown OUT]

Per source: reachable? latency? did a real query return a usable record?  Key-gated
sources (Materials Project) report ``needs-key`` when ``MP_API_KEY`` is unset —
that is a configuration state, not a failure.  The output is timestamped and
written to ``runs/sources_live.json``; ``docs/SOURCES.md`` embeds the table.

Exit code is always 0 (a database being down must not break a release); use the
JSON for gating.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: (host, port) used for a cheap TCP reachability probe before spending an HTTP call
HOSTS = {
    "cod": ("www.crystallography.net", 443),
    "aflow": ("aflow.org", 443),
    "materials-project": ("api.materialsproject.org", 443),
}


def tcp_probe(host: str, port: int, timeout: float = 6.0) -> dict:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"reachable": True, "seconds": round(time.perf_counter() - started, 3)}
    except OSError as exc:
        return {"reachable": False, "seconds": round(time.perf_counter() - started, 3),
                "error": f"{type(exc).__name__}: {exc}"}


def check_core_mof() -> dict:
    """Local dataset: no network, so this is the only always-available source."""
    from cifkit.sources.core_mof import build_index, dataset_dir

    started = time.perf_counter()
    try:
        index = build_index()
        return {"status": "ok", "seconds": round(time.perf_counter() - started, 2),
                "n_entries": index["n_entries"], "path": str(dataset_dir()),
                "license": index.get("license") or "CC-BY-4.0"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "seconds": round(time.perf_counter() - started, 2),
                "error": f"{type(exc).__name__}: {exc}"}


def check_cod() -> dict:
    from cifkit.sources.cod import CODSource
    from cifkit.types import SourceQuery

    probe = tcp_probe(*HOSTS["cod"])
    row: dict = {"tcp": probe}
    started = time.perf_counter()
    try:
        source = CODSource()
        by_id = source.search(SourceQuery(structure_id="7111973", source="cod", limit=1))
        row["by_id"] = {"n_hits": len(by_id),
                        "first": by_id[0].record_id if by_id else None,
                        "formula": getattr(by_id[0], "formula", None) if by_id else None}
        by_text = source.search(SourceQuery(structure_name="ZIF-8", source="cod", limit=3))
        row["by_text"] = {"n_hits": len(by_text),
                          "first": by_text[0].record_id if by_text else None}
        row.update({"status": "ok" if by_id else "empty",
                    "seconds": round(time.perf_counter() - started, 2)})
    except Exception as exc:  # noqa: BLE001
        row.update({"status": "fail", "seconds": round(time.perf_counter() - started, 2),
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    return row


def check_aflow() -> dict:
    from cifkit.sources.aflow import AFLOWSource
    from cifkit.types import SourceQuery

    probe = tcp_probe(*HOSTS["aflow"])
    row: dict = {"tcp": probe}
    started = time.perf_counter()
    try:
        source = AFLOWSource()
        hits = source.search(SourceQuery(structure_name="ZnO", source="aflow", limit=3))
        row.update({"status": "ok" if hits else "empty",
                    "n_hits": len(hits),
                    "first": hits[0].record_id if hits else None,
                    "seconds": round(time.perf_counter() - started, 2)})
    except Exception as exc:  # noqa: BLE001
        row.update({"status": "fail", "seconds": round(time.perf_counter() - started, 2),
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    return row


def check_materials_project() -> dict:
    from cifkit.sources.materials_project import api_key, mp_available

    key = api_key()
    probe = tcp_probe(*HOSTS["materials-project"])
    row: dict = {"tcp": probe, "key_present": bool(key)}
    if not key:
        row.update({"status": "needs-key",
                    "note": "set MP_API_KEY (never echoed, never written to artifacts)"})
        return row
    started = time.perf_counter()
    try:
        from cifkit.sources.materials_project import MaterialsProjectSource
        from cifkit.types import SourceQuery

        hits = MaterialsProjectSource().search(
            SourceQuery(structure_id="mp-149", source="materials-project", limit=1))
        row.update({"status": "ok" if hits else "empty", "n_hits": len(hits),
                    "first": hits[0].record_id if hits else None,
                    "seconds": round(time.perf_counter() - started, 2)})
    except Exception as exc:  # noqa: BLE001
        row.update({"status": "fail", "seconds": round(time.perf_counter() - started, 2),
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    return row


def check_qmof() -> dict:
    """QMOF ships as a local mirror here; the official download was never reachable."""
    from cifkit.sources.qmof import QMOFSource

    try:
        source = QMOFSource()
        hits = source.search.__self__ if False else None  # keep the import honest
        directory = os.environ.get("CIFKIT_QMOF_DIR") or str(ROOT / "library" / "qmof")
        path = Path(directory)
        count = len(list(path.glob("*.cif"))) if path.is_dir() else 0
        return {"status": "ok" if count else "not-configured",
                "mirror_dir": directory, "n_cif": count, "seconds": 0.0,
                "note": "官方 figshare 下载在本环境不可达；仅有本地镜像时才算可用"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}


def check_local() -> dict:
    from cifkit.cache import project_root

    started = time.perf_counter()
    library = project_root() / "library"
    count = len(list(library.rglob("*.cif"))) if library.is_dir() else 0
    return {"status": "ok", "library": str(library), "n_cif": count,
            "seconds": round(time.perf_counter() - started, 3)}


def render_markdown(report: dict) -> str:
    """Render the live-check report as a Markdown table (pure function)."""
    lines = ["| 数据源 | 状态 | 实测 | 证据 |", "|---|---|---|---|"]
    for name, row in (report.get("sources") or {}).items():
        evidence = row.get("error") or row.get("note") or ""
        if not evidence:
            parts: list[str] = []
            if name == "core-mof":
                parts.append(f"{row.get('n_entries')} 条索引")
            for key in ("by_id", "by_text", "query"):
                nested = row.get(key)
                if isinstance(nested, dict) and nested.get("n_hits") is not None:
                    parts.append(f"{key}: n_hits={nested['n_hits']}"
                                 + (f", first={nested['first']}" if nested.get("first") else ""))
            if row.get("n_hits") is not None:
                parts.append(f"n_hits={row['n_hits']}"
                             + (f", first={row['first']}" if row.get("first") else ""))
            if row.get("n_cif") is not None:
                parts.append(f"{row['n_cif']} 个 CIF")
            if row.get("key_present") is not None:
                parts.append(f"key_present={row['key_present']}")
            evidence = "; ".join(parts)
        latency = row.get("seconds") or (row.get("tcp") or {}).get("seconds")
        lines.append(f"| `{name}` | {row.get('status')} | "
                     f"{latency if latency is not None else '-'} s | {str(evidence)[:90]} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "sources_live.json"))
    ap.add_argument("--markdown", default=str(ROOT / "runs" / "sources_live.md"))
    args = ap.parse_args()

    report: dict = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sources": {}}
    for name, fn in (("core-mof", check_core_mof), ("cod", check_cod), ("aflow", check_aflow),
                     ("materials-project", check_materials_project), ("qmof", check_qmof),
                     ("local", check_local)):
        print(f"== {name} ==")
        try:
            row = fn()
        except Exception as exc:  # noqa: BLE001
            row = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
        report["sources"][name] = row
        print("   ", json.dumps(row, ensure_ascii=False)[:220])

    ok = [name for name, row in report["sources"].items() if row.get("status") == "ok"]
    report["summary"] = {"ok": ok,
                         "needs_key": [n for n, r in report["sources"].items()
                                       if r.get("status") == "needs-key"],
                         "failed": [n for n, r in report["sources"].items()
                                    if r.get("status") == "fail"]}
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nok: {ok}\nsummary: {report['summary']}\nreport: {out}")

    md = Path(args.markdown)
    md.write_text(render_markdown(report), encoding="utf-8")
    print(f"markdown: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
