"""Lead independent verification v3: fix column names, add Fe3C composition matching."""
import csv
import json
import math
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore")
import spglib
from pymatgen.core import Composition, Lattice, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

ROOT = Path(r"D:\Dev\Project5-skill-cif\usecases")
issues = []


def report(name, ok, detail):
    print(("[PASS] " if ok else "[FAIL] ") + name + " :: " + str(detail)[:220])
    if not ok:
        issues.append((name, detail))


# ---------------- u1 ----------------
p = ROOT / "u1_fd3m"
rows = list(csv.DictReader((p / "data/examples.csv").open(encoding="utf-8-sig")))
cifs = sorted((p / "data/structures").glob("*.cif"))
bads = []
for cif in cifs:
    s = Structure.from_file(cif)
    sg = SpacegroupAnalyzer(s, symprec=0.05).get_space_group_number()
    if sg != 227:
        bads.append((cif.name, sg))
report("u1 6 CIFs all spglib #227", len(cifs) >= 6 and not bads, f"files={len(cifs)} bad={bads}")
report("u1 CSV sg_number all 227", {str(r["sg_number"]) for r in rows} == {"227"},
       {str(r["sg_number"]) for r in rows})
report("u1 CSV verified_227 all true", all(str(r["verified_227"]).lower() in ("yes", "true", "1") for r in rows), "")
img = p / "figures/fd3m_examples.png"
report("u1 PNG >500KB", img.is_file() and img.stat().st_size > 500_000, img.stat().st_size if img.is_file() else 0)

# ---------------- u2 ----------------
p2 = ROOT / "u2_bravais"
bain = list(csv.DictReader((p2 / "data/bain_path.csv").open(encoding="utf-8-sig")))
report("u2 bain rows>=80", len(bain) >= 80, len(bain))
report("u2 tI#139 majority", sum(r["spacegroup_number"] == "139" for r in bain) >= 75,
       sum(r["spacegroup_number"] == "139" for r in bain))
report("u2 c/a=1 -> #229", [r["spacegroup_number"] for r in bain if r["c_over_a"] in ("1", "1.0")] == ["229"], "")
report("u2 c/a=sqrt2 -> #225", [r["spacegroup_number"] for r in bain if abs(float(r["c_over_a"]) - math.sqrt(2)) < 1e-6] == ["225"], "")
a_t = 3.615 / math.sqrt(2.0)
lat = Lattice([[a_t, 0, 0], [0, a_t, 0], [0, 0, a_t * math.sqrt(2)]])
st = Structure(lat, ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0.5]])
ds = spglib.get_symmetry_dataset((st.lattice.matrix, [1, 1], [s.frac_coords for s in st]), symprec=0.01) if False else \
     spglib.get_symmetry_dataset((st.lattice.matrix, [site.frac_coords for site in st], [29, 29]), symprec=0.01)
report("u2 independent spglib bct(c/a=sqrt2)->#225", ds.number == 225, f"{ds.number} {ds.international}")
br = list(csv.DictReader((p2 / "data/bravais14.csv").open(encoding="utf-8-sig")))
sgs = [r["sg_number"] for r in br]
report("u2 14 Bravais rows, unique SG, all verified", len(br) == 14 and len(set(sgs)) == 14 and all(str(r["verified"]).lower() in ("yes", "true", "1") for r in br), sgs)
eq = list(csv.DictReader((p2 / "data/equivalences.csv").open(encoding="utf-8-sig")))
report("u2 equivalences>=10", len(eq) >= 10, len(eq))

# ---------------- u3 ----------------
p3 = ROOT / "u3_metals"
stats = json.loads((p3 / "data/summary_stats.json").read_text(encoding="utf-8"))
summary = list(csv.DictReader((p3 / "metals_summary.csv").open(encoding="utf-8-sig")))
dirs = [d for d in (p3 / "elements").iterdir() if d.is_dir()]
report("u3 exported+missing=87", stats["n_exported"] + stats["n_missing"] == 87, stats)
report("u3 rows==dirs==exported", len(summary) == len(dirs) == stats["n_exported"], f"{len(summary)}/{len(dirs)}/{stats['n_exported']}")
missing = [f"{r['element']}/{f}" for r in summary for f in ("bulk.cif", "bulk_POSCAR", "slab_POSCAR")
           if not (p3 / "elements" / r["element"] / f).is_file()]
report("u3 all bulk/slab files exist", not missing, missing[:5])
report("u3 all vacuum>=15", min(float(r["vacuum_measured"]) for r in summary) >= 15 - 1e-6, min(float(r["vacuum_measured"]) for r in summary))
planes = {r["element"]: r["densest_plane"] for r in summary if r["element"] in ("Fe", "Cu", "Mg", "Al", "W")}
report("u3 Fe/Cu/Mg/Al/W planes", planes == {"Fe": "(110)", "Cu": "(111)", "Mg": "(0001)", "Al": "(111)", "W": "(110)"}, planes)
with zipfile.ZipFile(p3 / "metals_kit.zip") as zf:
    report("u3 zip testzip", zf.testzip() is None and len(zf.namelist()) > 100, len(zf.namelist()))

# ---------------- u4 ----------------
p4 = ROOT / "u4_fec"
hull = list(csv.DictReader((p4 / "data/hull_points.csv").open(encoding="utf-8-sig")))
comp = list(csv.DictReader((p4 / "data/fe_c_compounds.csv").open(encoding="utf-8-sig")))
energies = list(csv.DictReader((p4 / "data/aflow_fe_c_energies.csv").open(encoding="utf-8-sig")))
report("u4 energies 289", len(energies) == 289, len(energies))
report("u4 compounds 7", len(comp) == 7, [r.get("name") for r in comp])
fe3c = []
for r in hull:
    try:
        c = Composition(r["compound"])
    except Exception:
        continue
    if abs(c.get_atomic_fraction("C") - 0.25) < 1e-6:
        fe3c.append((r["compound"], float(r["energy_above_hull_eV_per_atom"])))
report("u4 hull at 25 at%C (Fe3C) ~ +0.0456", bool(fe3c) and any(abs(e - 0.0456359) < 1e-3 for _, e in fe3c), fe3c[:3])
on_hull = [r["compound"] for r in hull if str(r["on_hull"]).lower() in ("yes", "true", "1")]
report("u4 only Fe/C endpoints on hull", len(on_hull) == 2, on_hull)
with zipfile.ZipFile(p4 / "fe_c_kit.zip") as zf:
    report("u4 zip testzip + README/scripts", zf.testzip() is None and any("README" in n for n in zf.namelist()) and any("build_hull" in n for n in zf.namelist()), len(zf.namelist()))

print("\nISSUES:", issues if issues else "none")
