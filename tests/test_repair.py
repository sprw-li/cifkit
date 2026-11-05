"""Tests for the repair layer: 补氢 / 无序占位 / 过近原子 / 价态检查.

Fixtures (``tests/data``, frozen):
* ``zif8_raw_hfree.cif`` - ZIF-8 conventional cell, Zn12 C96 N48, **no H**;
  the main "碳上补氢" case: 24 x mIm x 5 H = 120 H, final 276 atoms.
* ``zif8_cr_sod.cif`` - primitive cell with complete H (60 H): must be a no-op.
* ``zif8_disordered_h.cif`` - 48 full H + 144 H at occupancy 0.5: after
  disorder resolution 120 H / 276 atoms.

The extra small-molecule cases (benzene, duplicate atoms, synthetic CIF with
``_atom_site_disorder_group``) are built in the tests so the repair layer is
also checked outside the MOF fixtures.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from cifkit.repair import (
    add_hydrogens,
    check_structure,
    find_close_contacts,
    parse_atom_site_loop,
    perceive_bonds,
    repair_all,
    remove_close_contacts_atoms,
    resolve_disorder_sites,
)
from cifkit.repair.bonds import is_metal

DATA = Path(__file__).parent / "data"
ZIF8_HFREE = DATA / "zif8_raw_hfree.cif"
ZIF8_CR = DATA / "zif8_cr_sod.cif"
ZIF8_DISORDERED = DATA / "zif8_disordered_h.cif"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _load(path: Path) -> Structure:
    return Structure.from_file(path)


def _action(report, name: str) -> dict:
    return next(action for action in report.actions if action["action"] == name)


def _element_counts(structure: Structure) -> dict[str, int]:
    return {element.symbol: int(structure.composition[element]) for element in structure.composition.elements}


def _h_analysis(structure: Structure, search: float = 2.8) -> dict:
    """Geometry of every H-X bond in a periodic structure.

    The neighbour list includes the periodic image offsets, so the analysis is
    valid for primitive (non-orthogonal) cells as well.
    """
    symbols = [site.species_string for site in structure]
    cart = np.asarray(structure.cart_coords, dtype=float)
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    center, point, offsets, distances = structure.get_neighbor_list(search)
    pairs = [
        (int(a), int(b), np.asarray(offset, dtype=float), float(distance))
        for a, b, offset, distance in zip(center, point, offsets, distances)
    ]

    # parent (nearest heavy atom) of every H, in the H atom's reference frame
    parent: dict[int, tuple[float, int, np.ndarray]] = {}
    for a, b, offset, distance in pairs:
        if symbols[a] == "H" and symbols[b] != "H" and distance < 1.3:
            if a not in parent or distance < parent[a][0]:
                parent[a] = (distance, b, offset)

    min_hh = np.inf
    min_h_metal = np.inf
    min_h_nonbonded_heavy = np.inf
    for a, b, _offset, distance in pairs:
        if a == b:
            continue
        if symbols[a] == "H" and symbols[b] == "H" and a < b:
            min_hh = min(min_hh, distance)
        if symbols[a] == "H" and symbols[b] != "H":
            if is_metal(symbols[b]):
                min_h_metal = min(min_h_metal, distance)
            elif a in parent and b == parent[a][1] and distance < 1.3:
                continue
            else:
                min_h_nonbonded_heavy = min(min_h_nonbonded_heavy, distance)

    ring_angles: list[float] = []
    ring_out_of_plane: list[float] = []
    methyl_angles: list[float] = []
    methyl_hch_pairs: dict[tuple[int, int], float] = {}

    def angle(v1: np.ndarray, v2: np.ndarray) -> float:
        cosine = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
        return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))

    for h, (distance, p, h_offset) in parent.items():
        p_abs = cart[p] + h_offset @ lattice
        neighbours = [
            (b, cart[b] + offset @ lattice, d)
            for a, b, offset, d in pairs
            if a == p and b != h and d < 1.9
        ]
        heavy = [(b, position, d) for b, position, d in neighbours if symbols[b] != "H"]
        siblings = [(b, position, d) for b, position, d in neighbours if symbols[b] == "H" and d < 1.3]
        h_vector = cart[h] - p_abs
        if len(heavy) == 2:
            for _b, position, _d in heavy:
                ring_angles.append(angle(h_vector, position - cart[p]))
            normal = np.cross(heavy[0][1] - cart[p], heavy[1][1] - cart[p])
            ring_out_of_plane.append(abs(float(np.dot(h_vector, normal)) / (np.linalg.norm(normal) + 1e-12)))
        elif len(heavy) == 1:
            methyl_angles.append(angle(h_vector, heavy[0][1] - cart[p]))
            for b, position, _d in siblings:
                methyl_hch_pairs[tuple(sorted((h, b)))] = angle(h_vector, position - cart[p])

    return {
        "parent": parent,
        "min_hh": min_hh,
        "min_h_metal": min_h_metal,
        "min_h_nonbonded_heavy": min_h_nonbonded_heavy,
        "ring_angles": ring_angles,
        "ring_out_of_plane": ring_out_of_plane,
        "methyl_angles": methyl_angles,
        "methyl_hch": list(methyl_hch_pairs.values()),
        "symbols": symbols,
    }


def _benzene(lattice: Lattice, *, with_h: bool = True) -> Structure:
    species: list[str] = []
    coords: list[np.ndarray] = []
    for k in range(6):
        phi = math.radians(60.0 * k)
        carbon = np.array([1.39 * math.cos(phi), 1.39 * math.sin(phi), 0.0])
        hydrogen = carbon * (2.47 / 1.39)
        species.append("C")
        coords.append(carbon)
        if with_h:
            species.append("H")
            coords.append(hydrogen)
    return Structure(
        lattice,
        species,
        coords,
        coords_are_cartesian=True,
        validate_proximity=False,
    )


@pytest.fixture(scope="module")
def repaired_zif8():
    source = _load(ZIF8_HFREE)
    repaired, report = repair_all(source, add_hydrogen=True)
    return source, repaired, report


@pytest.fixture(scope="module")
def resolved_disordered():
    source = _load(ZIF8_DISORDERED)
    resolved, report = repair_all(source, add_hydrogen=False)
    return source, resolved, report


# ---------------------------------------------------------------------------
# main case: ZIF-8 without H -> 120 chemically placed H
# ---------------------------------------------------------------------------
def test_zif8_hfree_repair_adds_120_hydrogens(repaired_zif8):
    source, repaired, report = repaired_zif8

    # input untouched / final composition
    assert len(source) == 156
    assert len(repaired) == 276
    assert _element_counts(repaired) == {"Zn": 12, "C": 96, "H": 120, "N": 48}
    assert report.added_h == 120
    assert report.removed_atoms == 0
    assert report.resolved_disorder == 0
    assert report.warnings == []

    # structured actions, in pipeline order
    assert [action["action"] for action in report.actions] == ["contacts", "hydrogen", "valence"]
    hydrogen = _action(report, "hydrogen")
    assert hydrogen["added_h"] == 120
    assert hydrogen["per_ligand_h"] == {5: 24}  # every mIm linker gets exactly 5 H
    assert hydrogen["h_types"] == {"sp2 C-H": 48, "sp3 C-H3": 72}
    assert hydrogen["c_valence_ok"] is True
    assert hydrogen["route"] in {"rdkit-capped", "geometric-vsepr", "mixed (rdkit-capped + geometric-vsepr)"}
    if hydrogen["rdkit"]["available"]:
        assert hydrogen["rdkit"]["fragments_ok"] == 24
        assert hydrogen["rdkit"]["fragments_failed"] == 0

    # every carbon ends up four-coordinate, every Zn keeps CN=4, no warnings
    valence = _action(report, "valence")
    assert valence["ok"] is True
    metrics = check_structure(repaired)["metrics"]
    assert metrics["c_four_coordinate"] == 96
    assert metrics["metal_coordination"] == {"Zn": {4: 12}}
    assert metrics["h_count"] == 120

    # geometric chemistry of the placed hydrogens
    analysis = _h_analysis(repaired)
    assert len(analysis["parent"]) == 120
    lengths = [distance for distance, _parent, _offset in analysis["parent"].values()]
    assert 1.05 <= min(lengths) <= max(lengths) <= 1.15
    assert analysis["min_hh"] >= 1.4
    assert analysis["min_h_metal"] >= 2.0
    assert analysis["min_h_nonbonded_heavy"] >= 1.5

    # imidazolate N are Zn-coordinated: no N-H was added
    assert [h for h, (_d, p, _o) in analysis["parent"].items() if analysis["symbols"][p] == "N"] == []

    # ring C-H: in the ring plane, ~125.7 deg to both ring neighbours
    assert len(analysis["ring_angles"]) == 2 * 48
    assert all(115.0 <= angle <= 135.0 for angle in analysis["ring_angles"])
    assert max(analysis["ring_out_of_plane"]) < 0.10

    # methyl: tetrahedral H-C-C and H-C-H angles
    assert len(analysis["methyl_angles"]) == 72
    assert len(analysis["methyl_hch"]) == 3 * 24
    assert all(104.0 <= angle <= 115.0 for angle in analysis["methyl_angles"])
    assert all(104.0 <= angle <= 115.0 for angle in analysis["methyl_hch"])


def test_repaired_zif8_has_no_close_contacts(repaired_zif8):
    _source, repaired, _report = repaired_zif8
    assert find_close_contacts(repaired) == []


# ---------------------------------------------------------------------------
# no-op: a structure that already has all hydrogens
# ---------------------------------------------------------------------------
def test_full_hydrogen_structure_is_not_touched():
    source = _load(ZIF8_CR)
    assert len(source) == 138
    repaired, report = repair_all(source, add_hydrogen=True)

    assert len(source) == 138  # caller's structure not mutated
    assert len(repaired) == 138
    assert report.added_h == 0
    assert report.warnings == []
    assert _element_counts(repaired) == {"Zn": 6, "H": 60, "C": 48, "N": 24}
    hydrogen = _action(report, "hydrogen")
    assert hydrogen["added_h"] == 0
    assert hydrogen["route"] == "none"

    # direct API + idempotency
    again, stats = add_hydrogens(source)
    assert stats["added_h"] == 0 and len(again) == 138
    twice, report_twice = repair_all(repaired, add_hydrogen=True)
    assert len(twice) == 138 and report_twice.added_h == 0


# ---------------------------------------------------------------------------
# disorder / partial occupancy
# ---------------------------------------------------------------------------
def test_disordered_fixture_resolves_to_120_hydrogens(resolved_disordered):
    source, resolved, report = resolved_disordered

    assert len(source) == 348  # 48 full H + 144 half-occupied H + 156 heavy
    assert len(resolved) == 276
    assert report.resolved_disorder == 24  # one statistical methyl group per linker
    assert report.removed_atoms == 0
    assert report.warnings == []
    assert _element_counts(resolved) == {"Zn": 12, "C": 96, "H": 120, "N": 48}

    # no partial occupancy left, all C four-coordinate
    assert all(len(site.species) == 1 for site in resolved)
    valence = check_structure(resolved)
    assert valence["ok"] is True
    assert valence["metrics"]["c_four_coordinate"] == 96

    # 3 H per methyl carbon, 1 H per ring carbon, no overlaps
    analysis = _h_analysis(resolved)
    assert len(analysis["parent"]) == 120
    assert analysis["min_hh"] > 1.2
    assert len(analysis["methyl_angles"]) == 72
    assert len(analysis["ring_angles"]) == 2 * 48
    assert all(104.0 <= angle <= 115.0 for angle in analysis["methyl_hch"])
    assert all(115.0 <= angle <= 135.0 for angle in analysis["ring_angles"])

    # adding H after disorder resolution is a no-op
    still, report_twice = repair_all(source, add_hydrogen=True)
    assert len(still) == 276 and report_twice.added_h == 0


def test_disorder_cif_text_parsing_and_resolution():
    text = ZIF8_DISORDERED.read_text(encoding="utf-8")
    records = parse_atom_site_loop(text)
    assert len(records) == 348
    assert sum(1 for record in records if abs(record.occupancy - 0.5) < 1e-6) == 144
    assert sum(1 for record in records if record.occupancy >= 0.999) == 204

    structure = _load(ZIF8_DISORDERED)
    resolved, stats = resolve_disorder_sites(structure, cif_text=text)
    assert len(structure) == 348  # caller's structure not mutated
    assert len(resolved) == 276
    assert stats["cif_records"] == 348
    assert stats["partial_before"] == 144
    assert stats["removed_h"] == 72
    assert stats["groups_resolved"] == 24
    assert stats["warnings"] == []


def test_disorder_group_columns_are_honoured():
    lattice = Lattice.cubic(20.0)
    coords = np.array([[0.0, 0.0, 0.0], [1.43, 0.0, 0.0], [2.39, 0.0, 0.0], [1.08, 0.85, 0.0]])
    structure = Structure(
        lattice,
        [{"C": 1.0}, {"O": 1.0}, {"H": 0.6}, {"H": 0.4}],
        coords,
        coords_are_cartesian=True,
        validate_proximity=False,
    )
    cif_text = """
