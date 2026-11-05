"""Export layer tests (owner: geom-export).

Covers every supported format with a real fixture (``zif8_cr_sod.cif``,
138 atoms) plus read-back checks for the formats that have readers.
"""
from __future__ import annotations

from pathlib import Path

import ase.io
import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.vasp import Poscar

from cifkit import export

DATA = Path(__file__).resolve().parent / "data"
EXPECTED_FORMATS = {"vasp", "cif", "xyz", "lammps", "qe", "cp2k", "xsf"}


@pytest.fixture(scope="module")
def zif8() -> Structure:
    return Structure.from_file(str(DATA / "zif8_cr_sod.cif"))


# ---------------------------------------------------------------------------
def test_supported_formats() -> None:
    formats = export.supported_formats()
    assert EXPECTED_FORMATS <= set(formats)
    for name, description in formats.items():
        assert isinstance(name, str) and name == name.strip().lower()
        assert isinstance(description, str) and len(description) > 10
    for alias in ("poscar", "lammps-data", "espresso-in", "cp2k-in", "xcrysden"):
        assert export.normalize_format(alias) in formats


def test_vasp_poscar_is_vasp5_and_reads_back(tmp_path, zif8: Structure) -> None:
    path = export.write_structure(zif8, tmp_path / "structure.vasp", "vasp", title="ZIF-8 primitive")
    assert Path(path) == tmp_path / "structure.vasp"
    assert Path(path).stat().st_size > 0
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "ZIF-8 primitive"
    # VASP5 layout: comment / scale / 3 lattice lines / species names / counts / coord mode
    species = lines[5].split()
    counts = [int(v) for v in lines[6].split()]
    assert set(species) == {"Zn", "H", "C", "N"}
    assert sum(counts) == len(zif8) == 138
    assert lines[7].strip()[0].lower() in ("d", "c")
    poscar = Poscar.from_file(path, check_for_potcar=False, read_velocities=False)
    assert len(poscar.structure) == len(zif8)
    assert poscar.structure.composition.reduced_formula == zif8.composition.reduced_formula


def test_cif_reads_back_with_pymatgen(tmp_path, zif8: Structure) -> None:
    path = export.write_structure(zif8, tmp_path / "structure.cif", "cif")
    text = Path(path).read_text(encoding="utf-8")
    assert "_cell_length_a" in text and "_atom_site_fract_x" in text
    back = Structure.from_file(path)
    assert len(back) == len(zif8)
    assert back.composition.reduced_formula == zif8.composition.reduced_formula
    assert abs(back.lattice.a - zif8.lattice.a) < 1e-3


def test_xyz_reads_back_and_records_the_cell(tmp_path, zif8: Structure) -> None:
    path = export.write_structure(zif8, tmp_path / "structure.xyz", "xyz", title="ZIF-8")
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert int(lines[0]) == len(zif8) == 138
    assert "ZIF-8" in lines[1] and "cell=" in lines[1]
    atoms = ase.io.read(path, format="xyz")
    assert len(atoms) == len(zif8)


@pytest.mark.parametrize("fmt", sorted(EXPECTED_FORMATS))
def test_every_format_writes_a_non_empty_file(tmp_path, zif8: Structure, fmt: str) -> None:
    path = export.write_structure(zif8, tmp_path / f"structure.{fmt}", fmt, title="ZIF-8")
    assert Path(path).is_file()
    assert Path(path).stat().st_size > 0


def test_batch_export_all_formats_at_once(tmp_path, zif8: Structure) -> None:
    """The CLI passes ``--format vasp,cif,xyz,qe,...``; every one must succeed."""
    written = {}
    for fmt in sorted(EXPECTED_FORMATS):
        written[fmt] = export.write_structure(zif8, tmp_path / f"structure.{fmt}", fmt)
    assert set(written) == EXPECTED_FORMATS
    assert all(Path(p).stat().st_size > 0 for p in written.values())


