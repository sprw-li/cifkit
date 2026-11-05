"""标准化：原胞 <-> 常规胞，去重复位点。

Owner: geom teammate. Public API (DESIGN.md §6):

    standardize(structure, *, target="conventional") -> Structure

Design notes
------------
* ``conventional`` is what the demo wants: the CoRE ASR ``sod`` ZIF-8 file is the
  rhombohedral **primitive** cell (138 atoms, a=14.669 Å) and must become the
  cubic conventional cell (276 atoms, a≈16.94 Å, I-43m).
* A structure that already is a conventional cell (e.g. the H-free raw ZIF-8,
  156 atoms, I-43m, a=17.029 Å) must be left essentially untouched.
* **Primitive-multiple guard**: if the input is already an integer (>=2x) cell of
  its own primitive cell, it is treated as "already conventional" and returned
  unchanged. Without this guard the *repaired* ZIF-8 conventional cell (276 atoms,
  H added) is detected as Fmm2 by spglib and its conventional setting has 552
  atoms -- exactly the "cell doubles after repair" bug reported by the Lead.
* Structures with no exploitable symmetry (P1) are a safe no-op.
* Any surprising result from pymatgen (atom count exploding, composition ratio
  changing, volume per atom drifting) is rejected and the input is returned
  unchanged -- we never silently hand a doubled/incorrect cell downstream.
* The reason/decision is recorded in ``structure._cifkit_geom_info``
  (``kept`` = ``"standardized"`` or ``"input"``, plus ``note``/``reason``).
"""
from __future__ import annotations

from typing import Any

import numpy as np
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from cifkit.geom._common import attach_geom_info, dedupe_sites, element_counts

#: allowed integer atomic-number scaling between input and output cells
_ALLOWED_SCALE = (1, 2, 3, 4)
#: allowed drift of volume-per-atom (relative)
_VPA_TOL = 0.03
#: symmetry tolerance used by pymatgen (Å)
SYMPREC = 0.01


def _scaling_ratio(src: Structure, out: Structure) -> float | None:
    """Common integer scaling factor of the element counts, ``None`` if not uniform."""
    src_counts = element_counts(src)
    out_counts = element_counts(out)
    if set(src_counts) != set(out_counts):
        return None
    ratios = []
    for el, n_in in src_counts.items():
        n_out = out_counts[el]
        if n_in <= 0 or n_out <= 0:
            return None
        ratios.append(n_out / n_in)
    if not ratios:
        return None
    mean = float(np.mean(ratios))
    if mean <= 0:
        return None
    if max(abs(r - mean) for r in ratios) > 1e-3 * max(mean, 1.0):
        return None
    return mean


def _scale_is_allowed(ratio: float, target: str) -> bool:
    """``conventional`` may multiply (x1..x4), ``primitive`` may divide (x1, x/2, x/3, x/4)."""
    if abs(ratio - 1.0) < 1e-3:
        return True
    if target == "conventional":
        return any(abs(ratio - n) < 1e-3 * max(1.0, ratio) for n in _ALLOWED_SCALE)
    return any(abs(ratio - 1.0 / n) < 1e-3 * max(1.0, ratio) for n in _ALLOWED_SCALE)


def _acceptable(src: Structure, out: Structure, target: str) -> tuple[bool, str]:
    """Sanity gate for a symmetry-derived cell."""
    if len(out) == 0:
        return False, "empty result"
    if len(out) != len(src):
        ratio = _scaling_ratio(src, out)
        if ratio is None:
            return False, "element-count ratios are not a uniform scaling"
        if not _scale_is_allowed(ratio, target):
            return False, f"atom count scaling x{ratio:g} is not allowed for target={target!r}"
    vpa_in = src.volume / len(src)
    vpa_out = out.volume / len(out)
    if vpa_in <= 0 or vpa_out <= 0:
        return False, "non-positive volume"
    if abs(vpa_out - vpa_in) / vpa_in > _VPA_TOL:
        return False, f"volume-per-atom drift {vpa_in:.3f} -> {vpa_out:.3f} Å^3"
    abc = np.asarray(out.lattice.abc, dtype=float)
    angles = np.asarray(out.lattice.angles, dtype=float)
    if not np.all(np.isfinite(abc)) or not np.all(np.isfinite(angles)):
        return False, "non-finite lattice parameters"
    if np.any(abc <= 0.1) or np.any(abc > 500.0):
        return False, f"implausible lattice lengths {abc}"
    if np.any(angles <= 1.0) or np.any(angles >= 179.0):
        return False, f"implausible lattice angles {angles}"
    return True, "ok"


