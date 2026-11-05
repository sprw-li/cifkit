"""Geometry layer tests (owner: geom-export).

Numbers asserted here were measured on this project's fixtures:

* ``tests/data/zif8_cr_sod.cif``: CoRE ASR sod ZIF-8, rhombohedral **primitive**
  cell, 138 atoms, a = 14.669 Å, I-43m.
* ``standardize`` -> conventional cubic cell, 276 atoms, a = 16.939 Å.
* ``make_supercell(conv, (2, 2, 1))`` -> 1104 atoms.
* ``(111)`` slab of the conventional cell -> 552 atoms, ~19 Å thick; a 2x2
  in-plane repeat -> 2208 atoms; measured vacuum >= 15 Å.
"""
from __future__ import annotations

import math
import warnings
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pymatgen.core import Lattice, Structure
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from cifkit import export, geom
from cifkit.geom._common import gaps_all_axes, vacuum_metrics
from cifkit.geom.surface import _select_candidate

DATA = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def zif8_prim() -> Structure:
    return Structure.from_file(str(DATA / "zif8_cr_sod.cif"))


@pytest.fixture(scope="module")
def zif8_conv(zif8_prim: Structure) -> Structure:
    return geom.standardize(zif8_prim)


@pytest.fixture(scope="module")
def slab_2x2(zif8_conv: Structure):
    """(111) slab of the 276-atom conventional cell, 2x2 in-plane -> 2208 atoms."""
    slab, info = geom.make_slab(
        zif8_conv,
        (1, 1, 1),
        slab_thickness=15.0,
        vacuum=15.0,
        reps=(2, 2, 1),
        frame="slab",
    )
    return slab, info


# ---------------------------------------------------------------------------
# standardize
# ---------------------------------------------------------------------------
def test_fixture_is_the_rhombohedral_primitive_cell(zif8_prim: Structure) -> None:
    assert len(zif8_prim) == 138
    assert all(abs(a - 14.669) < 0.01 for a in zif8_prim.lattice.abc)
    assert all(abs(ang - 109.47) < 0.1 for ang in zif8_prim.lattice.angles)
    assert SpacegroupAnalyzer(zif8_prim).get_space_group_symbol() == "I-43m"


def test_standardize_primitive_to_conventional(zif8_prim: Structure, zif8_conv: Structure) -> None:
    assert len(zif8_conv) == 2 * len(zif8_prim) == 276
    assert all(abs(a - 16.939) < 0.05 for a in zif8_conv.lattice.abc)
    assert all(abs(ang - 90.0) < 0.01 for ang in zif8_conv.lattice.angles)
    assert SpacegroupAnalyzer(zif8_conv).get_space_group_symbol() == "I-43m"
    counts = {el.symbol: int(n) for el, n in zif8_conv.composition.items()}
    assert counts == {"Zn": 12, "C": 96, "N": 48, "H": 120}
    # volume per atom is conserved by the primitive -> conventional conversion
    vpa_in = zif8_prim.volume / len(zif8_prim)
    vpa_out = zif8_conv.volume / len(zif8_conv)
    assert abs(vpa_in - vpa_out) / vpa_in < 0.01
    info = getattr(zif8_conv, "_cifkit_geom_info", {})
    assert info.get("kept") == "standardized"
    assert info.get("natoms_out") == 276


def test_standardize_conventional_hfree_is_a_noop() -> None:
    """The H-free raw ZIF-8 is already conventional: keep 156 atoms / a=17.029."""
    hfree = Structure.from_file(str(DATA / "zif8_raw_hfree.cif"))
    out = geom.standardize(hfree)
    assert len(out) == 156
    assert all(abs(a - 17.029) < 0.01 for a in out.lattice.abc)
    assert all(abs(ang - 90.0) < 0.01 for ang in out.lattice.angles)
    info = getattr(out, "_cifkit_geom_info", {})
    assert info.get("kept") == "input"
    assert "symmetry kept as input" in str(info.get("note"))


def test_standardize_does_not_double_the_repaired_conventional_cell(zif8_conv: Structure) -> None:
    """Regression: the repaired (276-atom) conventional cell is seen as Fmm2 by spglib.

    spglib's conventional setting for that structure has 552 atoms; ``standardize``
    must keep the 276-atom input cell instead of doubling it (Lead-reported bug:
    the demo pipeline produced a 552-atom "standardized" cell).
    """
    out = geom.standardize(zif8_conv)
    assert len(out) == 276
    assert all(abs(a - 16.939) < 0.05 for a in out.lattice.abc)
    info = getattr(out, "_cifkit_geom_info", {})
    assert info.get("kept") == "input"
    assert int(info.get("primitive_atoms", -1)) == 138
    assert "2x cell" in str(info.get("reason"))


