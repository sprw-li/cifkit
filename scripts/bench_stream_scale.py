"""Scale test for the streaming dataset (limitations F6/F7).

The earlier 8–12 run measurement could not show a memory difference because
pymatgen's per-structure working memory dominates at that size (peak ratio
1.17x / 0.94x — i.e. noise).  This script builds a **thousands-of-runs** corpus of
tiny synthetic structures and measures both build modes with a warm-up, so the
question "does streaming actually help?" gets a real answer instead of a claim.

    .venv\\Scripts\\python.exe scripts\\bench_stream_scale.py [--runs 2000] [--rdf] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CIF_TEMPLATE = """data_run{i}
_cell_length_a {a:.3f}
_cell_length_b {a:.3f}
_cell_length_c {a:.3f}
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
S1 S 0.00 0.00 0.00
M1 M {x:.3f} 0.200 0.300
M2 M 0.400 {y:.3f} 0.600
O1 O 0.500 0.500 0.500
O2 O 0.250 0.750 0.100
"""


def make_corpus(root: Path, count: int, *, refresh: bool = False) -> Path:
    """Create `count` run directories, each a manifest + one tiny CIF."""
    marker = root / ".complete"
    if marker.is_file() and not refresh:
        # only reuse a corpus of exactly the requested size (otherwise the
        # measurement silently describes a different corpus than the report says)
        try:
            recorded = int(marker.read_text(encoding="utf-8").split("=")[1])
        except Exception:  # noqa: BLE001
            recorded = -1
        if recorded == count:
            return root
    if root.exists():
        shutil.rmtree(root)
    for index in range(count):
        run = root / f"run{index:05d}"
        run.mkdir(parents=True)
        # element "M" is not a real symbol; use Zn instead so pymatgen parses it
        text = CIF_TEMPLATE.format(i=index, a=8.0 + (index % 7) * 0.05,
                                   x=0.100 + (index % 7) * 0.01,
                                   y=0.200 + (index % 5) * 0.01).replace("M1 M", "M1 Zn").replace(
            "M2 M", "M2 Zn")
        cif = run / "standardized.cif"
        cif.write_text(text, encoding="utf-8")
        (run / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(cif)},
            "source": {"source": "local",
                       "record": {"record_id": f"local:{index}", "topology": "sod"}},
        }), encoding="utf-8")
    marker.write_text(f"count={count}\n", encoding="utf-8")
    return root


def measure(root: Path, outdir: Path, *, stream: bool, rdf: bool) -> dict:
    from cifkit.dataset import build_dataset

    # warm-up (imports, file cache) outside the traced region
    build_dataset(root, outdir.with_name(outdir.name + "_warm"), rdf=rdf, stream=stream,
                  copy_structures=False)
    tracemalloc.start()
    started = time.perf_counter()
    summary = build_dataset(root, outdir, rdf=rdf, stream=stream, copy_structures=False)
    wall = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"mode": summary["mode"], "n_runs": summary["n_runs"], "n_ok": summary["n_ok"],
            "wall_s": round(wall, 3), "peak_mib": round(peak / 1048576, 2),
            "max_rows_held": summary["max_rows_held"],
            "csv_sha256": summary["csv_sha256"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2000)
    ap.add_argument("--rdf", action="store_true", help="include RDF columns (bigger rows)")
    ap.add_argument("--refresh", action="store_true", help="rebuild the corpus")
    ap.add_argument("--json", default=str(ROOT / "runs" / "bench_stream_scale.json"))
    args = ap.parse_args()

    work = ROOT / "runs" / "bench_scale"
    corpus = make_corpus(work / "runs", args.runs, refresh=args.refresh)
    print(f"corpus: {args.runs} runs at {corpus} (rdf={args.rdf})")

    stream = measure(corpus, work / "out_stream", stream=True, rdf=args.rdf)
    material = measure(corpus, work / "out_materialised", stream=False, rdf=args.rdf)
    report = {
        "runs": args.runs,
        "rdf": args.rdf,
        "stream": stream,
        "materialised": material,
        "wall_ratio": round(material["wall_s"] / stream["wall_s"], 2) if stream["wall_s"] else None,
        "peak_ratio": round(material["peak_mib"] / stream["peak_mib"], 2) if stream["peak_mib"] else None,
        "same_csv": stream["csv_sha256"] == material["csv_sha256"],
        "note": ("tracemalloc 峰值（含预热）；CSV 哈希相同说明两种模式输出一致。"
                 "max_rows_held 是结构性证据：流式恒为 1。"),
    }
    for mode in ("stream", "materialised"):
        row = report[mode]
        print(f"  {mode:14s} wall={row['wall_s']:8.2f}s peak={row['peak_mib']:8.2f} MiB "
              f"max_rows_held={row['max_rows_held']}")
    print(f"  peak ratio (materialised/stream) = {report['peak_ratio']}, "
          f"wall ratio = {report['wall_ratio']}, same CSV = {report['same_csv']}")

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
