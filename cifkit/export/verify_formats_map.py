"""Reader mapping shared by ``scripts/verify_formats.py`` and the corpus verifier.

**Extracted** from the working script (round 55) rather than retyped: a hand-written
copy invented ASE format names (``abinit`` instead of ``abinit-in``), which made the
corpus verifier report five false failures on every structure.  Re-run
``.probe/extract_reader_map.py`` if the script's map changes.
"""
from __future__ import annotations

#: formats read back with pymatgen

PYMATGEN_READERS = ["cif", "json", "vasp"]

#: formats read back with ASE (format strings as ASE expects them)
ASE_READERS = {
    'abinit': 'abinit-in',
    'aims': 'aims',
    'castep': 'castep-cell',
    'cfg': 'cfg',
    'crystal': 'crystal',
    'dmol': 'dmol-arc',
    'extxyz': 'extxyz',
    'gaussian': 'gaussian-in',
    'gen': 'gen',
    'gromacs': 'gromacs',
    'lammps': 'lammps-data',
    'mol': 'mol',
    'nwchem': 'nwchem-in',
    'onetep': 'onetep-in',
    'pdb': 'proteindatabank',
    'qe': 'espresso-in',
    'res': 'res',
    'sdf': 'sdf',
    'struct': 'struct',
    'turbomole': 'turbomole',
    'xsf': 'xsf',
    'xyz': 'xyz',
}

__all__ = ["PYMATGEN_READERS", "ASE_READERS"]
