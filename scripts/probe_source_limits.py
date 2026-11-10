"""How do the real public endpoints rate-limit us?  Measure, politely.

Limitation A6 said the backoff/retry behaviour was only verified against a local
mock server — the real quotas were unknown.  This probe makes a **small, polite**
number of requests to COD and AFLOW through the production ``HttpClient`` and
records what actually comes back:

* status codes and latencies for a paced series (default 0.25 s/request);
* a short *unpaced* burst (3 requests) to see whether the server pushes back
  (429/503), and whether our retry/backoff engages;
* the client's own counters (``stats``) and whether any ``Retry-After`` was seen.

Deliberately **not** a load test: at most 3 unpaced requests per host, then stop.
Results are observations with timestamps, not an SLA.

    .venv\\Scripts\\python.exe scripts\\probe_source_limits.py [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: small, cheap, stable GETs (one result page each); AFLOW's directory layout is
#: not guessable, so its URL is discovered through the adapter below
TARGETS = {
    "cod": "https://www.crystallography.net/cod/result?text=ZIF-8&format=json",
}


def discover_aflow_url() -> str | None:
    """Ask the AFLOW adapter for a real CIF URL instead of guessing paths."""
    try:
        from cifkit.sources.aflow import AFLOWSource
        from cifkit.types import SourceQuery

        hits = AFLOWSource().search(SourceQuery(structure_name="ZnO", limit=1))
        if not hits:
            return None
        url = getattr(hits[0], "url", None)
        if url:
            return url
        # fall back to the adapter's own resolver
        source = AFLOWSource()
        return getattr(source, "_cif_url", lambda record: None)(hits[0])
    except Exception:  # noqa: BLE001
        return None


def probe(client, url: str, n: int) -> list[dict]:
    rows = []
    for index in range(n):
        started = time.perf_counter()
        try:
            payload = client.get(url)
            rows.append({"i": index, "ok": True, "bytes": len(payload),
                         "seconds": round(time.perf_counter() - started, 3)})
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status", None)
            rows.append({"i": index, "ok": False, "status": status,
                         "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                         "seconds": round(time.perf_counter() - started, 3)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "source_limits.json"))
    ap.add_argument("--paced", type=int, default=5)
    ap.add_argument("--burst", type=int, default=5)
    args = ap.parse_args()

    from cifkit.sources.http import HttpClient

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "policy": {"paced_requests": args.paced, "unpaced_burst": args.burst,
                               "note": "deliberately small; not a load test"},
                    "hosts": {}}

    targets = dict(TARGETS)
    aflow_url = discover_aflow_url()
    if aflow_url:
        targets["aflow"] = aflow_url
    else:
        report["aflow_url"] = "could not discover (adapter search failed)"
        print("aflow: could not discover a CIF URL, skipping")

    for name, url in targets.items():
        # 1) production pacing + retries (as the library would use them)
        paced_client = HttpClient(min_interval=0.25, retries=2, timeout=20.0)
        paced = probe(paced_client, url, args.paced)
        # 2) short unpaced burst with retries disabled, to observe server push-back
        burst_client = HttpClient(min_interval=0.0, retries=0, timeout=20.0)
        burst = probe(burst_client, url, args.burst)
        report["hosts"][name] = {"url": url, "paced": paced, "burst": burst,
                                 "paced_stats": dict(paced_client.stats),
                                 "burst_stats": dict(burst_client.stats)}
        paced_seconds = [row["seconds"] for row in paced if row.get("ok")]
        report["hosts"][name]["paced_latency_median_s"] = (
            sorted(paced_seconds)[len(paced_seconds) // 2] if paced_seconds else None)
        pushback = [row for row in burst if not row.get("ok")]
        rate_limited = [row for row in burst + paced
                        if row.get("status") in (429, 503)]
        report["hosts"][name]["server_pushback"] = bool(pushback)
        report["hosts"][name]["rate_limited_statuses"] = [row["status"] for row in rate_limited]
        report["hosts"][name]["retry_after_seen"] = any(
            "retry-after" in json.dumps(row).lower() for row in paced + burst)
        print(f"== {name} ==")
        for row in paced:
            print("   paced ", json.dumps(row, ensure_ascii=False))
        for row in burst:
            print("   burst ", json.dumps(row, ensure_ascii=False))

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