def test_qe_input_has_required_sections(tmp_path, zif8: Structure) -> None:
    path = export.write_structure(zif8, tmp_path / "structure.qe", "qe")
    text = Path(path).read_text(encoding="utf-8")
    for keyword in ("ATOMIC_SPECIES", "CELL_PARAMETERS", "ATOMIC_POSITIONS"):
        assert keyword in text, keyword
    assert "Zn.UPF" in text and "H.UPF" in text  # placeholders found in ATOMIC_SPECIES
    assert len(ase.io.read(path, format="espresso-in")) == len(zif8)


def test_qe_accepts_custom_pseudopotentials(tmp_path, zif8: Structure) -> None:
    path = export.write_structure(
        zif8,
        tmp_path / "custom.qe",
        "qe",
        pseudopotentials={"Zn": "Zn.pbe-vdz.UPF", "C": "C.pbe-n-kjpaw_psl.1.0.0.UPF"},
    )
    text = Path(path).read_text(encoding="utf-8")
    assert "Zn.pbe-vdz.UPF" in text
    assert "C.pbe-n-kjpaw_psl.1.0.0.UPF" in text
    assert "H.UPF" in text  # elements not in the custom mapping keep the placeholder


def test_aliases_are_written_in_the_target_format(tmp_path, zif8: Structure) -> None:
    for alias, canonical in (
        ("poscar", "vasp"),
        ("lammps-data", "lammps"),
        ("espresso-in", "qe"),
        ("cp2k-in", "cp2k"),
        ("xcrysden", "xsf"),
    ):
        assert export.normalize_format(alias) == canonical
        path = export.write_structure(zif8, tmp_path / f"{canonical}_{alias}", alias)
        assert Path(path).stat().st_size > 0


def test_lammps_and_xsf_read_back(tmp_path, zif8: Structure) -> None:
    lammps = export.write_structure(zif8, tmp_path / "m.lammps", "lammps")
    assert len(ase.io.read(lammps, format="lammps-data")) == len(zif8)
    xsf = export.write_structure(zif8, tmp_path / "m.xsf", "xsf")
    assert len(ase.io.read(xsf, format="xsf")) == len(zif8)


def test_cp2k_skeleton_has_cell_and_coords(tmp_path, zif8: Structure) -> None:
    path = export.write_structure(zif8, tmp_path / "cp2k.inp", "cp2k")
    text = Path(path).read_text(encoding="utf-8")
    assert "&CELL" in text and "&COORD" in text and "&END COORD" in text
    assert "ALPHA_BETA_GAMMA" in text
    # one coordinate line per atom inside the &COORD block
    inside = False
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("&COORD"):
            inside = True
            continue
        if inside and stripped.startswith("&END"):
            inside = False
        elif inside and stripped:
            count += 1
    assert count == len(zif8)


def test_unsupported_format_raises_value_error(tmp_path, zif8: Structure) -> None:
    with pytest.raises(ValueError, match="available"):
        export.write_structure(zif8, tmp_path / "x.gjf", "gaussian")
    with pytest.raises(ValueError, match="cif"):
        export.normalize_format("nonsense")
    with pytest.raises(ValueError):
        export.write_structure("not a structure", tmp_path / "x.cif", "cif")


def test_empty_structure_is_rejected(tmp_path) -> None:
    empty = Structure(Lattice.cubic(5.0), [], [], validate_proximity=False)
    with pytest.raises(ValueError, match="empty"):
        export.write_structure(empty, tmp_path / "empty.cif", "cif")


def test_hfree_fixture_exports(tmp_path) -> None:
    hfree = Structure.from_file(str(DATA / "zif8_raw_hfree.cif"))
    path = export.write_structure(hfree, tmp_path / "hfree.vasp", "vasp")
    assert len(Poscar.from_file(path, check_for_potcar=False).structure) == len(hfree) == 156
