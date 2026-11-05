"""Acceptance self-check for the u3_metals deliverable.

Re-runs the acceptance criteria from the task without trusting the generated
tables blindly: it re-reads the files on disk, re-parses POSCAR/CIF files,
re-validates >= 10 slabs and checks that the numbers quoted in README.md match
the actual tables.  Exits non-zero if any check fails.

Usage::

    python usecases/u3_metals/scripts/verify_deliverables.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cifkit.types import TaskSpec  # noqa: E402
from cifkit.validate import validate_structure  # noqa: E402

KIT = Path(__file__).resolve().parents[1]
DATA = KIT / "data"
ELEMENTS = KIT / "elements"
VACUUM = 15.0
REQUIRED = ["bulk.cif", "bulk_POSCAR", "slab.cif", "slab_POSCAR", "lattice.csv", "INCAR", "KPOINTS"]
CRITICAL = {
    "Fe": "(110)",
    "Cu": "(111)",
    "Mg": "(0001)",
    "Al": "(111)",
    "W": "(110)",
}
VALIDATE_AT_LEAST = 10

_results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return bool(ok)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    stats = json.loads((DATA / "summary_stats.json").read_text(encoding="utf-8"))
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    failures = json.loads((DATA / "failures.json").read_text(encoding="utf-8"))
    summary = read_csv(KIT / "metals_summary.csv")
    lattice = read_csv(KIT / "lattice.csv")
    report = read_csv(DATA / "run_report.csv")
    validation = read_csv(DATA / "slab_validation.csv")

    # ---- 1. element dirs / files ----------------------------------------
    dirs = sorted(p.name for p in ELEMENTS.iterdir() if p.is_dir())
    check("元素目录数 = records 数", len(dirs) == len(records), f"{len(dirs)} dirs vs {len(records)} records")
    check("元素目录数 = summary_stats.n_exported", len(dirs) == stats["n_exported"],
          f"{len(dirs)} vs {stats['n_exported']}")
    missing_files = [(el, f) for el in dirs for f in REQUIRED if not (ELEMENTS / el / f).exists()]
    check("每个元素目录含 7 个必需文件", not missing_files, f"{len(missing_files)} missing: {missing_files[:5]}")

    # ---- 2. tables consistency ------------------------------------------
    check("lattice.csv 行数 = 目录数", len(lattice) == len(dirs), f"{len(lattice)} rows vs {len(dirs)} dirs")
    check("metals_summary.csv 行数 = 目录数", len(summary) == len(dirs), f"{len(summary)} rows vs {len(dirs)} dirs")
    check("run_report.csv 行数 = 87", len(report) == 87, f"{len(report)} rows")
    statuses = [r["status"] for r in report]
    n_ok = sum(1 for s in statuses if s.startswith("ok"))
    n_fail = sum(1 for s in statuses if s == "failed")
    check("run_report: ok 数 = 导出数", n_ok == stats["n_exported"], f"ok={n_ok} exported={stats['n_exported']}")
    check("run_report: failed 数 = missing 数", n_fail == stats["n_missing"], f"failed={n_fail} missing={stats['n_missing']}")
    fail_reasons = [r for r in report if r["status"] == "failed" and not r["reason"].strip()]
    check("每个 failed 都有 reason", not fail_reasons, f"{len(fail_reasons)} without reason")
    no_lattice = [r["element"] for r in summary if not (ELEMENTS / r["element"] / "lattice.csv").exists()]
    check("summary 的每个元素都有目录", not no_lattice, f"{no_lattice[:5]}")

    # ---- 3. critical planes --------------------------------------------
    by_el = {r["element"]: r for r in summary}
    for el, plane in CRITICAL.items():
        got = by_el.get(el, {}).get("densest_plane")
        check(f"{el} densest_plane = {plane}", got == plane, f"got {got}")

    # ---- 4. vacuum / slab sanity for every row --------------------------
    bad_vac = [r["element"] for r in summary if float(r["vacuum_measured"]) + 1e-6 < VACUUM]
    check("全部 slab 真空 >= 15 A", not bad_vac, f"{bad_vac[:5]}")
    bad_atoms = [r["element"] for r in summary if int(r["slab_atoms"]) <= 0]
    check("全部 slab 原子数 > 0", not bad_atoms, f"{bad_atoms[:5]}")
    too_thin = [
        (r["element"], float(r["slab_thickness"]), int(r["n_atomic_layers"]))
        for r in summary
        if float(r["slab_thickness"]) < 10.0 and int(r["n_atomic_layers"]) < 3
    ]
    check("薄 slab 均有 >= 3 层", not too_thin, f"{too_thin[:5]}")

    # ---- 5. POSCAR / CIF re-parse --------------------------------------
    bad_poscar = []
    for el in dirs:
        for name in ("bulk_POSCAR", "slab_POSCAR"):
            try:
                pos = Poscar.from_file(str(ELEMENTS / el / name))
                if len(pos.structure) == 0:
                    bad_poscar.append(f"{el}/{name}: empty")
            except Exception as exc:  # noqa: BLE001
                bad_poscar.append(f"{el}/{name}: {exc}")
    check("全部 POSCAR 可解析", not bad_poscar, f"{bad_poscar[:3]}")
    bad_cif = []
    for el in dirs:
        for name in ("bulk.cif", "slab.cif"):
            try:
                st = Structure.from_file(str(ELEMENTS / el / name))
                if len(st) == 0:
                    bad_cif.append(f"{el}/{name}: empty")
            except Exception as exc:  # noqa: BLE001
                bad_cif.append(f"{el}/{name}: {exc}")
    check("全部 CIF 可解析", not bad_cif, f"{bad_cif[:3]}")

    # ---- 6. independent slab re-validation (fresh, not the stored CSV) ---
    picks = [el for el in ["Fe", "Cu", "Mg", "Al", "W", "Ti", "Nb", "Ni", "Zn", "Co",
                           "In", "Sn", "Hg", "Sm", "Bi", "Mn", "Ga", "U", "Pa"] if el in dirs]
    spec = TaskSpec(query="metal slab", vacuum=VACUUM)
    failed = []
    for el in picks:
        st = Structure.from_file(str(ELEMENTS / el / "slab.cif"))
        rep = validate_structure(st, spec=spec)
        m = rep.metrics
        ok = (
            rep.ok
            and (m.get("vacuum_measured") or 0) + 1e-6 >= VACUUM
            and (m.get("duplicate_pairs") or 0) == 0
        )
        if not ok:
            failed.append((el, [c.name for c in rep.checks if not c.ok and getattr(c, "severity", "") == "error"]))
    check(
        f"独立复验 >= {VALIDATE_AT_LEAST} 个 slab（本次 {len(picks)} 个）",
        len(picks) >= VALIDATE_AT_LEAST and not failed,
        f"failed={failed}",
    )
    check("slab_validation.csv 记录数 >= 10 且全部通过",
          len(validation) >= VALIDATE_AT_LEAST
          and all(bool(r["ok"]) and bool(r["vacuum_ok"]) and bool(r["duplicates_ok"]) for r in validation),
          f"{len(validation)} rows")

    # ---- 7. zip ---------------------------------------------------------
    zip_path = KIT / "metals_kit.zip"
    if not check("metals_kit.zip 存在", zip_path.exists(), str(zip_path)):
        return 1
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        names = set(zf.namelist())
    check("zip 完整性（testzip）", bad is None, f"bad entry: {bad}")
    need = ["README.md", "metals_summary.csv", "lattice.csv", "surface_energy/INCAR",
            "surface_energy/KPOINTS", "surface_energy/README.md", "data/run_report.csv",
            "scripts/export_metals.py", "elements/Fe/bulk_POSCAR", "elements/Fe/slab_POSCAR"]
    missing_in_zip = [n for n in need if n not in names]
    check("zip 含关键文件", not missing_in_zip, f"missing: {missing_in_zip}")
    zip_el = {n.split("/")[1] for n in names if n.startswith("elements/")}
    check("zip 内元素目录数 = 导出数", len(zip_el) == stats["n_exported"], f"{len(zip_el)} vs {stats['n_exported']}")

    # ---- 8. README numbers ---------------------------------------------
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    nums_ok = True
    for label, value in [
        ("金属总数", stats["n_metals_total"]),
        ("成功导出", stats["n_exported"]),
        ("missing", stats["n_missing"]),
    ]:
        if str(value) not in readme:
            nums_ok = False
            print(f"    README 缺少 {label} = {value}")
    check("README 数字与统计一致", nums_ok, f"{stats['n_metals_total']}/{stats['n_exported']}/{stats['n_missing']}")
    plane_counts_readme = re.findall(r"\| \*\*(\d+)\*\* \|", readme)
    check("README 含关键数字表格", len(plane_counts_readme) >= 1, str(plane_counts_readme[:5]))

    # ---- 9. summary -----------------------------------------------------
    n_pass = sum(1 for ok, _, _ in _results if ok)
    n_all = len(_results)
    print(f"\n{'=' * 60}\n验收: {n_pass}/{n_all} 通过")
    if n_pass != n_all:
        for ok, name, detail in _results:
            if not ok:
                print(f"  FAILED: {name} -- {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