def test_standardize_to_primitive(zif8_conv: Structure) -> None:
    prim = geom.standardize(zif8_conv, target="primitive")
    assert len(prim) == 138
    assert all(abs(a - 14.669) < 0.05 for a in prim.lattice.abc)


def test_standardize_p1_is_a_safe_noop() -> None:
    rng = np.random.default_rng(7)
    lattice = Lattice.from_parameters(6.1, 7.2, 8.3, 71.0, 82.0, 65.0)
    species = ["Na", "Cl", "C", "O", "N"]
    frac = rng.random((5, 3))
    p1 = Structure(lattice, species, frac)
    assert SpacegroupAnalyzer(p1).get_space_group_symbol() == "P1", "fixture must be P1"
    out = geom.standardize(p1)
    assert len(out) == 5
    assert np.allclose(out.lattice.matrix, p1.lattice.matrix, atol=1e-6)
    info = getattr(out, "_cifkit_geom_info", {})
    assert info.get("kept") == "input"
    assert "P1" in str(info.get("reason"))


def test_standardize_rejects_unknown_target(zif8_prim: Structure) -> None:
    with pytest.raises(ValueError, match="conventional"):
        geom.standardize(zif8_prim, target="banana")


# ---------------------------------------------------------------------------
# supercell
# ---------------------------------------------------------------------------
def test_supercell_atom_count_is_exact(zif8_prim: Structure, zif8_conv: Structure) -> None:
    cell_552 = geom.make_supercell(zif8_prim, (2, 2, 1))
    assert len(cell_552) == 552 == 4 * len(zif8_prim)
    assert abs(cell_552.lattice.a - 2 * zif8_prim.lattice.a) < 1e-6
    cell_1104 = geom.make_supercell(zif8_conv, (2, 2, 1))
    assert len(cell_1104) == 1104 == 4 * len(zif8_conv)
    assert abs(cell_1104.lattice.a - 2 * zif8_conv.lattice.a) < 1e-6
    info = getattr(cell_1104, "_cifkit_geom_info", {})
    assert info.get("natoms_in") == 276 and info.get("natoms_out") == 1104


@pytest.mark.parametrize("reps", [(0, 2, 1), (2, 2), (2, -1, 1)])
def test_supercell_rejects_bad_reps(zif8_prim: Structure, reps) -> None:
    with pytest.raises(ValueError):
        geom.make_supercell(zif8_prim, reps)


# ---------------------------------------------------------------------------
# vacuum
# ---------------------------------------------------------------------------
def test_set_vacuum_is_exact_for_an_orthogonal_slab() -> None:
    slab = Structure(
        Lattice.orthorhombic(5.0, 5.0, 20.0),
        ["Si", "Si"],
        [[0.0, 0.0, 0.30], [0.5, 0.5, 0.34]],
    )
    out, measured = geom.set_vacuum(slab, 15.0)
    metrics = vacuum_metrics(out)
    thickness = metrics["thickness"]
    assert abs(thickness - 0.8) < 1e-6
    assert abs(out.lattice.c - (thickness + 15.0)) < 1e-6
    # returned value is the PERPENDICULAR vacuum layer -> exactly the target
    assert abs(measured - 15.0) < 1e-6
    assert abs(metrics["vacuum_perp"] - 15.0) < 1e-6
    assert abs(metrics["vacuum"] - metrics["vacuum_perp"]) < 1e-12
    # the min periodic-image distance is only a lower bound and can be larger
    assert metrics["min_image_distance"] >= metrics["vacuum_perp"] - 1e-6
    info = getattr(out, "_cifkit_geom_info", {})
    assert abs(info.get("min_image_distance", 0.0) - metrics["min_image_distance"]) < 1e-6
    # idempotent: the pipeline runs set_vacuum once more after make_slab
    again, measured_again = geom.set_vacuum(out, 15.0)
    assert abs(again.lattice.c - out.lattice.c) < 1e-6
    assert abs(measured_again - 15.0) < 1e-6