def standardize(structure: Structure, *, target: str = "conventional") -> Structure:
    """Return a standardised cell of ``structure``.

    Args:
        structure: input structure (primitive or conventional or anything else).
        target: ``"conventional"`` (default) or ``"primitive"``.

    Returns:
        A new :class:`~pymatgen.core.Structure`. The input object is never
        mutated. When symmetry cannot be exploited (P1) or the symmetry-derived
        cell fails the sanity gate, an unchanged copy is returned and the reason
        is recorded on ``structure._cifkit_geom_info``.

    Raises:
        ValueError: unknown ``target`` or an empty structure.
    """
    if len(structure) == 0:
        raise ValueError("standardize: empty structure")
    key = str(target or "conventional").strip().lower()
    if key in ("conv", "conventional", "standard"):
        target = "conventional"
    elif key in ("prim", "primitive"):
        target = "primitive"
    else:
        raise ValueError(f"standardize: target must be 'conventional' or 'primitive', got {target!r}")

    src = structure.copy()
    info: dict[str, Any] = {
        "function": "standardize",
        "target": target,
        "natoms_in": len(src),
        "lattice_in": list(np.round(src.lattice.abc, 4)),
    }
    try:
        sga = SpacegroupAnalyzer(src, symprec=SYMPREC)
        symbol = sga.get_space_group_symbol()
        number = sga.get_space_group_number()
    except Exception as exc:  # noqa: BLE001 - symmetry finder can fail on odd cells
        info.update({"kept": "input", "reason": f"symmetry analysis failed: {type(exc).__name__}: {exc}"})
        return attach_geom_info(src, info)

    info["spacegroup_in"] = {"symbol": symbol, "number": number}

    if symbol == "P1":
        info.update({"kept": "input", "reason": "P1 structure: nothing to standardise", "note": "symmetry kept as input"})
        return attach_geom_info(src, info)

    # A cell that is an integer (>=2x) multiple of the primitive cell is already a
    # conventional (or super-) cell. Re-deriving a "conventional" cell for such an
    # input is dangerous: e.g. the repaired ZIF-8 conventional cell (276 atoms) is
    # detected as Fmm2 by spglib and its conventional setting has 552 atoms. Keep
    # the input cell instead -- this is the "do not double the cell" guard.
    if target == "conventional":
        prim = None
        try:
            prim = sga.get_primitive_standard_structure()
        except Exception:  # noqa: BLE001
            prim = None
        if prim is not None and len(prim) > 0:
            ratio = len(src) / len(prim)
            rounded = round(ratio)
            if rounded >= 2 and abs(ratio - rounded) < 1e-6:
                info.update(
                    {
                        "kept": "input",
                        "note": "symmetry kept as input",
                        "primitive_atoms": len(prim),
                        "reason": (
                            f"input is already a {rounded}x cell of the {len(prim)}-atom primitive cell "
                            f"({len(src)} atoms); keeping the input setting instead of re-standardising "
                            f"to a different conventional cell"
                        ),
                    }
                )
                return attach_geom_info(src, info)

    try:
        if target == "conventional":
            out = sga.get_conventional_standard_structure()
        else:
            out = sga.get_primitive_standard_structure()
    except Exception as exc:  # noqa: BLE001
        info.update({"kept": "input", "reason": f"{type(exc).__name__}: {exc}"})
        return attach_geom_info(src, info)

    ok, reason = _acceptable(src, out, target)
    if not ok:
        info.update({"kept": "input", "reason": f"rejected symmetry cell: {reason}", "note": "symmetry kept as input"})
        return attach_geom_info(src, info)

    out, removed = dedupe_sites(out, tol=0.05)
    note = ""
    if removed:
        note = f"; removed {removed} duplicate site(s)"
    try:
        out_sga = SpacegroupAnalyzer(out, symprec=SYMPREC)
        out_symbol = out_sga.get_space_group_symbol()
    except Exception:  # noqa: BLE001
        out_symbol = None

    info.update(
        {
            "kept": "standardized",
            "natoms_out": len(out),
            "lattice_out": list(np.round(out.lattice.abc, 4)),
            "angles_out": list(np.round(out.lattice.angles, 3)),
            "removed_duplicates": int(removed),
            "spacegroup_out": out_symbol,
            "note": (
                f"symmetry kept as input{note}"
                if len(out) == len(src) and removed == 0
                else f"standardized{note}"
            ),
        }
    )
    return attach_geom_info(out, info)
