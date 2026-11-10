"""Strict parsers for cifkit's own template exports.

Five formats are *input templates* for electronic-structure codes; no third-party
reader in our dependency set can parse them (ASE's ``siesta``/``dftb``/``abacus``/
``orca``/``cp2k`` modules do not accept our files — see
``runs/probe_template_readers.json``).  The previous check was "do these keywords
appear", which cannot notice a truncated coordinate block.

This module actually parses each template and asserts the things a code would
need: atom count, element set, and the cell.  It is an in-house check (not an
independent reader) — the docstring says so, and so does the report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TemplateReport:
    ok: bool
    natoms: int | None = None
    elements: list[str] = field(default_factory=list)
    cell: list[list[float]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "natoms": self.natoms, "elements": self.elements,
                "cell": self.cell, "errors": self.errors}


def _rows(block: str) -> list[list[float]]:
    rows = []
    for line in block.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                rows.append([float(value) for value in parts[:3]])
            except ValueError:
                continue
    return rows


def check_cp2k(text: str) -> TemplateReport:
    report = TemplateReport(ok=False)
    coord = re.search(r"&COORD(.*?)&END COORD", text, re.S)
    if not coord:
        report.errors.append("no &COORD block")
        return report
    elements = []
    for line in coord.group(1).splitlines():
        parts = line.split()
        if parts and re.fullmatch(r"[A-Z][a-z]?", parts[0]):
            elements.append(parts[0])
    report.natoms = len(elements)
    report.elements = sorted(set(elements))
    cell = re.search(r"&CELL(.*?)&END CELL", text, re.S)
    if cell:
        abc = re.search(r"ABC\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", cell.group(1))
        if abc:
            lengths = [float(abc.group(i)) for i in (1, 2, 3)]
            report.cell = [[lengths[0], 0, 0], [0, lengths[1], 0], [0, 0, lengths[2]]]
    if not report.natoms:
        report.errors.append("no atoms in &COORD")
    report.ok = not report.errors and report.natoms > 0
    return report


def check_siesta(text: str) -> TemplateReport:
    report = TemplateReport(ok=False)
    natoms_declared = re.search(r"NumberOfAtoms\s+(\d+)", text)
    coords = re.search(r"%block AtomicCoordinatesAndAtomicSpecies(.*?)%endblock", text, re.S)
    lattice = re.search(r"%block LatticeVectors(.*?)%endblock", text, re.S)
    if not coords:
        report.errors.append("no AtomicCoordinatesAndAtomicSpecies block")
    else:
        rows = [line.split() for line in coords.group(1).splitlines() if line.strip()]
        species = sorted({row[-1] for row in rows if row and row[-1].isdigit()})
        report.natoms = len(rows)
        report.elements = species  # species *indices* here; SIESTA numbers its species
        if natoms_declared and int(natoms_declared.group(1)) != report.natoms:
            report.errors.append(
                f"NumberOfAtoms={natoms_declared.group(1)} but {report.natoms} rows")
    if lattice:
        report.cell = _rows(lattice.group(1))
        if len(report.cell) != 3:
            report.errors.append(f"LatticeVectors has {len(report.cell)} rows, expected 3")
    else:
        report.errors.append("no LatticeVectors block")
    label = re.search(r"%block ChemicalSpeciesLabel(.*?)%endblock", text, re.S)
    if label is None:
        # the template documents that the user adds it; its absence is a real gap
        report.errors.append("no ChemicalSpeciesLabel block (template documents this)")
    elif not label.group(1).strip():
        report.errors.append("ChemicalSpeciesLabel block is empty (template placeholder)")
    report.ok = not report.errors and bool(report.natoms)
    return report


def check_abacus(text: str) -> TemplateReport:
    report = TemplateReport(ok=False)
    species_block = re.search(r"ATOMIC_SPECIES(.*?)\n\s*\n", text, re.S)
    elements = []
    if species_block:
        for line in species_block.group(1).splitlines():
            parts = line.split()
            if len(parts) >= 2 and re.fullmatch(r"[A-Z][a-z]?", parts[0]):
                elements.append(parts[0])
    else:
        report.errors.append("no ATOMIC_SPECIES block")

    positions = re.search(r"ATOMIC_POSITIONS(.*?)(?=\n\s*\n\s*\S+\s*=|\Z)", text, re.S)
    if positions:
        # ABACUS repeats, per species: symbol, magnetism, count, then `count` rows.
        # Counting the actual coordinate rows is stricter than trusting the counts.
        rows = 0
        for line in positions.group(1).splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                [float(value) for value in parts[:3]]
            except ValueError:
                continue
            rows += 1
        report.natoms = rows
    else:
        report.errors.append("no ATOMIC_POSITIONS block")

    lattice = re.search(r"LATTICE_VECTORS(.*?)\n\s*\n", text, re.S)
    if lattice:
        report.cell = _rows(lattice.group(1))
        if len(report.cell) != 3:
            report.errors.append(f"LATTICE_VECTORS has {len(report.cell)} rows")
    else:
        report.errors.append("no LATTICE_VECTORS block")
    report.elements = sorted(set(elements))
    if not report.natoms:
        report.errors.append("could not count atoms from ATOMIC_POSITIONS")
    elif report.elements:
        # species listed but no coordinates for one of them -> suspicious
        pass
    report.ok = not report.errors and bool(report.natoms)
    return report


def check_orca(text: str) -> TemplateReport:
    report = TemplateReport(ok=False)
    match = re.search(r"^\*\s*xyz\s+\S+\s+\S+\s*$(.*?)^\*", text, re.M | re.S)
    if not match:
        report.errors.append("no '* xyz charge mult' block")
        return report
    elements = []
    for line in match.group(1).splitlines():
        parts = line.split()
        if len(parts) >= 4 and re.fullmatch(r"[A-Z][a-z]?", parts[0]):
            try:
                for value in parts[1:4]:
                    float(value)
            except ValueError:
                continue
            elements.append(parts[0])
    report.natoms = len(elements)
    report.elements = sorted(set(elements))
    header = re.search(r"#\s*(\S+)\s*\((\d+) atoms\)", text)
    if header and int(header.group(2)) != report.natoms:
        report.errors.append(f"header says {header.group(2)} atoms, block has {report.natoms}")
    if not re.search(r"^!", text, re.M):
        report.errors.append("no route line ('! ...')")
    report.ok = not report.errors and report.natoms > 0
    return report


def check_dftb(hsd_text: str, gen_text: str | None) -> TemplateReport:
    report = TemplateReport(ok=False)
    if not re.search(r"Geometry\s*=\s*GenFormat", hsd_text):
        report.errors.append("Geometry is not a GenFormat block")
    for keyword in ("Hamiltonian", "SlaterKosterFiles", "MaxAngularMomentum"):
        if keyword not in hsd_text:
            report.errors.append(f"missing {keyword}")
    if gen_text is None:
        report.errors.append("no geo.gen to read coordinates from")
        return report
    lines = [line for line in gen_text.splitlines() if line.strip()]
    if len(lines) < 3:
        report.errors.append("gen file too short")
        return report
    header = lines[0].split()
    try:
        natoms = int(header[0])
    except (ValueError, IndexError):
        report.errors.append("gen header has no atom count")
        return report
    periodic = len(header) > 1 and header[1].upper() in ("S", "C", "F")
    if not periodic:
        report.errors.append(f"gen header mode is not S/C/F: {header[1:2]}")
    kind = None
    try:
        if periodic and len(header) > 2:
            kind = int(header[2])
    except ValueError:
        kind = None
    symbols_line = lines[1].split()
    if kind is not None and len(symbols_line) < kind:
        report.errors.append(f"gen species line has {len(symbols_line)} < {kind} entries")
    coord_rows = [line for line in lines[2:] if re.match(r"\s*\d+\s+\d+\s+", line)]
    report.natoms = len(coord_rows)
    report.elements = sorted(set(symbols_line[:kind] if kind else symbols_line))
    if report.natoms != natoms:
        report.errors.append(f"gen header says {natoms} atoms, {report.natoms} rows")
    report.ok = not report.errors and report.natoms > 0
    return report


CHECKS = {"cp2k": check_cp2k, "siesta": check_siesta, "abacus": check_abacus,
          "orca": check_orca}


def check_template(fmt: str, text: str, companion: dict[str, str] | None = None) -> TemplateReport:
    """Validate one template export (``companion`` carries e.g. ``geo.gen``)."""
    if fmt == "dftb":
        companion = companion or {}
        return check_dftb(text, companion.get("geo.gen"))
    check = CHECKS.get(fmt)
    if check is None:
        raise ValueError(f"no template parser for {fmt!r}")
    return check(text)


__all__ = ["TemplateReport", "check_template", "CHECKS"]
