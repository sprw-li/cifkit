"""Shared finite/degenerate-cell guards for every symmetry (spglib) entry point.

Why this module exists
----------------------
``spglib`` reads the lattice matrix in **native** code and does not tolerate
non-finite entries: handing it a cell containing ``nan`` (e.g. a CIF whose
``_cell_angle_beta`` is the plain ASCII token ``nan``) is an access violation
that kills the whole process -- exit ``0xC0000005`` / ``-1073741819``, zero
bytes on stdout, no Python traceback.  In a server (one ``POST /rpc``) that is
a remote denial of service, because the process dies instead of returning a
JSON error.

``cifkit.validate`` already *reports* this class of defect (``lattice`` check),
but a report is not a guard: callers that skip validation, or that take the
``--no-rdf`` / ``--topology`` / ``--standardize`` / ``--surface`` branches,
still reached ``pymatgen.symmetry.analyzer.SpacegroupAnalyzer`` (and
``SlabGenerator``, which calls spglib internally) with the poisoned cell.

This module is the single guard used by those entry points.  It is intentionally
dependency-light (``math`` + ``numpy`` only, no pymatgen import) so it can be
called from anywhere without import cycles.

The guard checks the three properties a symmetry finder needs:

* the 3x3 lattice matrix is entirely finite;
* the cell has a non-degenerate volume: ``|det(matrix)| > MIN_ABS_DETERMINANT``;
* the lattice parameters are physically positive/finite: ``a, b, c > 0`` and
  ``0 < alpha, beta, gamma < 180`` degrees.

Callers get a typed :class:`DegenerateCellError` (a ``ValueError`` subclass, so
existing ``except ValueError`` handlers keep working) carrying the concrete list
of ``violations``; the CLI catches it at the top level and prints a readable
one-line ``error: DegenerateCellError: ...`` instead of dying in native code.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

__all__ = [
    "DegenerateCellError",
    "MIN_ABS_DETERMINANT",
    "MIN_LENGTH",
    "ANGLE_EPS",
    "cell_violations",
    "assert_finite_cell",
    "guard_structure",
]

#: smallest accepted |det(lattice)| in A^3 (a smaller value is a zero/near-zero cell)
MIN_ABS_DETERMINANT = 1e-8
#: smallest accepted lattice vector length in A (must be strictly positive)
MIN_LENGTH = 1e-12
#: angular margin in degrees: angles must lie strictly inside (0, 180)
ANGLE_EPS = 1e-9

#: (vector index pair, parameter name) for the three cell angles
_ANGLE_KEYS = ((1, 2, "alpha"), (0, 2, "beta"), (0, 1, "gamma"))


class DegenerateCellError(ValueError):
    """A cell that must not be handed to a symmetry finder (spglib).

    Attributes:
        violations: human-readable list of every failed property (non-empty).
        context: optional caller label such as ``"standardize"``.
    """

    def __init__(
        self,
        message: str,
        violations: Sequence[str] = (),
        context: str | None = None,
    ) -> None:
        self.violations = [str(v) for v in violations]
        self.context = context
        super().__init__(message)


def _as_matrix(cell: Any) -> np.ndarray:
    """Coerce a ``Structure``/``Lattice``/3x3 array-like into a float matrix."""
    lattice = getattr(cell, "lattice", None)
    if lattice is not None:
        cell = lattice
    matrix = getattr(cell, "matrix", cell)
    return np.asarray(matrix, dtype=float)


def _finite_angles(lengths: Sequence[float], matrix: np.ndarray) -> dict[str, float]:
    """Cell angles in degrees, ``nan`` where they cannot be computed."""
    out: dict[str, float] = {}
    for i, j, name in _ANGLE_KEYS:
        li, lj = float(lengths[i]), float(lengths[j])
        if not (math.isfinite(li) and math.isfinite(lj) and li > MIN_LENGTH and lj > MIN_LENGTH):
            out[name] = float("nan")
            continue
        vi, vj = np.asarray(matrix[i], dtype=float), np.asarray(matrix[j], dtype=float)
        try:
            cos = float(np.dot(vi, vj) / (li * lj))
        except Exception:  # noqa: BLE001 - defensive: never let the guard itself crash
            out[name] = float("nan")
            continue
        if not math.isfinite(cos):
            out[name] = float("nan")
            continue
        out[name] = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
    return out


def cell_violations(cell: Any) -> list[str]:
    """Return every reason ``cell`` is unfit for spglib (``[]`` means safe).

    ``cell`` may be a pymatgen ``Structure``, a ``Lattice``, or any 3x3
    array-like.  The function never raises for malformed input; an unreadable
    matrix comes back as a violation instead.
    """
    try:
        matrix = _as_matrix(cell)
    except Exception as exc:  # noqa: BLE001 - the guard must not raise itself
        return [f"lattice matrix cannot be read: {type(exc).__name__}: {exc}"]

    if matrix.shape != (3, 3):
        return [f"lattice matrix must be 3x3, got shape {tuple(matrix.shape)}"]

    violations: list[str] = []

    nonfinite = [
        f"[{i}][{j}]={float(matrix[i, j])!r}"
        for i in range(3)
        for j in range(3)
        if not math.isfinite(float(matrix[i, j]))
    ]
    if nonfinite:
        violations.append("non-finite lattice matrix entries: " + ", ".join(nonfinite))

    lengths = [float(np.linalg.norm(matrix[i])) for i in range(3)]
    for name, value in zip("abc", lengths):
        if not math.isfinite(value):
            violations.append(f"lattice length {name} is not finite ({value!r})")
        elif value <= MIN_LENGTH:
            violations.append(
                f"lattice length {name}={value!r} A is not > {MIN_LENGTH:g} (zero/degenerate axis)"
            )

    angles = _finite_angles(lengths, matrix)
    for name in ("alpha", "beta", "gamma"):
        value = angles[name]
        if not math.isfinite(value):
            violations.append(f"lattice angle {name} is not finite ({value!r})")
        elif not (ANGLE_EPS < value < 180.0 - ANGLE_EPS):
            violations.append(f"lattice angle {name}={value!r} deg is outside (0, 180)")

    if np.all(np.isfinite(matrix)):
        det = float(np.linalg.det(matrix))
        if not math.isfinite(det) or abs(det) <= MIN_ABS_DETERMINANT:
            violations.append(
                f"|det(lattice)|={abs(det)!r} A^3 is not > {MIN_ABS_DETERMINANT:g} "
                "(zero/near-zero cell volume)"
            )

    return violations


def assert_finite_cell(cell: Any, *, context: str = "") -> None:
    """Raise :class:`DegenerateCellError` unless ``cell`` is safe for spglib.

    Args:
        cell: pymatgen ``Structure`` / ``Lattice`` / 3x3 array-like.
        context: caller label woven into the message (e.g. ``"standardize"``).

    Raises:
        DegenerateCellError: with every violated property in ``.violations``.
    """
    violations = cell_violations(cell)
    if not violations:
        return
    where = f"{context}: " if context else ""
    detail = "; ".join(violations)
    raise DegenerateCellError(
        f"{where}refusing to run symmetry analysis on a degenerate cell "
        f"({len(violations)} violation(s)): {detail}. "
        f"Cell parameters must be finite with a positive volume; check the CIF "
        f"cell lengths/angles before calling spglib.",
        violations=violations,
        context=context or None,
    )


def guard_structure(structure: Any, *, context: str = "") -> Any:
    """Convenience: ``assert_finite_cell`` and return ``structure`` unchanged."""
    assert_finite_cell(structure, context=context)
    return structure