@pytest.mark.parametrize("target", [0.0, -5.0, float("nan")])
def test_set_vacuum_rejects_bad_target(target: float) -> None:
    slab = Structure(Lattice.cubic(5.0), ["Si"], [[0.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="vacuum"):
        geom.set_vacuum(slab, target)


def test_set_vacuum_rejects_empty_structure() -> None:
    empty = Structure(Lattice.cubic(5.0), [], [], validate_proximity=False)
    with pytest.raises(ValueError):
        geom.set_vacuum(empty, 10.0)


# ---------------------------------------------------------------------------
# cluster / SBU
# ---------------------------------------------------------------------------
def test_extract_sbu_is_a_finite_zn_imidazolate_cluster(zif8_prim: Structure) -> None:
    cluster = geom.extract_cluster(zif8_prim, mode="sbu")
    counts = {el.symbol: int(n) for el, n in cluster.composition.items()}
    # ZIF-8 SBU: one Zn + four complete 2-methylimidazolate ligands (C4H5N2)
    assert counts == {"Zn": 1, "C": 16, "N": 8, "H": 20}
    assert len(cluster) == 45
    assert all(g > 5.0 for g in gaps_all_axes(cluster)), "the extracted cluster must be isolated"
    info = getattr(cluster, "_cifkit_geom_info", {})
    assert info.get("mode") == "sbu"


def test_extract_metal_cluster_is_first_shell_only(zif8_prim: Structure) -> None:
    cluster = geom.extract_cluster(zif8_prim, mode="metal_cluster")
    counts = {el.symbol: int(n) for el, n in cluster.composition.items()}
    assert counts == {"Zn": 1, "N": 4}


def test_extract_cluster_requires_metals() -> None:
    organic = Structure(Lattice.cubic(6.0), ["C", "N", "O", "H"], [[0.0, 0.0, 0.0], [0.3, 0.1, 0.2], [0.1, 0.4, 0.2], [0.2, 0.2, 0.5]])
    with pytest.raises(ValueError, match="no metal"):
        geom.extract_cluster(organic, mode="sbu")


# ---------------------------------------------------------------------------
# surfaces
# ---------------------------------------------------------------------------
def test_make_slab_two_by_two_numbers(slab_2x2, zif8_conv: Structure) -> None:
    slab, info = slab_2x2
    # frame="slab": cut the conventional cell, then repeat in plane
    assert info["frame"] == "slab"
    assert info["hkl"] == [1, 1, 1]
    assert info["reps"] == (2, 2, 1)
    assert info["base_atoms"] == 552, "the un-repeated (111) slab of the 276-atom cell has 552 atoms"
    assert info["atoms_after_reps"] == 2208
    assert info["natoms"] == 2208 == len(slab) == 4 * info["base_atoms"]

    thickness = info["slab_thickness"]
    vacuum = info["vacuum_measured"]  # perpendicular vacuum layer
    assert 15.0 <= thickness <= 30.0, thickness
    assert abs(vacuum - 15.0) < 0.01, f"perpendicular vacuum {vacuum} != 15 Å"
    assert info["vacuum_perp"] == vacuum
    assert info["min_image_distance"] >= vacuum - 1e-6
    assert abs(info["c_length"] - (thickness + 15.0)) < 0.02
    # c is perpendicular to the surface plane (a,b)
    matrix = np.asarray(slab.lattice.matrix, dtype=float)
    cos_ca = float(np.dot(matrix[0], matrix[2]) / (np.linalg.norm(matrix[0]) * np.linalg.norm(matrix[2])))
    assert abs(cos_ca) < 1e-6

    # metric definition check: vacuum_perp == d_perp - thickness (standard)
    metrics = vacuum_metrics(slab)
    assert abs(metrics["vacuum_perp"] - (metrics["d_perp"] - metrics["thickness"])) < 1e-6
    assert abs(metrics["vacuum"] - metrics["vacuum_perp"]) < 1e-12

    # "slab atoms > supercell atoms" acceptance check
    supercell = geom.make_supercell(zif8_conv, (2, 2, 1))
    assert len(slab) > len(supercell)

    # candidate bookkeeping for the report
    assert info["n_candidates"] == len(info["candidates"]) >= 1
    required = {"shift", "natoms", "thickness", "dangling_bonds", "stoichiometry_deviation", "score"}
    for cand in info["candidates"]:
        assert required <= set(cand)
    assert info["termination"]["mode"] == "best"


def test_make_slab_info_has_report_fields(slab_2x2) -> None:
    _slab, info = slab_2x2
    for key in (
        "frame",
        "hkl",
        "reps",
        "base_atoms",
        "atoms_after_reps",
        "slab_thickness",
        "vacuum_measured",
        "vacuum_perp",
        "min_image_distance",
        "candidates",
        "termination",
        "lattice",
        "surface_area",
        "generator",
    ):
        assert key in info, key
    assert info["vacuum"] == info["vacuum_measured"] == info["vacuum_perp"]
    assert info["min_image_distance"] >= info["vacuum_perp"] - 1e-6
    assert info["formula"].startswith("Zn96") or "Zn96" in info["formula"]


def test_make_slab_vacuum_survives_pipeline_set_vacuum(slab_2x2) -> None:
    slab, info = slab_2x2
    again, measured = geom.set_vacuum(slab, 15.0)
    assert abs(again.lattice.c - slab.lattice.c) < 1e-6
    assert abs(measured - 15.0) < 0.01
    assert abs(measured - info["vacuum_measured"]) < 0.01


def test_make_slab_frame_cell_keeps_literal_semantics(zif8_conv: Structure) -> None:
    slab, info = geom.make_slab(
        zif8_conv, (1, 1, 1), slab_thickness=10.0, vacuum=15.0, reps=None, frame="cell"
    )
    assert info["frame"] == "cell"
    assert len(slab) == info["base_atoms"] == info["atoms_after_reps"]
    assert abs(info["vacuum_measured"] - 15.0) < 0.01
    assert info["min_image_distance"] >= info["vacuum_measured"] - 1e-6


def test_make_slab_termination_selection_logic() -> None:
    candidates = [
        {
            "shift": 0.1,
            "score": 5.0,
            "natoms": 10,
            "surface_elements_top": {"Zn": 2},
            "surface_elements_bottom": {"C": 3},
        },
        {
            "shift": 0.2,
            "score": 1.0,
            "natoms": 10,
            "surface_elements_top": {"C": 2},
            "surface_elements_bottom": {"C": 3},
        },
    ]
    assert _select_candidate(candidates, None)[0]["shift"] == 0.2
    assert _select_candidate(candidates, "auto")[0]["shift"] == 0.2
    assert _select_candidate(candidates, 0)[0]["shift"] == 0.1
    assert _select_candidate(candidates, -1)[0]["shift"] == 0.2
    assert _select_candidate(candidates, 0.1)[0]["shift"] == 0.1
    assert _select_candidate(candidates, "zn")[0]["shift"] == 0.1
    with pytest.raises(ValueError, match="available surface elements"):
        _select_candidate(candidates, "Xx")
    with pytest.raises(ValueError, match="out of range"):
        _select_candidate(candidates, 5)
    with pytest.raises(ValueError):
        _select_candidate(candidates, True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hkl": (0, 0, 0)},
        {"hkl": (1, 1, 1), "slab_thickness": 0.0},
        {"hkl": (1, 1, 1), "vacuum": -1.0},
        {"hkl": (1, 1, 1), "frame": "banana"},
        {"hkl": (1, 1, 1), "reps": (2, 2, 2), "frame": "slab"},
        {"hkl": (1, 1, 1), "reps": (0, 2, 1)},
    ],
)
def test_make_slab_rejects_bad_arguments(zif8_prim: Structure, kwargs) -> None:
    hkl = kwargs.pop("hkl")
    with pytest.raises(ValueError):
        geom.make_slab(zif8_prim, hkl, **kwargs)


def test_slab_exports_to_poscar_with_matching_atom_count(slab_2x2, tmp_path) -> None:
    slab, _info = slab_2x2
    path = export.write_structure(slab, tmp_path / "slab.vasp", "vasp", title="ZIF-8 (111) slab 2x2")
    assert Path(path).stat().st_size > 0
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("ZIF-8 (111) slab 2x2")
    species = lines[5].split()
    assert "Zn" in species and "H" in species and "C" in species and "N" in species
    assert sum(int(v) for v in lines[6].split()) == len(slab) == 2208
    poscar = Poscar.from_file(path, check_for_potcar=False, read_velocities=False)
    assert len(poscar.structure) == len(slab)
    assert poscar.structure.composition.reduced_formula == slab.composition.reduced_formula


# ---------------------------------------------------------------------------
# preview rendering (cifkit.render)
# ---------------------------------------------------------------------------
def test_render_produces_a_1200x900_png(tmp_path, zif8_prim: Structure) -> None:
    from cifkit.render import render_structure

    path = render_structure(zif8_prim, tmp_path / "preview.png")
    assert Path(path).is_file()
    assert Path(path).stat().st_size > 1000
    assert Image.open(path).size == (1200, 900)


def test_render_slab_uses_side_view_with_cjk_title(tmp_path, slab_2x2) -> None:
    from cifkit.render import render_structure

    slab, _info = slab_2x2
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        path = render_structure(slab, tmp_path / "slab.png", title="沿 (111) 面切出的 ZIF-8 slab")
    assert Path(path).is_file()
    assert Image.open(path).size == (1200, 900)
    # no matplotlib "Glyph ... missing from font" warnings may leak from a CJK title
    leaked = [str(w.message) for w in caught if "Glyph" in str(w.message)]
    assert not leaked, leaked[:3]


def test_render_rejects_unknown_view(tmp_path, zif8_prim: Structure) -> None:
    from cifkit.render import render_structure

    with pytest.raises(ValueError, match="view must be"):
        render_structure(zif8_prim, tmp_path / "bad.png", view="banana")
