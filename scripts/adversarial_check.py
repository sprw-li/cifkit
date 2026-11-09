"""Adversarial round-10 self-verification (Lead-run; the delegated reviewer agent failed).

Unlike ``tests/`` which asserts intended behaviour, this script tries to BREAK the
four round-10 changes: single vs batch convert semantics, duplicate stems, bad
inputs, unknown bundles, whether ``verify_formats`` can be fooled, ring-count
semantics cross-checked against an independent formula, and whether the
``check_all`` skill group is really wired to the external script.

    .venv\\Scripts\\python.exe scripts\\adversarial_check.py [--work DIR]

Exit code 0 when every check passes; 1 otherwise.  Results are written to
``<work>/adversarial_check.json``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")


def run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), "-m", "cifkit", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def loads(text: str) -> dict:
    raw = text.encode("utf-8", "surrogatepass")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return json.loads(raw.decode("utf-16"))
    return json.loads(text.lstrip("\ufeff"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(ROOT / "runs" / "lead_verify_r11"))
    args = ap.parse_args()
    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 1) convert
    single = work / "single"
    proc = run(["convert", str(ZIF8), "--to", "vasp,xyz", "--outdir", str(single), "--json"])
    data = loads(proc.stdout)
    check("convert single: exit 0 + files at outdir root",
          proc.returncode == 0 and (single / f"{ZIF8.stem}.vasp").is_file()
          and (single / f"{ZIF8.stem}.xyz").is_file() and "runs" not in data,
          f"exit={proc.returncode} files={sorted(p.name for p in single.iterdir())}")

    batch_src = work / "src"
    batch_src.mkdir()
    shutil.copyfile(ZIF8, batch_src / "a.cif")
    shutil.copyfile(ZIF8, batch_src / "b.CIF")
    shutil.copyfile(ZIF8, batch_src / "c.cif")
    out = work / "batch"
    proc = run(["convert", str(batch_src), "--to", "vasp", "--outdir", str(out), "--json"])
    data = loads(proc.stdout)
    check("convert batch: case-insensitive dedupe (3 inputs, not 6)",
          proc.returncode == 0 and data["n_inputs"] == 3 and data["n_ok"] == 3,
          f"n_inputs={data['n_inputs']} n_ok={data['n_ok']}")
    manifest = json.loads((out / "convert_manifest.json").read_text(encoding="utf-8"))
    check("convert batch: manifest has per-run outdir",
          all("outdir" in r and Path(r["outdir"]).is_dir() for r in manifest["runs"]),
          f"run outdirs={[Path(r['outdir']).name for r in manifest['runs']]}")

    # stem collision across two directories must NOT overwrite (explicit file list)
    coll = work / "coll"
    (coll / "d1").mkdir(parents=True)
    (coll / "d2").mkdir(parents=True)
    shutil.copyfile(ZIF8, coll / "d1" / "same.cif")
    shutil.copyfile(ZIF8, coll / "d2" / "same.cif")
    proc = run(["convert", str(coll / "d1" / "same.cif"), str(coll / "d2" / "same.cif"),
                "--to", "vasp", "--outdir", str(work / "coll_out"), "--json"])
    data = loads(proc.stdout)
    written = sorted(p.name for p in (work / "coll_out").glob("*/same*.vasp"))
    check("convert batch: same stem from two dirs is disambiguated (2 distinct outputs)",
          data["n_inputs"] == 2 and data["n_ok"] == 2 and len(written) == 2,
          f"n_inputs={data['n_inputs']} outputs={written}")

    # nested directories are NOT scanned recursively (documented behaviour)
    proc = run(["convert", str(coll), "--to", "vasp", "--outdir", str(work / "nested"), "--json"])
    check("convert batch: nested dirs without top-level *.cif -> clear error",
          proc.returncode != 0 and "没有" in (proc.stderr or ""),
          f"exit={proc.returncode} stderr={proc.stderr.strip()[:70]}")

    mixed = work / "mixed"
    mixed.mkdir()
    shutil.copyfile(ZIF8, mixed / "good.cif")
    (mixed / "bad.cif").write_text("not a cif\n", encoding="utf-8")
    proc = run(["convert", str(mixed), "--to", "vasp", "--outdir", str(work / "mixed_out"), "--json"])
    data = loads(proc.stdout)
    check("convert: bad input -> exit 1 but good input converted",
          proc.returncode == 1 and data["n_ok"] == 1 and data["n_failed"] == 1
          and (work / "mixed_out" / "good" / "good.vasp").is_file(),
          f"exit={proc.returncode} ok={data['n_ok']} failed={data['n_failed']}")

    proc = run(["convert", str(ZIF8), "--bundle", "nope", "--outdir", str(work / "ub"), "--json"])
    check("convert: unknown bundle -> exit 2 with available list",
          proc.returncode == 2 and "bundle" in (proc.stderr or "").lower(),
          f"exit={proc.returncode} stderr={proc.stderr.strip()[:80]}")

    # ---------------------------------------------------- 2) verify_formats
    vf_out = work / "vf"
    proc = subprocess.run([str(PY), str(ROOT / "scripts" / "verify_formats.py"),
                           "--outdir", str(vf_out)],
                          cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                          timeout=1800)
    report = json.loads((vf_out / "verify_formats.json").read_text(encoding="utf-8"))
    check("verify_formats: full run 31/31 + 25 third-party + 12 bundles",
          proc.returncode == 0 and report["n_ok"] == 31 and report["n_third_party_ok"] == 25
          and report["n_bundles"] == 12 and report["bundles_ok"] is True,
          f"formats={report['n_ok']}/{report['n_formats']} "
          f"tp={report['n_third_party_ok']}/{report['n_third_party_readback']} "
          f"bundles_ok={report['bundles_ok']}")
    readers = {r["format"]: r["reader"] for r in report["formats"]}
    templates = {f for f, r in readers.items() if r == "structural-check"}
    check("verify_formats: templates labelled, not claimed as read-back",
          templates == {"cp2k", "siesta", "abacus", "orca", "dftb"} and "软件接受" in report["note"],
          f"templates={sorted(templates)}")

    from pymatgen.core import Lattice, Structure

    bad_cif = vf_out / "corrupt.cif"
    bad_cif.write_text("data_bad\n_cell_length_a 1\n", encoding="utf-8")
    try:
        Structure.from_file(str(bad_cif))
        corrupt_detected = False
    except Exception:  # noqa: BLE001
        corrupt_detected = True
    check("verify_formats premise: a corrupt CIF is actually rejected by the reader",
          corrupt_detected, "pymatgen raised on the truncated file")

    # -------------------------------------------------- 3) ring statistics
    from cifkit.features import extract_features
    from cifkit.topology import ring_statistics

    diamond = Structure(Lattice.cubic(3.567), ["C"] * 8,
                        [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0],
                         [.25, .25, .25], [.25, .75, .75], [.75, .25, .75], [.75, .75, .25]])
    stats = ring_statistics(diamond)
    check("ring_statistics: diamond 6-rings == 16/cell (independent formula 8*12/6)",
          stats["rings_per_cell"]["6"] == 16.0 and stats["n_bonds"] == 16
          and stats["truncated"] is False,
          f"6-rings={stats['rings_per_cell']['6']} bonds={stats['n_bonds']}")
    sums = {k: round(v * int(k), 3) for k, v in stats["rings_per_cell"].items()}
    check("ring_statistics: canonical rings (size*per_cell integral)",
          all(abs(v - round(v)) < 1e-6 for v in sums.values()), f"size*per_cell={sums}")

    tiny = Structure(Lattice.cubic(3.0), ["C"], [[0, 0, 0]])
    check("ring_statistics: isolated atom -> zero rings, no crash",
          ring_statistics(tiny)["rings_per_cell"]["6"] == 0.0,
          f"result={ring_statistics(tiny)['rings_per_cell']}")

    big = Structure(Lattice.cubic(30.0), ["C"] * 700, [[i / 700, 0, 0] for i in range(700)])
    big_stats = ring_statistics(big)
    check("ring_statistics: >600 atoms returns truncated instead of running",
          big_stats["truncated"] is True and big_stats["ring_sizes"] == [],
          f"truncated={big_stats['truncated']} warnings={big_stats['warnings'][:1]}")

    fz = extract_features(Structure.from_file(str(ZIF8)), rdf=False, rings=True)
    fd = extract_features(diamond, rdf=False, rings=True)
    check("features --rings: metal vs non-metal basis",
          fz["ring_basis"] == "metal-net" and fd["ring_basis"] == "full-bond-graph"
          and json.loads(fd["rings_per_cell"])["6"] == 16.0,
          f"zif8={fz['ring_basis']} diamond={fd['ring_basis']}")

    # ---------------------------------------------------- 4) check_all group
    text = (ROOT / "scripts" / "check_all.py").read_text(encoding="utf-8")
    check("check_all: check_skill group wired to the real script",
          "check_skill.py" in text and "check_skills()" in text
          and '"check_skill cif-*"' in text and "--skip-agentlib" in text,
          "helper runs catalog/skill-retro/scripts/check_skill.py over cif-* skills")

    print("\n== summary ==")
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("failed:", failed)
    (work / "adversarial_check.json").write_text(
        json.dumps([{"check": n, "ok": ok, "detail": d} for n, ok, d in results],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
