"""Element ground-state structure resolution (87 metals) -- two-tier, verified.

Why not "AFLOW LIB1 lowest energy_atom"?
----------------------------------------
The Lead measured that ``element_ground_state()`` picks wrong structures for
several elements (Sn -> cF8 diamond, Hg -> cI2, Ga -> tI2, In -> hP3,
Mn -> hP2, Sm -> hP2) because LIB1 mixes many PAW potentials and the raw
``energy_atom`` minimum is not the experimental ground state.  So we use:

Tier 1 ``ase``
    ``ase.data.reference_states`` is the Kittel/Ashcroft-Mermin textbook table
    (symmetry + lattice constants + basis).  ``ase.build.bulk`` builds
    bcc / fcc / hcp / bct / rhombohedral primitive cells, and we then take the
    pymatgen conventional cell and re-check the space group with spglib.

Tier 2 ``aflow``
    For prototypes ASE cannot build (alpha-Mn, alpha-Ga, alpha-U, Sm-type,
    Bi, Pa, Np, Pu, transuranics) the AFLOW LIB1 entries are filtered by the
    *expected space group* (not by energy), fetched, converted to the
    conventional cell and re-checked with spglib (number + atom count).

Every resolved structure carries ``structure_confidence``:
``high`` (ASE textbook table + SG/atom-count check passed), ``medium``
(AFLOW filtered by expected SG + check passed, experimental structure known),
``uncertain`` (AFLOW entry with no independent expectation).  Anything that
cannot be resolved or fails the check is reported as missing -- never faked.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.core import Element, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from cifkit.geom import standardize

# ---------------------------------------------------------------------------
# Expected ground state per element.
#   symmetry: ase.build.bulk keyword (tier-1) or None when ASE cannot build it
#   sg:       expected spglib space-group number
#   natoms:   expected number of atoms in the *conventional* cell
#   proto:    human-readable prototype / Strukturbericht label
#   conf:     structure_confidence
# The 55 bcc/fcc/hcp entries come straight from reference_states; the rest are
# hand-entered from the literature (Kittel, Pearson's Crystal Data).
EXPECTED: dict[str, dict[str, Any]] = {
    # ---- bcc (A2, Im-3m, 229); ASE lattice constant ---------------------
    **{
        el: dict(symmetry="bcc", sg=229, natoms=2, proto="bcc (A2)", conf="high")
        for el in "Li Na K V Cr Fe Rb Nb Mo Cs Ba Eu Ta W".split()
    },
    # ---- fcc (A1, Fm-3m, 225) -------------------------------------------
    **{
        el: dict(symmetry="fcc", sg=225, natoms=4, proto="fcc (A1)", conf="high")
        for el in "Al Ca Ni Cu Sr Rh Pd Ag Ce Yb Ir Pt Au Pb Ac Th".split()
    },
    # ---- hcp (A3, P6_3/mmc, 194) ----------------------------------------
    **{
        el: dict(symmetry="hcp", sg=194, natoms=2, proto="hcp (A3)", conf="high")
        for el in (
            "Be Mg Sc Ti Co Zn Y Zr Tc Ru Cd La Pr Nd Gd Tb Dy Ho Er Tm Lu "
            "Hf Re Os Tl"
        ).split()
    },
    # ---- body-centred tetragonal ----------------------------------------
    "In": dict(symmetry="bct", sg=139, natoms=2, proto="bct (A6, In)", conf="high"),
    "Sn": dict(
        symmetry="bct",
        sg=141,
        natoms=4,
        proto="bct (A5, beta-Sn)",
        conf="high",
        basis=[[0.0, 0.0, 0.0], [0.25, 0.75, 0.5]],
    ),
    # ---- rhombohedral ----------------------------------------------------
    # alpha-Hg is the 1-atom rhombohedral primitive cell (A10, R-3m); the
    # conventional hexagonal cell then holds 3 atoms (Pearson hR1 primitive /
    # hR3 hexagonal conventional).
    "Hg": dict(symmetry="rhombohedral", sg=166, natoms=3, proto="rhombohedral (A10, alpha-Hg; hR1 primitive / hR3 hex cell)", conf="high"),
    # alpha-Sm is 9-layer rhombohedral (Sm-type, hR9); ASE's table gives only a
    # 1-atom rhombohedral cell -> AFLOW tier.
    "Sm": dict(symmetry=None, sg=166, natoms=9, pearson_hint="hR9", proto="rhombohedral (hR9, Sm-type)", conf="medium"),
    # alpha-Bi is the 2-atom rhombohedral primitive cell (A7); ASE's table has
    # no basis -> AFLOW tier.
    "Bi": dict(symmetry=None, sg=166, natoms=6, pearson_hint="hR2", proto="rhombohedral (A7, alpha-Bi; hR2 primitive / hR6 hex cell)", conf="medium"),
    # ---- AFLOW-only prototypes ------------------------------------------
    # alpha-Mn: complex cI58, I-43m (#217)
    "Mn": dict(symmetry=None, sg=217, natoms=58, pearson_hint="cI58", proto="cI58 (alpha-Mn)", conf="medium"),
    # alpha-Ga: oS8, Cmce/Cmca (#64)
    "Ga": dict(symmetry=None, sg=64, natoms=8, pearson_hint="oS8", proto="oS8 (alpha-Ga)", conf="medium"),
    # alpha-U: oC4, Cmcm (#63)
    "U": dict(symmetry=None, sg=63, natoms=4, pearson_hint="oC4", proto="oC4 (alpha-U)", conf="medium",
              catalogs=("LIB1", "ICSD")),
    # alpha-Np: oP8, Pnma (#62) -- experimental structure, relaxed AFLOW check
    "Np": dict(symmetry=None, sg=62, natoms=8, pearson_hint="oP8", proto="oP8 (alpha-Np)", conf="uncertain",
               catalogs=("LIB1", "ICSD"), cod=True),
    # alpha-Pa: tI2, I4/mmm (#139)
    "Pa": dict(symmetry=None, sg=139, natoms=2, pearson_hint="tI2", proto="tI2 (alpha-Pa)", conf="medium",
               catalogs=("LIB1", "ICSD")),
    # alpha-Pu: mP16, P2_1/m (#11) -- 16 atoms, the hardest one
    "Pu": dict(symmetry=None, sg=11, natoms=16, pearson_hint="mP16", proto="mP16 (alpha-Pu)", conf="uncertain",
               catalogs=("LIB1", "ICSD"), cod=True),
    # ---- no ASE reference; predicted/experimental structures -------------
    "Pm": dict(symmetry=None, sg=194, natoms=2, pearson_hint="hP2", proto="hcp (A3, predicted)", conf="medium"),
    "Fr": dict(symmetry=None, sg=229, natoms=2, pearson_hint="cI2", proto="bcc (A2, predicted)", conf="uncertain"),
    "Ra": dict(symmetry=None, sg=229, natoms=2, pearson_hint="cI2", proto="bcc (A2, experimental, COD)", conf="uncertain",
               cod=True),
    # americium/curium/berkelium/californium: double-hcp (hP4) or hcp
    "Am": dict(symmetry=None, sg=194, natoms=4, pearson_hint="hP4", proto="dhcp (hP4, experimental, COD)", conf="uncertain",
               cod=True),
    "Cm": dict(symmetry=None, sg=194, natoms=4, pearson_hint="hP4", proto="dhcp (hP4, predicted)", conf="uncertain"),
    "Bk": dict(symmetry=None, sg=194, natoms=4, pearson_hint="hP4", proto="dhcp (hP4, predicted)", conf="uncertain"),
    "Cf": dict(symmetry=None, sg=194, natoms=4, pearson_hint="hP4", proto="dhcp (hP4, predicted)", conf="uncertain"),
    "Es": dict(symmetry=None, sg=225, natoms=4, pearson_hint="cF4", proto="fcc (A1, predicted)", conf="uncertain"),
    # no reliable crystal structure known (only a few atoms ever produced)
    **{
        el: dict(symmetry=None, sg=None, natoms=None, proto="unknown", conf="uncertain")
        for el in "Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn".split()
    },
}


# ---------------------------------------------------------------------------
def _ase_bulk(el: str, spec: dict[str, Any]) -> Structure:
    """Build a tier-1 structure with ase and return the pymatgen conventional cell."""
    from ase.build import bulk
    from ase.data import atomic_numbers, reference_states
    from pymatgen.io.ase import AseAtomsAdaptor

    ref = reference_states[atomic_numbers[el]]
    if ref is None:
        raise RuntimeError(f"ASE reference_states has no entry for {el}")
    kw: dict[str, Any] = {"name": el, "crystalstructure": spec["symmetry"]}
    kw["a"] = float(ref["a"])
    if spec["symmetry"] == "hcp":
        kw["covera"] = float(ref["c/a"])
    elif spec["symmetry"] == "bct":
        c = float(ref["a"]) * float(ref["c/a"])
        kw["c"] = c
        if spec.get("basis") is not None:
            kw["basis"] = spec["basis"]
        elif ref.get("basis") is not None:
            kw["basis"] = ref["basis"]
    elif spec["symmetry"] == "rhombohedral":
        kw["alpha"] = float(ref["alpha"])
    atoms = bulk(**kw)
    struct = AseAtomsAdaptor.get_structure(atoms)
    return standardize(struct)


def _aflow_rows(el: str, catalog: str = "LIB1") -> list[dict[str, Any]]:
    """All AFLOW entries of a pure element in one catalog (full query, no filtering).

    AFLUX silently ignores ``spacegroup_relax(...)`` filters (measured by the
    Lead), so the space-group selection has to happen client-side.
    """
    from usecases._common import aflow_db as db

    rows = db.aflux(
        f"species({el}),nspecies(1),catalog({catalog}),"
        "spacegroup_relax,Pearson_symbol_relax,energy_atom,prototype,natoms,compound",
        paging=(0, 300),
    )
    out = []
    for r in rows:
        try:
            energy = float(r["energy_atom"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            {
                "aurl": r.get("aurl"),
                "spacegroup_relax": r.get("spacegroup_relax"),
                "pearson": r.get("Pearson_symbol_relax"),
                "prototype": r.get("prototype"),
                "energy_atom": energy,
                "natoms": r.get("natoms"),
                "compound": r.get("compound"),
                "catalog": catalog,
            }
        )
    return out


def _aflow_bulk(
    el: str,
    spec: dict[str, Any],
    catalogs: tuple[str, ...] = ("LIB1",),
) -> tuple[Structure, dict[str, Any]]:
    """Pick the AFLOW entry matching the expected space group (never raw energy)."""
    from usecases._common import aflow_db as db

    sg = int(spec["sg"])
    tried: list[str] = []
    pool: list[dict[str, Any]] = []
    for catalog in catalogs:
        try:
            rows = _aflow_rows(el, catalog)
        except Exception as exc:  # noqa: BLE001 - catalogue unavailable -> next one
            tried.append(f"{catalog}:error({type(exc).__name__})")
            continue
        tried.append(f"{catalog}:{len(rows)}")
        same = [
            r
            for r in rows
            if r.get("spacegroup_relax") is not None
            and int(float(r["spacegroup_relax"])) == sg
        ]
        if same:
            pool = same
            break
    if not pool:
        raise RuntimeError(
            f"no AFLOW entry with spacegroup_relax={sg} for {el} (searched {', '.join(tried)})"
        )

    # prefer the Pearson symbol of the experimental structure (e.g. Sm -> hR9)
    hint = spec.get("pearson_hint")
    if hint:
        match = [r for r in pool if str(r.get("pearson") or "").startswith(hint)]
        if match:
            pool = match

    def _rank(r: dict[str, Any]) -> tuple:
        # relaxed DFT energies only order structures that already carry the
        # expected space group (and Pearson symbol when it is known)
        return (float(r["energy_atom"]), str(r.get("pearson") or ""))

    chosen = sorted(pool, key=_rank)[0]
    struct, prov, _rec = db.fetch_structure(chosen["aurl"])
    struct = fix_aflow_species(struct, el, prov)  # independent element check
    meta = {
        "source_aurl": "https://" + str(chosen["aurl"]).replace(":", "/", 1),
        "source_energy_atom": round(float(chosen["energy_atom"]), 6),
        "aflow_catalog": chosen["catalog"],
        "aflow_pearson": chosen.get("pearson"),
        "aflow_natoms_primitive": chosen.get("natoms"),
        "aflow_n_matching_sg": len(pool),
        "cif_sanitized_for_parsing": bool(prov.get("cif_sanitized_for_parsing")),
    }
    return standardize(struct), meta


#: AFLOW CIFs write the PAW *potential* name (``potpaw_PBE.54/Fe_sv``) into
#: ``_atom_site_type_symbol``; parsers then read e.g. "Po" from "potpaw".  The
#: query is ``nspecies(1)``, so the element is known -- rebuild the structure
#: with it after checking the CIF really is a single-element file.
def fix_aflow_species(struct: Structure, el: str, prov: dict[str, Any] | None = None) -> Structure:
    import re
    from pathlib import Path

    elems = {str(e) for e in struct.composition.elements}
    if len(elems) != 1:
        raise RuntimeError(f"AFLOW CIF for {el} is not a pure element ({sorted(elems)})")
    # cross-check the CIF text: potpaw_*/*<El>* must contain only the wanted element
    if prov and prov.get("cif_path"):
        text = Path(prov["cif_path"]).read_text(encoding="utf-8", errors="replace")
        found = set()
        for token in re.findall(r"potpaw[^\s/]*/([A-Za-z]+[0-9]*)", text):
            m = re.match(r"([A-Z][a-z]?)", token)
            if m:
                found.add(m.group(1))
        if found and found != {el}:
            raise RuntimeError(f"AFLOW CIF for {el} mentions elements {sorted(found)}")
    return Structure(struct.lattice, [el] * len(struct), struct.frac_coords)


# ---------------------------------------------------------------------------
def spglib_check(struct: Structure) -> dict[str, Any]:
    """spglib space group / Pearson / atom count of a (conventional) structure."""
    import spglib

    lat = np.asarray(struct.lattice.matrix, dtype=float)
    pos = np.asarray(struct.frac_coords, dtype=float)
    numbers = np.array([Element(s.symbol).Z for s in struct.species], dtype=int)
    ds = spglib.get_symmetry_dataset((lat, pos, numbers), symprec=1e-3)
    if ds is None:
        raise RuntimeError("spglib.get_symmetry_dataset returned None")
    number = int(ds.number)
    symbol = str(ds.international)
    # conventional atom count from spglib itself
    std = spglib.standardize_cell((lat, pos, numbers), to_primitive=False, no_idealize=False, symprec=1e-3)
    n_conv = int(len(std[2])) if std is not None else len(struct)
    return {
        "sg_number": number,
        "sg_symbol": symbol,
        "natoms_conv": n_conv,
        "pearson": pearson_symbol(number, symbol, n_conv),
    }


def pearson_symbol(sg_number: int, sg_symbol: str, natoms_conv: int) -> str:
    """Pearson symbol (crystal-system letter + Bravais centring + atom count).

    Pearson uses ``S`` for a single side-centred lattice (C/A/B in the
    Hermann-Mauguin symbol), e.g. alpha-Ga (Cmce) is ``oS8``.
    """
    if sg_number <= 2:
        system = "a"
    elif sg_number <= 15:
        system = "m"
    elif sg_number <= 74:
        system = "o"
    elif sg_number <= 142:
        system = "t"
    elif sg_number <= 194:
        system = "h"
    else:
        system = "c"
    first = sg_symbol[:1]
    if first in ("A", "B", "C"):
        centring = "S"
    else:
        centring = first if first in "PIFR" else "P"
    return f"{system}{centring}{natoms_conv}"


def primitive_natoms(struct: Structure) -> int:
    """Number of atoms in the primitive cell (spglib standardisation)."""
    import spglib

    lat = np.asarray(struct.lattice.matrix, dtype=float)
    pos = np.asarray(struct.frac_coords, dtype=float)
    numbers = np.array([Element(s.symbol).Z for s in struct.species], dtype=int)
    std = spglib.standardize_cell(
        (lat, pos, numbers), to_primitive=True, no_idealize=False, symprec=1e-3
    )
    return int(len(std[2])) if std is not None else len(struct)


_PLANES = {
    225: (1, 1, 1),  # fcc
    229: (1, 1, 0),  # bcc
    194: (0, 0, 1),  # hcp / dhcp
    221: (1, 0, 0),  # sc
    227: (1, 1, 1),  # diamond
}


def densest_plane_known(sg_number: int, natoms_conv: int) -> tuple[int, int, int] | None:
    """Backwards-compatible helper; the real rule lives in surface_planes.py."""
    return _PLANES.get(int(sg_number))


# ---------------------------------------------------------------------------
COD_HOST = "https://www.crystallography.net/cod"
COD_CACHE = Path(__file__).resolve().parents[1] / "data" / "cod_cache"


def _cod_fetch(path: str, timeout: float = 40.0) -> str:
    """Download a COD URL, caching the text under data/cod_cache/."""
    import hashlib
    import urllib.request

    COD_CACHE.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
    suffix = ".cif" if path.lower().endswith(".cif") else ".json"
    cache = COD_CACHE / f"{digest}{suffix}"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    req = urllib.request.Request(path, headers={"User-Agent": "cifkit-usecases/0.1 (python-urllib)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed host
        text = resp.read().decode("utf-8", "replace")
    cache.write_text(text, encoding="utf-8")
    return text


def _cod_bulk(el: str, spec: dict[str, Any]) -> tuple[Structure, dict[str, Any]]:
    """Last-resort tier: an experimental COD entry, checked against the expected SG."""
    import io
    import json
    import urllib.parse

    from pymatgen.io.cif import CifParser

    url = f"{COD_HOST}/result?formula={urllib.parse.quote(el)}&format=json"
    entries = json.loads(_cod_fetch(url))
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"COD has no entries for {el}")
    sg = int(spec["sg"])
    exp_n = spec.get("natoms")
    pool: list[tuple[int, Structure, dict[str, Any]]] = []
    scanned = 0
    for entry in entries:
        cod_id = entry.get("file")
        if not cod_id:
            continue
        try:
            text = _cod_fetch(f"{COD_HOST}/{cod_id}.cif")
            scanned += 1
            structs = CifParser(io.StringIO(text), occupancy_tolerance=100.0).parse_structures(
                primitive=False
            )
        except Exception:  # noqa: BLE001 - skip unparsable / disordered COD entries
            continue
        for raw in structs:
            if {str(e) for e in raw.composition.elements} != {el}:
                continue  # mixed compounds etc.
            try:
                struct = standardize(raw)
                check = spglib_check(struct)
            except Exception:  # noqa: BLE001
                continue
            if check["sg_number"] != sg:
                continue
            dist = abs(check["natoms_conv"] - int(exp_n)) if exp_n else 0
            pool.append(
                (
                    dist,
                    struct,
                    {
                        "cod_id": cod_id,
                        "cod_title": entry.get("title"),
                        "cod_sg": entry.get("sg"),
                        "cod_year": entry.get("year"),
                    },
                )
            )
    if not pool:
        raise RuntimeError(
            f"COD has {len(entries)} entries for {el} ({scanned} CIF(s) parsed) but none "
            f"is a pure-element structure with spacegroup {sg}"
        )
    pool.sort(key=lambda t: t[0])
    _dist, struct, meta = pool[0]
    meta["source_aurl"] = f"{COD_HOST}/{meta['cod_id']}.html"
    meta["source_energy_atom"] = None
    return struct, meta


# ---------------------------------------------------------------------------
def resolve(el: str, candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Resolve the ground state of ``el``; returns a dict with structure + metadata.

    ``candidates`` is the cached AFLOW LIB1 row list (may be empty); the structure
    itself is always re-derived from ASE or fetched fresh from AFLOW.
    """
    spec = EXPECTED.get(el)
    if spec is None:
        raise KeyError(f"no expected ground state recorded for {el}")
    struct = None
    source = ""
    meta: dict[str, Any] = {}
    notes: list[str] = []

    if spec["symmetry"] is not None:
        try:
            struct = _ase_bulk(el, spec)
            source = "ASE reference_states (Kittel) + ase.build.bulk"
        except Exception as exc:  # noqa: BLE001 - fall back to AFLOW
            notes.append(f"ASE build failed: {type(exc).__name__}: {exc}")

    if struct is None:
        if spec.get("sg") is None:
            raise RuntimeError(
                f"{el}: no crystal structure available (ASE has no entry and no "
                f"experimental space group is established)"
            )
        catalogs = tuple(spec.get("catalogs", ("LIB1",)))
        tried: list[str] = []
        try:
            struct, meta = _aflow_bulk(el, spec, catalogs=catalogs)
            source = (
                "AFLOW " + "/".join(catalogs) + " filtered client-side to "
                f"spacegroup_relax={spec['sg']}"
            )
        except Exception as aflow_exc:  # noqa: BLE001 - try COD next
            tried.append(f"AFLOW: {aflow_exc}")
            if spec.get("cod"):
                struct, meta = _cod_bulk(el, spec)  # raises if COD cannot help
                source = (
                    "COD (Crystallography Open Database, experimental entry "
                    f"{meta.get('cod_id')}) filtered to spacegroup {spec['sg']}"
                )
            else:
                raise RuntimeError("; ".join(tried)) from aflow_exc

    check = spglib_check(struct)
    ok_sg = spec.get("sg") is None or check["sg_number"] == int(spec["sg"])
    ok_n = spec.get("natoms") is None or check["natoms_conv"] == int(spec["natoms"])
    if not (ok_sg and ok_n):
        raise RuntimeError(
            f"{el}: structure check failed (got sg={check['sg_number']} n_conv={check['natoms_conv']}, "
            f"expected sg={spec.get('sg')} n_conv={spec.get('natoms')})"
        )
    n_prim = primitive_natoms(struct)
    pearson_prim = pearson_symbol(check["sg_number"], check["sg_symbol"], n_prim)
    return {
        "element": el,
        "structure": struct,
        "structure_type": spec["proto"],
        "lattice_source": source,
        "structure_confidence": spec["conf"],
        "sg_check": check["sg_number"],
        "sg_symbol": check["sg_symbol"],
        "pearson": check["pearson"],
        "pearson_primitive": pearson_prim,
        "natoms_conventional": len(struct),
        "source_aurl": meta.get("source_aurl", ""),
        "source_energy_atom": meta.get("source_energy_atom"),
        "aflow_meta": meta,
        "notes": "; ".join(notes),
    }
