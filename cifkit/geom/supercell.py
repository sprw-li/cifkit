"""超胞构建（严格校验原子数守恒）。

Owner: geom teammate. Public API (DESIGN.md §6):

    make_supercell(structure, reps) -> Structure
"""
from __future__ import annotations

from collections.abc import Sequence

from pymatgen.core import Structure

from cifkit.geom._common import attach_geom_info

#: refuse to materialise absurdly large cells (guards against typos in the CLI)
MAX_ATOMS = 50_000


def make_supercell(structure: Structure, reps: Sequence[int]) -> Structure:
    """Build ``structure * (r0, r1, r2)`` and verify the atom count exactly.

    Args:
        structure: input structure.
        reps: three positive integers.

    Returns:
        The supercell. ``len(result) == len(structure) * r0 * r1 * r2`` is
        guaranteed (``RuntimeError`` otherwise, which would indicate a pymatgen
        regression).

    Raises:
        ValueError: bad ``reps`` or a supercell larger than :data:`MAX_ATOMS`.
    """
    if reps is None:
        raise ValueError("make_supercell: reps must be a sequence of three positive integers")
    try:
        triple = tuple(int(r) for r in reps)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"make_supercell: reps must be three integers, got {reps!r}") from exc
    if len(triple) != 3:
        raise ValueError(f"make_supercell: reps must have exactly three entries, got {reps!r}")
    if any(r < 1 for r in triple):
        raise ValueError(f"make_supercell: reps must all be >= 1, got {triple}")

    expected = len(structure) * triple[0] * triple[1] * triple[2]
    if expected > MAX_ATOMS:
        raise ValueError(
            f"make_supercell: supercell {triple} of {len(structure)} atoms would contain "
            f"{expected} atoms (> limit {MAX_ATOMS}); split the operation or raise the limit"
        )

    result = structure * triple
    if len(result) != expected:  # pragma: no cover - would be a pymatgen bug
        raise RuntimeError(
            f"supercell atom count mismatch: got {len(result)}, expected {expected} "
            f"({len(structure)} x {triple})"
        )
    info = {
        "function": "make_supercell",
        "reps": list(triple),
        "natoms_in": len(structure),
        "natoms_out": len(result),
    }
    return attach_geom_info(result, info)
