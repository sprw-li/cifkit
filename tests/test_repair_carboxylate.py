"""Carboxylate-MOF hydrogen completion tests (Round-2 WP2).

Fixtures (see ``tests/data/REPAIR_FIXTURES.md`` for full provenance):

* ``mof5_hfree.cif``  - SYNTHETIC H-free copy of the WP3-verified real MOF-5 record
  CoRE ``SI/CR/ASR/2007[Zn][pcu]3[ASR]3.cif`` (coreid ``2007[Zn][pcu]3[ASR]3``,
  refcode ``ja074366o_ASR_pacman``, DOI 10.1021/ja074366o, topology pcu, 106 atoms,
  Zn8 H24 C48 O26 = 2 x Zn4O(BDC)3): all 24 H removed, heavy atoms unchanged.
  Expected H: **24** = 6 BDC x 4 ring H; the 2 mu4-O are oxo (4 Zn each, 1.943 A)
  and get no H; carboxylate O / Zn4O cluster get no H.
* ``mof5_h.cif``       - REAL CoRE CR CIF of the same record (Zn8 H24 C48 O26,
  106 atoms) -> repair must be a no-op.
* ``mof5_cod_hfree.cif`` - REAL, independent H-free MOF-5 CIF from COD (4340010,
  Zn32 C192 O104, 328 atoms; the database CIF itself has no H).  Expected 96 H.
* ``mof5_cod_h.cif``   - REAL H-complete MOF-5 CIF from COD (1516287,
  Zn32 H96 C192 O104, 424 atoms) -> no-op reference / cross-check.
* ``uio66_hfree.cif``  - SYNTHETIC H-free copy of CoRE CR
  ``SI/CR/ASR/2015[Zr][fcu]3[ASR]1.cif`` (all 28 H removed, heavy atoms
  unchanged): Zr6 C48 O32, 86 atoms.  Expected H: 28 = 24 BDC ring C-H +
  4 mu3-OH cluster O-H (mu3-O oxo gets no H).
* ``uio66_h.cif``      - REAL CoRE CR CIF, Zr6 H28 C48 O32, 114 atoms ->
  no-op reference.
* ``hkust1_hfree.cif`` - SYNTHETIC H-free copy of CoRE NCR
  ``SI/NCR/mofchecker/c8tc01703d2_ASR_pacman.cif``: Cu12 C72 O48, 132 atoms.
  Expected H: 24 = 8 BTC x 3 ring H; carboxylate O and Cu paddlewheel no H.
* ``hkust1_h.cif``     - REAL CoRE NCR CIF, Cu12 H24 C72 O48, 156 atoms ->
  no-op reference.
* ``terephthalic_acid_hfree.cif`` - SYNTHETIC metal-free carboxylic acid
  (RDKit geometry, two acidic H removed): C8 H4 O4 -> repair adds 2 O-H.

Acceptance criteria verified here: H count equals the chemical formula of the
H-complete reference, all C four-coordinate, carboxylate O never protonated
in the MOFs, mu3-O/mu4-O oxo not protonated, ring C-H placed in the ring
plane, no close H...H / H...metal contacts, and the repair report records the
route and per-fragment H distribution.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pymatgen.core import Structure

from cifkit.repair import check_structure, perceive_bonds, repair_all
from cifkit.repair.bonds import is_metal

DATA = Path(__file__).parent / "data"
MOF5_HFREE = DATA / "mof5_hfree.cif"
MOF5_H = DATA / "mof5_h.cif"
MOF5_COD_HFREE = DATA / "mof5_cod_hfree.cif"
MOF5_COD_H = DATA / "mof5_cod_h.cif"
UIO66_HFREE = DATA / "uio66_hfree.cif"
UIO66_H = DATA / "uio66_h.cif"
HKUST1_HFREE = DATA / "hkust1_hfree.cif"
HKUST1_H = DATA / "hkust1_h.cif"
UIO66_RAW_NCR = DATA / "uio66_raw_ncr_h24.cif"
TPA_HFREE = DATA / "terephthalic_acid_hfree.cif"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _load(path: Path) -> Structure:
    return Structure.from_file(path)


def _element_counts(structure: Structure) -> dict[str, int]:
    return {
        element.symbol: int(structure.composition[element])
        for element in structure.composition.elements
    }


def _action(report, name: str) -> dict:
    return next(action for action in report.actions if action["action"] == name)


def _periodic_pairs(structure: Structure, search: float = 3.2):
    """Symbols + directed neighbour pairs (i, j, image, distance)."""
    symbols = [site.species_string for site in structure]
    center, point, offsets, distances = structure.get_neighbor_list(search)
    pairs = [
        (int(a), int(b), np.asarray(offset, dtype=float), float(distance))
        for a, b, offset, distance in zip(center, point, offsets, distances)
    ]
    return symbols, pairs


def _h_parents(structure: Structure):
    """Map every H to its nearest heavy atom: H -> (distance, parent, image)."""
    symbols, pairs = _periodic_pairs(structure)
    parents: dict[int, tuple[float, int, np.ndarray]] = {}
    for a, b, offset, distance in pairs:
        if symbols[a] == "H" and symbols[b] != "H" and distance < 1.3:
            if a not in parents or distance < parents[a][0]:
                parents[a] = (distance, b, offset)
    return symbols, pairs, parents


def _angle(v1: np.ndarray, v2: np.ndarray) -> float:
    cosine = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12))
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def _hydrogen_geometry(structure: Structure) -> dict:
    """Classify every H bond and collect the checks used by the tests."""
    symbols, pairs, parents = _h_parents(structure)
    cart = np.asarray(structure.cart_coords, dtype=float)
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    min_hh = np.inf
    min_h_metal = np.inf
    min_h_nonbonded_heavy = np.inf
    ring_angles: list[float] = []
    ring_out_of_plane: list[float] = []
    c_h_lengths: list[float] = []
    o_h_lengths: list[float] = []
    metal_h_lengths: list[float] = []
    o_h_parents: list[int] = []
    for a, b, _offset, distance in pairs:
        if a == b:
            continue
        if symbols[a] == "H" and symbols[b] == "H" and a < b:
            min_hh = min(min_hh, distance)
        if symbols[a] == "H" and symbols[b] != "H":
            if is_metal(symbols[b]):
                min_h_metal = min(min_h_metal, distance)
                metal_h_lengths.append(distance)
            elif a in parents and b == parents[a][1] and distance < 1.3:
                continue
            else:
                min_h_nonbonded_heavy = min(min_h_nonbonded_heavy, distance)

    for h, (distance, parent, h_offset) in parents.items():
        parent_symbol = symbols[parent]
        if parent_symbol == "C":
            c_h_lengths.append(distance)
        elif parent_symbol == "O":
            o_h_lengths.append(distance)
            o_h_parents.append(parent)
        parent_abs = cart[parent] + h_offset @ lattice
        neighbours = [
            (b, cart[b] + offset @ lattice, d)
            for a, b, offset, d in pairs
            if a == parent and b != h and d < 1.95
        ]
        heavy = [(b, position, d) for b, position, d in neighbours if symbols[b] != "H"]
        h_vector = cart[h] - parent_abs
        if parent_symbol == "C" and len(heavy) == 2 and all(symbols[b] == "C" for b, _p, _d in heavy):
            # aromatic ring carbon: H should lie in the ring plane and make
            # ~120 deg with both ring neighbours
            for _b, position, _d in heavy:
                ring_angles.append(_angle(h_vector, position - cart[parent]))
            normal = np.cross(heavy[0][1] - cart[parent], heavy[1][1] - cart[parent])
            ring_out_of_plane.append(
                abs(float(np.dot(h_vector, normal)) / (np.linalg.norm(normal) + 1e-12))
            )
    return {
        "symbols": symbols,
        "pairs": pairs,
        "parents": parents,
        "min_hh": min_hh,
        "min_h_metal": min_h_metal,
        "min_h_nonbonded_heavy": min_h_nonbonded_heavy,
        "ring_angles": ring_angles,
        "ring_out_of_plane": ring_out_of_plane,
        "c_h_lengths": c_h_lengths,
        "o_h_lengths": o_h_lengths,
        "metal_h_lengths": metal_h_lengths,
        "o_h_parents": o_h_parents,
    }


def _oxygen_environment(structure: Structure) -> dict[int, dict]:
    """Per-O neighbour chemistry (metal count / C count / H count)."""
    graph = perceive_bonds(structure)
    info: dict[int, dict] = {}
    for atom in range(len(structure)):
        if graph.symbols[atom] != "O":
            continue
        metal_neighbours = [b for b in graph.adj.get(atom, ()) if b.metal]
        carbon_neighbours = [b for b in graph.adj.get(atom, ()) if graph.symbols[b.j] == "C"]
        info[atom] = {
            "metal": len(metal_neighbours),
            "metal_symbols": sorted({graph.symbols[b.j] for b in metal_neighbours}),
            "carbon": len(carbon_neighbours),
            "h": graph.h_neighbor_count(atom),
        }
    return info


def _aromatic_ring_h_counts(structure: Structure) -> list[int]:
    """Number of ring carbons carrying an H, for every aromatic 6-ring."""
    graph = perceive_bonds(structure)
    counts = []
    for ring in graph.rings:
        if not ring.aromatic or ring.size != 6:
            continue
        counts.append(
            sum(
                1
                for atom in ring.atoms
                if graph.symbols[atom] == "C" and graph.h_neighbor_count(atom) == 1
            )
        )
    return counts


# ---------------------------------------------------------------------------
# module-scope repairs (each is ~0.1-0.5 s)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def repaired_mof5():
    source = _load(MOF5_HFREE)
    repaired, report = repair_all(source, add_hydrogen=True)
    return source, repaired, report


@pytest.fixture(scope="module")
def repaired_mof5_cod():
    source = _load(MOF5_COD_HFREE)
    repaired, report = repair_all(source, add_hydrogen=True)
    return source, repaired, report


@pytest.fixture(scope="module")
def repaired_uio66():
    source = _load(UIO66_HFREE)
    repaired, report = repair_all(source, add_hydrogen=True)
    return source, repaired, report


@pytest.fixture(scope="module")
def repaired_hkust1():
    source = _load(HKUST1_HFREE)
    repaired, report = repair_all(source, add_hydrogen=True)
    return source, repaired, report


# ---------------------------------------------------------------------------
# MOF-5: Zn4O(BDC)3, pcu  (CoRE 2007[Zn][pcu]3[ASR]3, DOI 10.1021/ja074366o)
# ---------------------------------------------------------------------------
def test_mof5_hfree_repairs_to_full_bdc_hydrogen(repaired_mof5):
    source, repaired, report = repaired_mof5
    assert len(source) == 82
    assert _element_counts(source) == {"Zn": 8, "C": 48, "O": 26}
    # all 24 missing H: 6 BDC linkers x 4 aromatic C-H
    assert report.added_h == 24
    assert len(repaired) == 106
    assert _element_counts(repaired) == {"Zn": 8, "C": 48, "H": 24, "O": 26}
    # repaired composition == the real H-complete CoRE MOF-5 record (same DOI)
    assert _element_counts(repaired) == _element_counts(_load(MOF5_H))
    assert report.warnings == []

    valence = check_structure(repaired)
    assert valence["ok"] is True
    assert valence["metrics"]["c_four_coordinate"] == 48
    assert valence["metrics"]["metal_coordination"] == {"Zn": {4: 8}}

    # every BDC ring carries its 4 C-H
    ring_h = _aromatic_ring_h_counts(repaired)
    assert len(ring_h) == 6
    assert all(count == 4 for count in ring_h)

    # mu4-O oxo must not be protonated; carboxylate O must not be protonated
    oxygen = _oxygen_environment(repaired)
    mu4_oxo = [index for index, info in oxygen.items() if info["metal"] == 4]
    assert len(mu4_oxo) == 2  # 2 Zn4O clusters per primitive MOF-5 cell
    assert all(oxygen[index]["h"] == 0 for index in mu4_oxo)
    carboxylate_o = [index for index, info in oxygen.items() if info["carbon"] >= 1]
    assert len(carboxylate_o) == 24
    assert all(oxygen[index]["h"] == 0 for index in carboxylate_o)

    # hydrogen geometry: C-H lengths, ring planarity, no clashes
    geometry = _hydrogen_geometry(repaired)
    assert len(geometry["c_h_lengths"]) == 24
    assert 1.05 <= min(geometry["c_h_lengths"]) <= max(geometry["c_h_lengths"]) <= 1.15
    assert geometry["o_h_lengths"] == []
    assert all(115.0 <= angle <= 125.0 for angle in geometry["ring_angles"])
    assert max(geometry["ring_out_of_plane"]) < 0.10
    assert geometry["min_hh"] > 1.4
    assert geometry["min_h_metal"] > 2.0
    assert geometry["min_h_nonbonded_heavy"] > 1.5

    # structured report: RDKit route, per-fragment 4 H (BDC), 6 fragments
    hydrogen = _action(report, "hydrogen")
    assert hydrogen["added_h"] == 24
    assert hydrogen["h_types"] == {"sp2 C-H": 24}
    assert hydrogen["per_ligand_h"] == {4: 6}
    assert "rdkit" in hydrogen["route"]
    if hydrogen["rdkit"]["available"]:
        assert hydrogen["rdkit"]["fragments_ok"] == 6
        assert hydrogen["rdkit"]["fragments_failed"] == 0


def test_mof5_cod_real_hfree_repairs_to_same_chemistry(repaired_mof5_cod):
    """Independent REAL H-free MOF-5 CIF (COD 4340010) gives the same chemistry."""
    source, repaired, report = repaired_mof5_cod
    assert len(source) == 328  # the COD CIF itself has no H
    assert _element_counts(source) == {"Zn": 32, "C": 192, "O": 104}
    assert report.added_h == 96  # 24 BDC x 4
    assert len(repaired) == 424
    assert _element_counts(repaired) == _element_counts(_load(MOF5_COD_H))
    assert report.warnings == []
    ring_h = _aromatic_ring_h_counts(repaired)
    assert len(ring_h) == 24
    assert all(count == 4 for count in ring_h)
    oxygen = _oxygen_environment(repaired)
    mu4_oxo = [index for index, info in oxygen.items() if info["metal"] == 4]
    assert len(mu4_oxo) == 8
    assert all(oxygen[index]["h"] == 0 for index in mu4_oxo)
    # cross-source consistency: MOF-5 stoich is Zn4O(BDC)3 -> H/Zn = 3
    assert abs(_load(MOF5_H).composition["H"] / _load(MOF5_H).composition["Zn"] - 3.0) < 1e-6
    assert abs(_load(MOF5_COD_H).composition["H"] / _load(MOF5_COD_H).composition["Zn"] - 3.0) < 1e-6
    assert _element_counts(repaired) == _element_counts(_load(MOF5_COD_H))


def test_mof5_hcomplete_is_noop():
    for path, natoms in ((MOF5_H, 106), (MOF5_COD_H, 424)):
        source = _load(path)
        assert len(source) == natoms
        repaired, report = repair_all(source, add_hydrogen=True)
        assert len(source) == natoms
        assert len(repaired) == natoms
        assert report.added_h == 0
        assert report.warnings == []
        assert _action(report, "hydrogen")["route"] == "none"


# ---------------------------------------------------------------------------
# UiO-66: Zr6O4(OH)4(BDC)6, fcu
# ---------------------------------------------------------------------------
def test_uio66_hfree_repairs_ring_and_mu3_oh_hydrogen(repaired_uio66):
    source, repaired, report = repaired_uio66
    assert len(source) == 86
    assert _element_counts(source) == {"Zr": 6, "C": 48, "O": 32}
    # 24 BDC ring C-H + 4 mu3-OH cluster O-H = 28
    assert report.added_h == 28
    assert len(repaired) == 114
    assert _element_counts(repaired) == {"Zr": 6, "C": 48, "H": 28, "O": 32}
    assert _element_counts(repaired) == _element_counts(_load(UIO66_H))
    assert report.warnings == []

    valence = check_structure(repaired)
    assert valence["ok"] is True
    assert valence["metrics"]["c_four_coordinate"] == 48
    assert valence["metrics"]["metal_coordination"] == {"Zr": {8: 6}}

    ring_h = _aromatic_ring_h_counts(repaired)
    assert len(ring_h) == 6
    assert all(count == 4 for count in ring_h)

    oxygen = _oxygen_environment(repaired)
    mu3 = [index for index, info in oxygen.items() if info["metal"] == 3]
    assert len(mu3) == 8
    mu3_oh = [index for index in mu3 if oxygen[index]["h"] == 1]
    mu3_oxo = [index for index in mu3 if oxygen[index]["h"] == 0]
    assert len(mu3_oh) == 4
    assert len(mu3_oxo) == 4
    # the 4 hydroxo O are the longer Zr-O family (2.268 A) of the Zr6 cluster
    graph = perceive_bonds(repaired)
    hydroxo_distances = [
        np.mean([b.distance for b in graph.adj[index] if b.metal]) for index in mu3_oh
    ]
    oxo_distances = [
        np.mean([b.distance for b in graph.adj[index] if b.metal]) for index in mu3_oxo
    ]
    assert min(hydroxo_distances) > max(oxo_distances) + 0.10
    # carboxylate O are not protonated
    carboxylate_o = [index for index, info in oxygen.items() if info["carbon"] >= 1]
    assert len(carboxylate_o) == 24
    assert all(oxygen[index]["h"] == 0 for index in carboxylate_o)

    geometry = _hydrogen_geometry(repaired)
    assert len(geometry["c_h_lengths"]) == 24
    assert len(geometry["o_h_lengths"]) == 4
    assert 0.90 <= min(geometry["o_h_lengths"]) <= max(geometry["o_h_lengths"]) <= 1.05
    assert all(115.0 <= angle <= 125.0 for angle in geometry["ring_angles"])
    assert max(geometry["ring_out_of_plane"]) < 0.10
    assert geometry["min_hh"] > 1.4
    assert geometry["min_h_metal"] > 2.0
    assert geometry["min_h_nonbonded_heavy"] > 1.5

    hydrogen = _action(report, "hydrogen")
    assert hydrogen["added_h"] == 28
    assert hydrogen["h_types"] == {"sp2 C-H": 24, "sp3 O-H": 4}
    # 6 BDC fragments with 4 H each + 4 OH groups with 1 H
    assert hydrogen["per_ligand_h"] == {4: 6, 1: 4}
    # BDC via RDKit, the isolated mu3-O via VSEPR geometry
    assert "rdkit" in hydrogen["route"]
    if hydrogen["rdkit"]["available"]:
        assert hydrogen["rdkit"]["fragments_ok"] == 6
        assert hydrogen["rdkit"]["fragments_failed"] == 0
    assert hydrogen["geometric_placements"] == 4
    assert hydrogen["c_valence_ok"] is True


def test_uio66_hcomplete_is_noop():
    source = _load(UIO66_H)
    assert len(source) == 114
    repaired, report = repair_all(source, add_hydrogen=True)
    assert len(source) == 114
    assert len(repaired) == 114
    assert report.added_h == 0
    assert report.warnings == []
    assert _action(report, "hydrogen")["route"] == "none"
def test_uio66_real_ncr_fixture_is_kept_for_provenance_only():
    """Real CoRE NCR UiO-66 (H24 vs 28) is kept for provenance but not acceptance."""
    structure = _load(UIO66_RAW_NCR)
    assert len(structure) == 110
    assert _element_counts(structure) == {"Zr": 6, "C": 48, "H": 24, "O": 32}
    # 4 H short of the H-complete UiO-66 reference; its distorted geometry makes
    # the oxo/hydroxo assignment ambiguous, see docs/REPAIR.md §8.5.


# ---------------------------------------------------------------------------
# HKUST-1: Cu3(BTC)2, tbo
# ---------------------------------------------------------------------------
def test_hkust1_hfree_repairs_btc_ring_hydrogen(repaired_hkust1):
    source, repaired, report = repaired_hkust1
    assert len(source) == 132
    assert _element_counts(source) == {"Cu": 12, "C": 72, "O": 48}
    # 8 BTC linkers x 3 aromatic C-H = 24
    assert report.added_h == 24
    assert len(repaired) == 156
    assert _element_counts(repaired) == {"Cu": 12, "C": 72, "H": 24, "O": 48}
    assert _element_counts(repaired) == _element_counts(_load(HKUST1_H))
    assert report.warnings == []

    valence = check_structure(repaired)
    assert valence["ok"] is True
    assert valence["metrics"]["c_four_coordinate"] == 72
    assert valence["metrics"]["metal_coordination"] == {"Cu": {4: 12}}

    ring_h = _aromatic_ring_h_counts(repaired)
    assert len(ring_h) == 8
    assert all(count == 3 for count in ring_h)

    # Cu paddlewheel: metal-metal contacts are not bonds, no H on Cu/O
    oxygen = _oxygen_environment(repaired)
    assert all(info["h"] == 0 for info in oxygen.values())
    geometry = _hydrogen_geometry(repaired)
    assert geometry["o_h_lengths"] == []
    assert len(geometry["c_h_lengths"]) == 24
    assert 1.05 <= min(geometry["c_h_lengths"]) <= max(geometry["c_h_lengths"]) <= 1.15
    assert all(115.0 <= angle <= 125.0 for angle in geometry["ring_angles"])
    assert max(geometry["ring_out_of_plane"]) < 0.10
    assert geometry["min_hh"] > 1.4
    assert geometry["min_h_metal"] > 2.0
    assert geometry["min_h_nonbonded_heavy"] > 1.5

    hydrogen = _action(report, "hydrogen")
    assert hydrogen["added_h"] == 24
    assert hydrogen["h_types"] == {"sp2 C-H": 24}
    assert hydrogen["per_ligand_h"] == {3: 8}
    assert "rdkit" in hydrogen["route"]
    if hydrogen["rdkit"]["available"]:
        assert hydrogen["rdkit"]["fragments_ok"] == 8
        assert hydrogen["rdkit"]["fragments_failed"] == 0


def test_hkust1_hcomplete_is_noop():
    source = _load(HKUST1_H)
    assert len(source) == 156
    repaired, report = repair_all(source, add_hydrogen=True)
    assert len(source) == 156
    assert len(repaired) == 156
    assert report.added_h == 0
    assert report.warnings == []
    assert _action(report, "hydrogen")["route"] == "none"


# ---------------------------------------------------------------------------
# free carboxylic acid: the only case where an O-H is added
# ---------------------------------------------------------------------------
def test_free_carboxylic_acid_gets_two_oh():
    source = _load(TPA_HFREE)
    assert len(source) == 16
    assert _element_counts(source) == {"C": 8, "H": 4, "O": 4}
    repaired, report = repair_all(source, add_hydrogen=True)
    assert report.added_h == 2
    assert len(repaired) == 18
    assert _element_counts(repaired) == {"C": 8, "H": 6, "O": 4}
    assert report.warnings == []
    geometry = _hydrogen_geometry(repaired)
    assert len(geometry["o_h_lengths"]) == 2
    assert 0.90 <= min(geometry["o_h_lengths"]) <= max(geometry["o_h_lengths"]) <= 1.05
    assert check_structure(repaired)["ok"] is True


# ---------------------------------------------------------------------------
# CLI integration: repair --add-h on each fixture
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fixture, expected_added, expected_natoms, expected_h",
    [
        (MOF5_HFREE, 24, 106, 24),
        (MOF5_COD_HFREE, 96, 424, 96),
        (UIO66_HFREE, 28, 114, 28),
        (HKUST1_HFREE, 24, 156, 24),
        (MOF5_H, 0, 106, 24),
        (MOF5_COD_H, 0, 424, 96),
        (UIO66_H, 0, 114, 28),
        (HKUST1_H, 0, 156, 24),
    ],
)
def test_cli_repair_add_h(tmp_path, capsys, fixture, expected_added, expected_natoms, expected_h):
    from cifkit.cli import main

    output = tmp_path / "repaired.cif"
    return_code = main(["repair", str(fixture), "-o", str(output), "--add-h", "--json"])
    assert return_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["added_h"] == expected_added
    assert payload["natoms"] == expected_natoms
    assert payload["report"]["warnings"] == []
    roundtrip = Structure.from_file(output)
    assert len(roundtrip) == expected_natoms
    assert int(roundtrip.composition["H"]) == expected_h
    assert check_structure(roundtrip)["ok"] is True
