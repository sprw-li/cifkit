"""Element ground-state reference (Lead-owned, read-only for teammates).

Primary source: ASE's built-in ``ase.data.reference_states`` table (lattice
constants from Kittel/Ashcroft-style standard tables).  This is used instead of
"AFLOW LIB1 lowest energy_atom" because AFLOW's prototype library contains many
polytypes per element and its energies are not comparable across prototypes /
potential sets (verified wrong picks: Sn->diamond, Hg->bcc, Ga->bct, In->hcp,
Mn->hcp, Sm->hcp).

For simple lattices ASE can build the structure directly.  For complex basis
structures (Mn, Ga, Sn, In, Hg, Sm, U, Np, Pu, ...) the basis is missing in the
ASE table, so callers should fetch a structure from AFLOW/COD filtered by the
expected space group below and verify it with spglib.

Expected space groups for the common elemental ground states::

    fcc 225 | bcc 229 | hcp 194 | sc 221 | diamond 227
    bct In 139 (I4/mmm) | bct Sn 141 (I41/amd)
    alpha-Ga 64 (Cmca) | alpha-Mn 217 (I-43m) | alpha-Hg 166 (R-3m)
    Sm 166 (R-3m) | alpha-U 63 (Cmcm) | alpha-Np 62 (Pnma) | alpha-Pu 11 (P21/m)
"""
from __future__ import annotations

#: space group number for simple ASE ``symmetry`` labels
SG_FOR_SYMMETRY = {
    "fcc": 225,
    "bcc": 229,
    "hcp": 194,
    "sc": 221,
    "diamond": 227,
}

#: expected ground-state space group for elements whose ASE basis is missing
EXPECTED_SG = {
    "Mn": 217,   # alpha-Mn, cI58
    "Ga": 64,    # alpha-Ga, Cmca
    "In": 139,   # In, I4/mmm
    "Sn": 141,   # beta-Sn, I41/amd
    "Hg": 166,   # alpha-Hg, R-3m
    "Sm": 166,   # alpha-Sm, R-3m
    "U": 63,     # alpha-U, Cmcm
    "Np": 62,    # alpha-Np, Pnma (uncertain)
    "Pu": 11,    # alpha-Pu, P21/m (uncertain)
}

#: elements with unreliable / predicted ground states; report as uncertain or missing
UNCERTAIN = {"Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr",
             "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn"}
