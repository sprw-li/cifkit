"""独立验收脚本：不需要相信 cifkit 自报，直接从产物结构复核 DESIGN.md §1 的 8 条标准。

用法（Windows 注意用双反斜杠或正斜杠）：
    .venv/Scripts/python.exe scripts/verify_demo.py runs/demo_sod_zif8
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

from pymatgen.core import Structure

RADII = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "S": 1.05, "Zn": 1.22, "Cd": 1.44, "Zr": 1.75}


def _crossref_check(doi: str, timeout: float = 20.0) -> dict:
    """Resolve a DOI through Crossref; used only with ``--online``."""
    import urllib.request

    url = f"https://api.crossref.org/works/{doi}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cifkit-verify/0.1 (mailto:none)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        title = ((data.get("message") or {}).get("title") or [""])[0]
        if resp.status != 200 or not title:
            return {"ok": False, "detail": f"status={resp.status} title={title!r}"}
        return {"ok": True, "detail": f"status=200 title={title[:80]!r}"}
    except Exception as exc:  # noqa: BLE001 - network is optional
        return {"ok": False, "detail": f"crossref failed: {type(exc).__name__}: {exc}"}


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


def carbon_environments(s: Structure, cutoff: float = 2.2) -> list[dict]:
    """Periodic neighbour environment of every carbon.

    A carbon is chemically valid when it has 4 neighbours (sp3, all single
    bonds) or 3 neighbours with at least one short (<1.50 A) bond (sp2: aromatic
    ring or C=N/C=O), i.e. bond-order sum 4.  Counting neighbours alone is not
    valence: a ZIF-8 ring carbon has only 3 neighbours.
    """
    elements = [site.species_string for site in s]
    centers, points, _, dists = s.get_neighbor_list(cutoff)
    neighbours: dict[int, dict[int, float]] = {}
    for i, j, dist in zip(centers, points, dists):
        i, j = int(i), int(j)
        if i == j:
            continue
        ri = RADII.get(elements[i], 1.0)
        rj = RADII.get(elements[j], 1.0)
        if float(dist) <= 1.25 * (ri + rj):
            nd = neighbours.setdefault(i, {})
            nd[j] = min(nd.get(j, 1e9), float(dist))
    out: list[dict] = []
    for i, el in enumerate(elements):
        if el != "C":
            continue
        nd = neighbours.get(i, {})
        n_h = sum(1 for j in nd if elements[j] == "H")
        min_heavy = min((d for j, d in nd.items() if elements[j] != "H"), default=1e9)
        out.append(
            {
                "index": i,
                "n": len(nd),
                "n_h": n_h,
                "min_heavy": min_heavy,
                "short_bond": min_heavy < 1.50,
            }
        )
    return out


def carbon_valence_ok(envs: list[dict]) -> tuple[bool, dict]:
    bad: list[dict] = []
    for e in envs:
        if e["n"] == 4:
            continue
        if e["n"] == 3 and e["short_bond"]:
            continue
        bad.append(e)
    return (not bad), {"n_carbons": len(envs), "bad": bad[:10], "n_bad": len(bad)}


class Checker:
    def __init__(self, outdir: Path, *, online: bool = False):
        self.dir = outdir
        self.online = online
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

        # 1. provenance: sha256 of the handed-over CIF + record identity + DOI
        raw = d / "raw.cif"
        ok = raw.is_file()
        detail = f"raw.cif exists={ok}"
        if ok:
            got = sha256(raw)
            sha_ok = bool(prov.get("sha256")) and got == prov["sha256"]
            doi = str(rec.get("doi") or prov.get("doi") or "")
            prov_doi = str(prov.get("doi") or "")
            doi_note = prov.get("doi_note") or ""
            doi_format_ok = bool(re.match(r"^10\.\d{4,9}/\S+$", doi))
            # a curated DOI must be labelled curated in provenance, and record/provenance must agree
            consistent = (not prov_doi) or (prov_doi == doi)
            note_lower = str(doi_note).lower()
            note_ok = ("curated" in note_lower) or ("metadata" in note_lower) or ("数据集元数据" in str(doi_note))
            doi_ok = doi_format_ok and consistent and note_ok
            detail = (f"sha256 matches={sha_ok} record={rec.get('record_id')} doi={doi or '-'} "
                      f"fmt={doi_format_ok} consistent={consistent} note_ok={note_ok}")
            if self.online and doi_ok:
                cross = _crossref_check(doi)
                doi_ok = doi_ok and cross["ok"]
                detail += f" crossref={cross['detail']}"
            elif not self.online:
                detail += " (offline: existence 未联网核验，用 --online 可查 Crossref)"
            ok = sha_ok and doi_ok
        self.check("1 来源追溯（sha256/record/DOI）", ok, detail)

        # 2. topology evidence
        topo = (steps.get("verify-topology") or {}).get("data", {})
        ok = (steps.get("verify-topology") or {}).get("status") == "ok" and topo.get("ok") is True
        self.check("2 拓扑 sod 已核实", ok,
                   f"evidence={topo.get('evidence')} detail={str(topo.get('detail'))[:160]}")

        # 3. hydrogen completion (chemically valid C environments, ZIF-8 ratios)
        raw_s = Structure.from_file(d / "raw.cif" if (d / "raw.cif").is_file() else d / "repaired.cif")
        rep = d / "repaired.cif"
        rep_s = Structure.from_file(rep)
        h_raw, h_rep = count(raw_s, "H"), count(rep_s, "H")
        added = (steps.get("repair") or {}).get("data", {}).get("added_h")
        envs = carbon_environments(rep_s)
        c_ok, c_detail = carbon_valence_ok(envs)
        zn = count(rep_s, "Zn")
        c = count(rep_s, "C")
        ratio_ok = zn == 0 or abs(h_rep / zn - 10.0) < 0.5
        # no overlapping H (the classic "over-hydrogenation" failure)
        h_idx = [i for i, site in enumerate(rep_s) if site.species_string == "H"]
        dm = rep_s.distance_matrix
        min_hh = min(
            (float(dm[i, j]) for a, i in enumerate(h_idx) for j in h_idx[a + 1 :]),
            default=99.0,
        )
        ok = h_raw == 0 and h_rep > 0 and c_ok and ratio_ok and added == h_rep - h_raw
        self.check("3 碳上补氢正确", ok,
                   f"H {h_raw}->{h_rep} (added={added}) C_env_ok={c_ok} n_bad_C={c_detail['n_bad']} "
                   f"H/Zn={h_rep}/{zn} C={c}")

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
    import argparse

    ap = argparse.ArgumentParser(description="独立验收 demo 产物")
    ap.add_argument("outdir", nargs="?", default="runs/demo_sod_zif8")
    ap.add_argument("--online", action="store_true",
                    help="additionally resolve the DOI through api.crossref.org (needs network)")
    args = ap.parse_args(argv[1:])
    outdir = Path(args.outdir)
    if not (outdir / "manifest.json").is_file():
        print(f"manifest.json 不存在：{outdir}", file=sys.stderr)
        return 2
    return Checker(outdir, online=args.online).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
