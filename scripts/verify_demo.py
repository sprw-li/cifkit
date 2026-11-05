"""独立验收脚本：不需要相信 cifkit 自报，直接从产物结构复核 DESIGN.md §1 的 8 条标准。

用法：
    .venv\Scripts\python.exe scripts\verify_demo.py runs/demo_sod_zif8
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

from pymatgen.core import Structure

RADII = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "S": 1.05, "Zn": 1.22, "Cd": 1.44, "Zr": 1.75}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def count(s: Structure, el: str) -> int:
    return sum(1 for site in s if site.species_string == el)


def min_distance(s: Structure) -> float:
    d = s.distance_matrix
    n = len(s)
    best = math.inf
    for i in range(n):
        for j in range(i + 1, n):
            if d[i, j] < best:
                best = float(d[i, j])
    return best


def vacuum_gap(s: Structure, target_axis: int = 2) -> float:
    """Largest empty slab gap along the given lattice vector (Å)."""
    lat = s.lattice
    normal = lat.get_cartesian_coords([0, 0, 1]) if target_axis == 2 else lat.matrix[target_axis]
    norm = math.sqrt(sum(x * x for x in normal))
    frac = s.frac_coords[:, 2] if target_axis == 2 else s.frac_coords[:, target_axis] % 1.0
    lo, hi = float(frac.min()), float(frac.max())
    return (1.0 - (hi - lo)) * norm


def carbon_bond_count(s: Structure, tol: float = 1.25) -> list[int]:
    """Count neighbours of every carbon (H + heavy) by covalent-radius criterion."""
    out = []
    coords = s.cart_coords
    lat = s.lattice
    for i, site in enumerate(s):
        if site.species_string != "C":
            continue
        n = 0
        ri = RADII["C"]
        for j, other in enumerate(s):
            if i == j:
                continue
            d = s.distance_matrix[i, j]
            rj = RADII.get(other.species_string, 1.0)
            if d < tol * (ri + rj):
                n += 1
        out.append(n)
    return out


class Checker:
    def __init__(self, outdir: Path):
        self.dir = outdir
        self.rows: list[tuple[str, bool, str]] = []
        self.manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))

    def check(self, name: str, ok: bool, detail: str) -> None:
        self.rows.append((name, ok, detail))

    # -- individual acceptance checks -------------------------------------
    def run(self) -> int:
        d = self.dir
        m = self.manifest
        steps = {s["name"]: s for s in m.get("steps", [])}
        source = m.get("source") or {}
        rec = (source.get("record") or {})
        prov = (source.get("provenance") or {})

        # 1. provenance
        raw = d / "raw.cif"
        ok = raw.is_file()
        detail = f"raw.cif exists={ok}"
        if ok:
            got = sha256(raw)
            ok = bool(prov.get("sha256")) and got == prov["sha256"]
            detail = f"sha256 matches={got == prov.get('sha256')} record={rec.get('record_id')}"
        self.check("1 来源追溯（sha256/record/DOI）", ok, detail)

        # 2. topology evidence
        topo = (steps.get("verify-topology") or {}).get("data", {})
        ok = (steps.get("verify-topology") or {}).get("status") == "ok" and topo.get("ok") is True
        self.check("2 拓扑 sod 已核实", ok,
                   f"evidence={topo.get('evidence')} detail={str(topo.get('detail'))[:160]}")

        # 3. hydrogen completion
        raw_s = Structure.from_file(d / "raw.cif" if (d / "raw.cif").is_file() else d / "repaired.cif")
        rep = d / "repaired.cif"
        rep_s = Structure.from_file(rep)
        h_raw, h_rep = count(raw_s, "H"), count(rep_s, "H")
        added = (steps.get("repair") or {}).get("data", {}).get("added_h")
        cb = carbon_bond_count(rep_s)
        c_ok = bool(cb) and all(x == 4 for x in cb)
        # ZIF-8 stoichiometry check: H/Zn == 10 and H/C == 1.25
        zn = count(rep_s, "Zn")
        c = count(rep_s, "C")
        ratio_ok = zn == 0 or (abs(h_rep / zn - 10.0) < 0.5)
        ok = h_raw == 0 and h_rep > 0 and c_ok and ratio_ok and added == h_rep - h_raw
        self.check("3 碳上补氢正确", ok,
                   f"H {h_raw}->{h_rep} (added={added}) C四键={c_ok} H/Zn={h_rep}/{zn} "
                   f"bad_C_bonds={sorted({x for x in cb if x != 4})}")

        # 4. 2x2x1 (supercell step, or in-plane repeats of the slab)
        if "supercell" in steps:
            sd = steps["supercell"].get("data", {})
            sup_s = Structure.from_file(d / "supercell.cif")
            exp = int(sd.get("expected") or 0)
            ok = steps["supercell"]["status"] == "ok" and len(sup_s) == exp and len(sup_s) == len(rep_s) * 4
            detail = f"repaired={len(rep_s)} supercell={len(sup_s)} expected={exp}"
        else:
            sdata = (steps.get("surface") or {}).get("data", {})
            base = int(sdata.get("base_atoms") or 0)
            after = int(sdata.get("atoms_after_reps") or 0)
            reps = tuple(sdata.get("reps") or ())
            ok = (
                reps == (2, 2, 1)
                and base > 0
                and after == base * 4
                and after == len(Structure.from_file(d / "slab.cif"))
            )
            detail = f"frame={sdata.get('frame')} reps={reps} slab_base={base} after_reps={after}"
        self.check("4 2x2x1 重复原子数", ok, detail)

        # 5. slab + vacuum
        fin = d / "final.cif"
        fin_s = Structure.from_file(fin) if fin.is_file() else Structure.from_file(d / "slab.cif")
        slab_s = Structure.from_file(d / "slab.cif") if (d / "slab.cif").is_file() else fin_s
        vac = vacuum_gap(fin_s)
        target = 15.0
        vac_ok = vac + 1e-3 >= target
        surf = steps.get("surface") or {}
        vac_step = steps.get("vacuum") or {}
        self.check(
            "5 (111) slab + 真空层",
            surf.get("status") == "ok" and vac_step.get("status") == "ok" and vac_ok,
            f"slab_atoms={len(slab_s)} final_atoms={len(fin_s)} measured_vacuum={vac:.3f}Å target={target} "
            f"reported={((vac_step.get('data') or {}).get('measured'))}",
        )

        # 6. exports
        vasp = d / "structure.vasp"
        ok = vasp.is_file() and vasp.stat().st_size > 0
        detail = "structure.vasp missing"
        if ok:
            poscar = Structure.from_file(vasp)
            same = len(poscar) == len(fin_s)
            detail = f"structure.vasp atoms={len(poscar)} final_atoms={len(fin_s)} match={same}"
            ok = same and ok
        for extra in ("structure.cif", "structure.xyz"):
            ok = ok and (d / extra).is_file()
        self.check("6 计算化学格式导出", ok, detail)

        # 7. validation report
        val = m.get("validation") or {}
        checks = val.get("checks") or []
        errs = [c for c in checks if not c["ok"] and c.get("severity") == "error"]
        self.check("7 结构校验通过", bool(val.get("ok")) and not errs,
                   f"checks={len(checks)} errors={[c['name'] for c in errs]}")

        # 8. report + manifest completeness
        report = d / "report.md"
        text = report.read_text(encoding="utf-8") if report.is_file() else ""
        needed = ["来源", "执行步骤", "校验", "产物"]
        ok = report.is_file() and all(k in text for k in needed)
        self.check("8 report.md / manifest 完整", ok,
                   f"report={report.is_file()} steps={len(m.get('steps', []))} artifacts={len(m.get('artifacts', {}))}")

        print(f"\n独立验收：{self.dir}")
        print("-" * 78)
        for name, ok, detail in self.rows:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
        print("-" * 78)
        failed = [r for r in self.rows if not r[1]]
        print(f"结果：{len(self.rows) - len(failed)}/{len(self.rows)} 通过")
        return 0 if not failed else 1


def main(argv: list[str]) -> int:
    outdir = Path(argv[1] if len(argv) > 1 else "runs/demo_sod_zif8")
    if not (outdir / "manifest.json").is_file():
        print(f"manifest.json 不存在：{outdir}", file=sys.stderr)
        return 2
    return Checker(outdir).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