data_synthetic
_cell_length_a 20.0
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 _atom_site_disorder_group
 _atom_site_disorder_assembly
C C1 0.0000 0.0000 0.0000 1.0 . .
O O1 0.0715 0.0000 0.0000 1.0 . .
H H1 0.1195 0.0000 0.0000 0.6 1 A
H H2 0.0540 0.0425 0.0000 0.4 2 A
"""
    records = parse_atom_site_loop(cif_text)
    assert [record.disorder_group for record in records] == [None, None, "1", "2"]
    assert records[2].disorder_assembly == "A"

    resolved, stats = resolve_disorder_sites(structure, cif_text=cif_text)
    assert len(resolved) == 3
    kept = [site for site in resolved if site.species_string == "H"]
    assert len(kept) == 1
    # higher-occupancy group ("1", 0.6) is kept
    assert abs(float(kept[0].frac_coords[0]) - 0.1195) < 1e-3
    assert stats["groups_resolved"] == 1
    assert stats["removed_h"] == 1


# ---------------------------------------------------------------------------
# close contacts / duplicate atoms
# ---------------------------------------------------------------------------
def test_close_contacts_detect_and_remove_duplicates():
    lattice = Lattice.cubic(20.0)
    structure = Structure(
        lattice,
        ["C", "C", "N"],
        [[0.0, 0.0, 0.0], [0.05, 0.0, 0.0], [5.0, 5.0, 5.0]],
        coords_are_cartesian=True,
        validate_proximity=False,
    )
    contacts = find_close_contacts(structure)
    assert [contact.kind for contact in contacts] == ["duplicate"]
    new_structure, removed, details = remove_close_contacts_atoms(structure)
    assert removed == 1
    assert len(new_structure) == 2
    assert len(structure) == 3  # caller's structure not mutated
    assert details["contacts"][0]["removed"] is not None
    assert details["warnings"] == []

    # overlapping hydrogens are also removed
    hydrogen_pair = Structure(
        lattice,
        ["C", "H", "H"],
        [[0.0, 0.0, 0.0], [1.09, 0.0, 0.0], [1.09, 0.40, 0.0]],
        coords_are_cartesian=True,
        validate_proximity=False,
    )
    contacts = find_close_contacts(hydrogen_pair)
    assert any(contact.kind == "h-h" for contact in contacts)
    stripped, removed, _details = remove_close_contacts_atoms(hydrogen_pair)
    assert removed == 1 and len(stripped) == 2


# ---------------------------------------------------------------------------
# small organic molecule: full benzene is a negative case, broken benzene is fixed
# ---------------------------------------------------------------------------
def test_benzene_full_h_is_noop_and_missing_h_is_repaired():
    lattice = Lattice.cubic(20.0)
    benzene = _benzene(lattice)
    graph = perceive_bonds(benzene)
    assert any(ring.aromatic and ring.size == 6 for ring in graph.rings)

    repaired, report = repair_all(benzene, add_hydrogen=True)
    assert report.added_h == 0
    assert len(repaired) == 12
    assert report.warnings == []
    assert check_structure(repaired)["ok"] is True

    broken = _benzene(lattice)
    # drop one H: the carbon loses its fourth bond -> valence warning
    broken.remove_sites([11])
    analysis = check_structure(broken)
    assert analysis["ok"] is False
    assert any("非四价碳" in warning for warning in analysis["warnings"])

    repaired, report = repair_all(broken, add_hydrogen=True)
    assert report.added_h == 1
    assert len(repaired) == 12
    assert report.warnings == []
    assert check_structure(repaired)["ok"] is True


# ---------------------------------------------------------------------------
# solvent-containing large structure: must stay untouched (x-ray short N-H)
# ---------------------------------------------------------------------------
def test_large_solvent_fixture_is_not_over_modified():
    source = _load(DATA / "sod_zn_mof.cif")
    assert len(source) == 750
    repaired, report = repair_all(source, add_hydrogen=True)
    assert len(source) == 750  # caller's structure not mutated
    assert len(repaired) == 750
    # X-ray N-H bonds are only ~0.86 A: they must not be treated as clashes,
    # and no extra H may be added on the already complete solvent structure.
    assert report.added_h == 0
    assert report.removed_atoms == 0
    assert report.warnings == []
    metrics = check_structure(repaired)["metrics"]
    assert metrics["c_four_coordinate"] == 312


# ---------------------------------------------------------------------------
# reporting / CLI integration
# ---------------------------------------------------------------------------
def test_report_is_structured_and_json_serialisable(repaired_zif8):
    _source, _repaired, report = repaired_zif8
    assert {"action", "detail"} <= set(report.actions[0])
    payload = report.to_dict()
    assert payload["added_h"] == 120
    assert payload["removed_atoms"] == 0
    assert payload["resolved_disorder"] == 0
    assert payload["warnings"] == []
    json.dumps(payload, ensure_ascii=False, default=str)  # must be serialisable


def test_cli_repair_add_h(tmp_path, capsys):
    from cifkit.cli import main

    output = tmp_path / "repaired.cif"
    return_code = main(["repair", str(ZIF8_HFREE), "-o", str(output), "--add-h", "--json"])
    assert return_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["added_h"] == 120
    assert payload["natoms"] == 276
    assert payload["formula"].replace(" ", "") == "Zn12H120C96N48"

    roundtrip = Structure.from_file(output)
    assert len(roundtrip) == 276
    assert _element_counts(roundtrip) == {"Zn": 12, "C": 96, "H": 120, "N": 48}
    assert check_structure(roundtrip)["ok"] is True


def test_repaired_structure_supports_supercell(repaired_zif8):
    geom = pytest.importorskip("cifkit.geom")
    _source, repaired, _report = repaired_zif8
    supercell = geom.make_supercell(repaired, (2, 2, 1))
    assert len(supercell) == 276 * 4
    assert int(supercell.composition["H"]) == 120 * 4
