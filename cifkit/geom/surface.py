"""(hkl) 表面切面 + 终止面选择 + 真空层。

Owner: geom teammate. Public API (DESIGN.md §6, extended in §6f):

    make_slab(structure, hkl, *, slab_thickness=15.0, vacuum=15.0,
              termination=None, reps=None, frame="slab") -> tuple[Structure, dict]

Two frames
----------
``frame="slab"`` (default, physically meaningful)
    Cut the ``hkl`` surface of the **input** (standardised conventional) cell,
    then expand the slab *in plane* by ``reps[:2]``. For the demo: the 276-atom
    conventional ZIF-8 cell gives a 552-atom (111) slab; a 2x2 in-plane repeat
    gives 2208 atoms; the vacuum is then set exactly to the target.
``frame="cell"`` (literal reading, kept for comparison)
    First build the ``reps`` supercell of the input cell, then cut its ``(hkl)``.
    Note that for a 2x2x1 supercell the (111) normal is *not* the (111) normal
    of the parent crystal, so this is a different surface; it is reported as
    such.

Termination selection
---------------------
All terminations returned by :class:`~pymatgen.core.surface.SlabGenerator` are
scored; the default choice minimises

    score = dangling_bonds + 100 * stoichiometry_deviation

where ``dangling_bonds`` counts, for atoms in the two surface layers
(:data:`SURFACE_WINDOW` Å deep), the missing bonds with respect to the bulk
median coordination number of that element, and
``stoichiometry_deviation`` is the largest relative deviation of the slab's
element fractions from the bulk ones. ``termination`` may also be an integer
candidate index, a float shift value, or an element symbol (e.g. ``"Zn"``).
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import time
from collections import Counter
from typing import Any, Sequence

import numpy as np
from pymatgen.core import Structure
from pymatgen.core.surface import SlabGenerator

from cifkit.geom._common import (
    attach_geom_info,
    coordination_numbers,
    element_counts,
    median_coordination_by_element,
    site_symbols,
    vacuum_metrics,
)
from cifkit.geom.vacuum import set_vacuum

#: depth of the "surface layer" used for dangling-bond accounting (Å)
SURFACE_WINDOW = 3.0
#: refuse to cut absurdly large slabs (guards against typos)
MAX_SLAB_ATOMS = 30_000
#: score penalty for a non-stoichiometric termination (per unit of relative deviation)
STOICH_PENALTY = 100.0


# ---------------------------------------------------------------------------
def _normalize_hkl(hkl: Sequence[int]) -> tuple[int, int, int]:
    try:
        triple = tuple(int(round(float(v))) for v in hkl)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"make_slab: hkl must be three integers, got {hkl!r}") from exc
    if len(triple) != 3:
        raise ValueError(f"make_slab: hkl must have exactly three entries, got {hkl!r}")
    if all(v == 0 for v in triple):
        raise ValueError("make_slab: hkl cannot be (0, 0, 0)")
    gcd = math.gcd(math.gcd(abs(triple[0]), abs(triple[1])), abs(triple[2]))
    if gcd > 1:
        triple = tuple(v // gcd for v in triple)
    for value in triple:  # canonical sign: first non-zero entry positive
        if value != 0:
            if value < 0:
                triple = tuple(-v for v in triple)
            break
    return triple  # type: ignore[return-value]


def _normalize_reps(reps: Sequence[int] | None) -> tuple[int, int, int] | None:
    if reps is None:
        return None
    try:
        triple = tuple(int(r) for r in reps)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"make_slab: reps must be three integers, got {reps!r}") from exc
    if len(triple) != 3:
        raise ValueError(f"make_slab: reps must have exactly three entries, got {reps!r}")
    if any(r < 1 for r in triple):
        raise ValueError(f"make_slab: reps must all be >= 1, got {triple}")
    return triple  # type: ignore[return-value]


def _slab_metrics(
    slab: Structure,
    ref_cn: dict[str, float],
    bulk_counts: dict[str, int],
    n_bulk: int,
) -> dict[str, Any]:
    """Cheap descriptors of one slab termination (used for scoring)."""
    n = len(slab)
    metrics = vacuum_metrics(slab, axis=2)
    normal = np.asarray(metrics["normal"], dtype=float)
    height = np.asarray(slab.cart_coords, dtype=float) @ normal
    h_min, h_max = float(height.min()), float(height.max())
    thickness = float(metrics["thickness"])
    window = float(min(SURFACE_WINDOW, max(1.0, thickness * 0.25)))
    top_mask = height >= (h_max - window)
    bottom_mask = height <= (h_min + window)
    surface_mask = top_mask | bottom_mask

    syms = site_symbols(slab)
    cn = coordination_numbers(slab)
    counts = Counter(syms)

    dangling = 0
    per_element_missing: dict[str, int] = {}
    for i in np.nonzero(surface_mask)[0]:
        el = syms[i]
        ref = ref_cn.get(el)
        if ref is None:
            continue
        missing = max(0, int(round(ref)) - int(cn[i]))
        if missing:
            dangling += missing
            per_element_missing[el] = per_element_missing.get(el, 0) + missing

    deviation = 0.0
    for el, count in counts.items():
        expected = (bulk_counts.get(el, 0) / n_bulk) if n_bulk else 0.0
        actual = count / n
        if expected <= 0:
            deviation = max(deviation, 1.0)
        else:
            deviation = max(deviation, abs(actual - expected) / expected)

    top_counts = Counter(syms[i] for i in np.nonzero(top_mask)[0])
    bottom_counts = Counter(syms[i] for i in np.nonzero(bottom_mask)[0])
    lattice = slab.lattice
    in_plane = float(np.linalg.norm(np.cross(lattice.matrix[0], lattice.matrix[1])))

    return {
        "natoms": n,
        "formula": slab.composition.formula,
        "thickness": round(thickness, 3),
        # perpendicular vacuum layer = d_perp - thickness (standard definition)
        "vacuum_perp": round(float(metrics["vacuum_perp"]), 3),
        # kept under the old name for the candidates table in docs/report
        "vacuum_as_generated": round(float(metrics["vacuum_perp"]), 3),
        # smallest cross-boundary periodic-image distance (safe lower bound only)
        "min_image_distance": round(float(metrics["min_image_distance"]), 3),
        "frac_span": round(float(metrics["frac_span"]), 4),
        "surface_area": round(in_plane, 2),
        "surface_atoms": int(surface_mask.sum()),
        "dangling_bonds": int(dangling),
        "dangling_by_element": dict(sorted(per_element_missing.items())),
        "stoichiometry_deviation": round(float(deviation), 4),
        "surface_elements_top": dict(sorted(top_counts.items())),
        "surface_elements_bottom": dict(sorted(bottom_counts.items())),
        "score": round(float(dangling) + STOICH_PENALTY * float(deviation), 4),
    }


def _select_candidate(
    candidates: list[dict[str, Any]],
    termination: Any,
) -> tuple[dict[str, Any], str]:
    """Pick one candidate according to ``termination``; returns (candidate, mode)."""
    if not candidates:
        raise RuntimeError("make_slab: SlabGenerator produced no terminations")

    def best_of(pool: list[dict[str, Any]]) -> dict[str, Any]:
        return min(pool, key=lambda c: (c["score"], c["natoms"], c["shift"]))

    if termination is None or (isinstance(termination, str) and termination.strip().lower() in ("auto", "best", "default")):
        return best_of(candidates), "best"

    if isinstance(termination, bool):  # bool is an int subclass, reject explicitly
        raise ValueError("make_slab: termination must be None, an int, a float or an element symbol")

    if isinstance(termination, (int, np.integer)):
        index = int(termination)
        if index < 0:
            index += len(candidates)
        if not 0 <= index < len(candidates):
            raise ValueError(
                f"make_slab: termination index {termination} out of range (0..{len(candidates) - 1}, "
                f"{len(candidates)} candidates)"
            )
        return candidates[index], "index"

    if isinstance(termination, (float, np.floating)):
        shift = float(termination)
        chosen = min(candidates, key=lambda c: abs(c["shift"] - shift))
        if abs(chosen["shift"] - shift) > 1e-3:
            raise ValueError(
                f"make_slab: no termination at shift={shift}; nearest is {chosen['shift']:.4f} "
                f"(pass termination=<index> to select a candidate explicitly)"
            )
        return chosen, "shift"

    if isinstance(termination, str):
        wanted = "".join(ch for ch in termination if ch.isalpha())
        if not wanted:
            raise ValueError(f"make_slab: cannot interpret termination={termination!r}")
        pool = []
        available: set[str] = set()
        for cand in candidates:
            surface = set(cand["surface_elements_top"]) | set(cand["surface_elements_bottom"])
            available |= surface
            if wanted.lower() in {el.lower() for el in surface}:
                pool.append(cand)
        if not pool:
            raise ValueError(
                f"make_slab: no termination exposes element {termination!r}; "
                f"available surface elements: {sorted(available)}"
            )
        return best_of(pool), "element"

    raise ValueError(
        f"make_slab: unsupported termination selector {termination!r} "
        "(use None/'auto', an integer index, a float shift, or an element symbol)"
    )


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# In-process result cache
# ---------------------------------------------------------------------------
# Cutting a slab enumerates every termination and computes coordination
# numbers; for a 500+-atom conventional cell one call costs ~1-3 s.  Batch
# workflows (E_surf scans over (hkl), vacuum or termination) repeat identical
# calls, so results are memoised per process.  The key includes a hash of the
# structure and every geometry argument; values are copied on return because
# callers may mutate the slab.
_SLAB_CACHE: dict[tuple[Any, ...], tuple[Structure, dict[str, Any]]] = {}
_SLAB_CACHE_ORDER: list[tuple[Any, ...]] = []
_SLAB_CACHE_STATS = {"hits": 0, "misses": 0}
_SLAB_CACHE_MAX = 24


def _structure_digest(structure: Structure) -> str:
    """Stable digest of a structure (lattice + species + fractional coords)."""
    from pymatgen.io.cif import CifWriter

    text = str(CifWriter(structure, symprec=None))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _slab_cache_key(
    structure: Structure,
    hkl: Sequence[int],
    slab_thickness: float,
    vacuum: float,
    termination: Any,
    reps: Sequence[int] | None,
    frame: str,
) -> tuple[Any, ...]:
    return (
        _structure_digest(structure),
        _normalize_hkl(hkl),
        round(float(slab_thickness), 6),
        round(float(vacuum), 6),
        repr(termination),
        _normalize_reps(reps),
        str(frame or "slab").strip().lower(),
    )



def _remember(key: tuple[Any, ...], slab: Structure, info: dict[str, Any]) -> None:
    """Insert into the bounded in-process LRU (shared by the hit paths)."""
    if key in _SLAB_CACHE:
        with contextlib.suppress(ValueError):
            _SLAB_CACHE_ORDER.remove(key)
    elif len(_SLAB_CACHE_ORDER) >= _SLAB_CACHE_MAX:
        oldest = _SLAB_CACHE_ORDER.pop(0)
        _SLAB_CACHE.pop(oldest, None)
    _SLAB_CACHE[key] = (slab.copy(), info)
    _SLAB_CACHE_ORDER.append(key)

def slab_cache_info() -> dict[str, Any]:
    """Stats for the ``make_slab`` caches (in-process + on-disk)."""
    from cifkit.geom import disk_cache

    return {
        "disk": disk_cache.stats(),
        "size": len(_SLAB_CACHE),
        "max": _SLAB_CACHE_MAX,
        "hits": int(_SLAB_CACHE_STATS["hits"]),
        "misses": int(_SLAB_CACHE_STATS["misses"]),
    }


def clear_slab_cache() -> None:
    """Drop cached slabs and counters (tests)."""
    _SLAB_CACHE.clear()
    _SLAB_CACHE_ORDER.clear()
    _SLAB_CACHE_STATS["hits"] = 0
    _SLAB_CACHE_STATS["misses"] = 0


def make_slab(
    structure: Structure,
    hkl: Sequence[int],
    *,
    slab_thickness: float = 15.0,
    vacuum: float = 15.0,
    termination: Any = None,
    reps: Sequence[int] | None = None,
    frame: str = "slab",
) -> tuple[Structure, dict[str, Any]]:
    """Cached wrapper around :func:`_make_slab_uncached`.

    The returned ``info`` carries ``cache="hit"`` on memoised calls; geometry
    arguments and the input structure fully determine the result.
    """
    key: tuple[Any, ...] | None = None
    try:
        key = _slab_cache_key(structure, hkl, slab_thickness, vacuum, termination, reps, frame)
    except Exception:  # noqa: BLE001 - cache is best-effort, never break geometry
        key = None
    if key is not None and key in _SLAB_CACHE:
        _SLAB_CACHE_STATS["hits"] += 1
        slab, info = _SLAB_CACHE[key]
        return slab.copy(), {**info, "cache": "hit"}

    # round 47 (G2): a second layer on disk, so separate processes in a batch do not
    # recompute identical slabs.  Failures degrade to a miss (never to an error).
    if key is not None:
        from cifkit.geom import disk_cache

        found = disk_cache.lookup(key)
        if found is not None:
            slab, info = found
            _SLAB_CACHE_STATS["hits"] += 1
            _remember(key, slab, info)
            return slab.copy(), {**info, "cache": "disk"}
    _SLAB_CACHE_STATS["misses"] += 1
    slab, info = _make_slab_uncached(
        structure,
        hkl,
        slab_thickness=slab_thickness,
        vacuum=vacuum,
        termination=termination,
        reps=reps,
        frame=frame,
    )
    if key is not None:
        _remember(key, slab, info)
        from cifkit.geom import disk_cache

        disk_cache.store(key, slab, info)
        info = {**info, "cache": "miss"}
    return slab, info


def _make_slab_uncached(
    structure: Structure,
    hkl: Sequence[int],
    *,
    slab_thickness: float = 15.0,
    vacuum: float = 15.0,
    termination: Any = None,
    reps: Sequence[int] | None = None,
    frame: str = "slab",
) -> tuple[Structure, dict[str, Any]]:
    """Cut a ``(hkl)`` slab and set an exact vacuum layer.

    Args:
        structure: periodic input structure (normally the standardised
            conventional cell).
        hkl: Miller index, e.g. ``(1, 1, 1)``.
        slab_thickness: minimum slab thickness in Å (pymatgen rounds up to whole
            layers).
        vacuum: target **perpendicular vacuum-layer thickness** in Å (standard
            surface-science definition). The smallest cross-boundary
            periodic-image distance is reported separately as
            ``info["min_image_distance"]``.
        termination: ``None``/"auto" for the automatically scored termination,
            an integer candidate index, a float shift value, or an element
            symbol that must appear on one of the two surfaces.
        reps: optional in-plane repeat (``frame="slab"``) or supercell
            (``frame="cell"``). ``reps[2]`` must be 1 for ``frame="slab"``.
        frame: ``"slab"`` (default) or ``"cell"`` -- see the module docstring.

    Returns:
        ``(slab_structure, info)``. ``info`` contains at least ``frame``,
        ``hkl``, ``reps``, ``base_atoms``, ``atoms_after_reps``,
        ``slab_thickness``, ``vacuum_measured`` (= ``vacuum_perp``),
        ``min_image_distance``, the chosen ``termination`` summary and the
        ``candidates`` list.

    Raises:
        ValueError: bad arguments, a slab that would be too large, or an
            impossible termination selector.
        RuntimeError: the slab generator returned nothing / failed.
    """
    hkl_t = _normalize_hkl(hkl)
    thickness_target = float(slab_thickness)
    vacuum_target = float(vacuum)
    if not math.isfinite(thickness_target) or thickness_target <= 0:
        raise ValueError(f"make_slab: slab_thickness must be a positive number of Å, got {slab_thickness!r}")
    if not math.isfinite(vacuum_target) or vacuum_target < 0:
        raise ValueError(f"make_slab: vacuum must be a non-negative number of Å, got {vacuum!r}")
    frame_key = str(frame or "slab").strip().lower()
    if frame_key not in ("slab", "cell"):
        raise ValueError(f"make_slab: frame must be 'slab' or 'cell', got {frame!r}")
    reps_t = _normalize_reps(reps)
    if reps_t is not None and frame_key == "slab" and reps_t[2] != 1:
        raise ValueError(
            f"make_slab: frame='slab' repeats the slab in plane only, so reps[2] must be 1, got {reps_t}"
        )
    if len(structure) == 0:
        raise ValueError("make_slab: empty structure")

    t_start = time.time()
    source = structure.copy()

    # -- frame="cell": literal `supercell then cut` semantics ----------------
    if frame_key == "cell" and reps_t is not None:
        source = source * reps_t

    generator = SlabGenerator(
        source,
        hkl_t,
        min_slab_size=thickness_target,
        min_vacuum_size=max(vacuum_target, 5.0),
        center_slab=True,
        max_normal_search=None,
        lll_reduce=True,
        primitive=False,  # pymatgen's primitive reduction explodes on 500+ atoms
        reorient_lattice=True,
    )

    # rough size guard before doing the expensive work
    proj_height = float(getattr(generator, "_proj_height", 0.0) or 0.0)
    if proj_height > 0:
        layers = math.ceil(thickness_target / proj_height)
        estimate = len(source) * max(layers, 1)
        if estimate > MAX_SLAB_ATOMS:
            raise ValueError(
                f"make_slab: a {thickness_target} Å {hkl_t} slab of a {len(source)}-atom cell would "
                f"contain about {estimate} atoms (> limit {MAX_SLAB_ATOMS}); reduce slab_thickness"
            )

    bulk_counts = element_counts(source)
    n_bulk = len(source)
    bulk_cn = coordination_numbers(source)
    ref_cn = median_coordination_by_element(source, cn=bulk_cn)

    # -- enumerate / score every termination --------------------------------
    shifts: list[float] | None = None
    if hasattr(generator, "gen_possible_terminations"):
        try:
            shifts = [float(x) for x in generator.gen_possible_terminations(ftol=0.1)]
        except TypeError:  # pragma: no cover - older pymatgen signature
            shifts = [float(x) for x in generator.gen_possible_terminations()]
        except Exception:  # noqa: BLE001 - fall back to get_slabs() below
            shifts = None

    candidates: list[dict[str, Any]] = []
    if shifts:
        for shift in shifts:
            slab = generator.get_slab(shift=shift)
            cand = _slab_metrics(slab, ref_cn, bulk_counts, n_bulk)
            cand["shift"] = round(float(shift), 6)
            candidates.append(cand)
            del slab
    else:  # pragma: no cover - fallback path
        slabs = generator.get_slabs(filter_out_sym_slabs=False)
        for slab in slabs:
            cand = _slab_metrics(slab, ref_cn, bulk_counts, n_bulk)
            cand["shift"] = round(float(getattr(slab, "shift", 0.0)), 6)
            candidates.append(cand)
        del slabs

    chosen_cand, mode = _select_candidate(candidates, termination)

    # regenerate just the chosen slab (keeps peak memory low)
    chosen_slab: Structure = generator.get_slab(shift=float(chosen_cand["shift"]))
    base_atoms = len(chosen_slab)

    # -- repeat in plane (frame="slab") -------------------------------------
    if frame_key == "slab" and reps_t is not None:
        in_plane = (reps_t[0], reps_t[1], 1)
        expanded = chosen_slab * in_plane
        used_reps = list(reps_t)
    else:
        expanded = chosen_slab
        used_reps = list(reps_t) if reps_t is not None else None

    if len(expanded) > MAX_SLAB_ATOMS:
        raise ValueError(
            f"make_slab: repeated slab would contain {len(expanded)} atoms (> limit {MAX_SLAB_ATOMS})"
        )

    # -- exact vacuum -------------------------------------------------------
    # `vacuum_as_generated` is the perpendicular gap of the raw SlabGenerator
    # output, i.e. only a lower bound (SlabGenerator guarantees >= min_vacuum_size).
    vacuum_as_generated = float(chosen_cand["vacuum_perp"])
    min_image_as_generated = float(chosen_cand["min_image_distance"])
    final, measured = set_vacuum(expanded, vacuum_target, axis=2)
    final_metrics = vacuum_metrics(final, axis=2)
    lattice = final.lattice

    termination_summary = {
        "mode": mode,
        "shift": chosen_cand["shift"],
        "surface_elements_top": chosen_cand["surface_elements_top"],
        "surface_elements_bottom": chosen_cand["surface_elements_bottom"],
        "dangling_bonds": chosen_cand["dangling_bonds"],
        "dangling_by_element": chosen_cand["dangling_by_element"],
        "stoichiometry_deviation": chosen_cand["stoichiometry_deviation"],
        "score": chosen_cand["score"],
    }
    info: dict[str, Any] = {
        "frame": frame_key,
        "hkl": list(hkl_t),
        "reps": tuple(used_reps) if used_reps is not None else None,
        "in_plane_reps": (reps_t[0], reps_t[1]) if (frame_key == "slab" and reps_t is not None) else None,
        "input_atoms": len(structure),
        "cut_cell_atoms": len(source),
        "base_atoms": int(base_atoms),
        "atoms_after_reps": int(len(expanded)),
        "natoms": int(len(final)),
        "formula": final.composition.formula,
        "reduced_formula": final.composition.reduced_formula,
        "slab_thickness": round(float(final_metrics["thickness"]), 3),
        "atom_extent": round(float(final_metrics["thickness"]), 3),
        # primary reported vacuum = perpendicular vacuum layer thickness
        "vacuum_measured": round(float(measured), 4),
        "vacuum_perp": round(float(measured), 4),
        "vacuum": round(float(measured), 4),  # legacy key used by pipeline/report
        "vacuum_target": vacuum_target,
        # smallest atom <-> periodic-image distance across the boundary (safe
        # lower bound, typically slightly larger than vacuum_perp)
        "min_image_distance": round(float(final_metrics["min_image_distance"]), 4),
        "vacuum_as_generated": round(vacuum_as_generated, 3),
        "min_image_distance_as_generated": round(min_image_as_generated, 3),
        "slab_thickness_target": thickness_target,
        "c_length": round(float(lattice.abc[2]), 3),
        "lattice": {
            "abc": [round(float(x), 4) for x in lattice.abc],
            "angles": [round(float(x), 3) for x in lattice.angles],
            "volume": round(float(final.volume), 3),
        },
        "surface_area": round(float(np.linalg.norm(np.cross(lattice.matrix[0], lattice.matrix[1]))), 2),
        "termination": termination_summary,
        "chosen": dict(chosen_cand),
        "n_candidates": len(candidates),
        "candidates": candidates,
        "generator": {
            "min_slab_size": thickness_target,
            "min_vacuum_size": max(vacuum_target, 5.0),
            "center_slab": True,
            "lll_reduce": True,
            "primitive": False,
            "max_normal_search": None,
            "n_terminations": len(candidates),
        },
        "elapsed_s": round(time.time() - t_start, 2),
    }
    return attach_geom_info(final, info), info
