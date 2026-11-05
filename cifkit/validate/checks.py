"""结构校验：组成、近邻距离、配位/悬空键、真空层、电荷等。

Owner: geom teammate. Public API (DESIGN.md §6):

    validate_structure(structure, *, spec=None, extra=None) -> ValidationReport

Check names are part of the report contract (``report.md`` references them) and
must stay stable:

======================  ==========  ==========================================
name                    severity    meaning
======================  ==========  ==========================================
``natoms``              error       structure is not empty
``composition``         error       formula / element counts readable
``lattice``             error       finite, positive cell parameters and volume
``finite_coordinates``  error       all coordinates are finite numbers
``duplicate_atoms``     error       no two atoms closer than 0.4 Å
``min_distance``        error       shortest interatomic distance >= 0.5 Å
``vacuum``              error/info  slab vacuum layer (perpendicular, >= spec.vacuum when given)
``slab_continuity``     warning     the slab region is one continuous block
``dangling_bonds``      warning     under-coordinated surface atoms (counts)
``hydrogen``            error/info  H present when ``spec.repair_h`` was requested
``carbon_coordination`` error/warn  no C with < 3 bonds in the structure interior
``charge``              info        charge heuristic (only when oxidation states exist)
======================  ==========  ==========================================

``report.ok`` only looks at ``error`` checks; warnings are reported but do not
fail the run.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
from pymatgen.core import Structure

from cifkit.geom._common import (
    along_normal,
    coordination_numbers,
    element_counts,
    gaps_all_axes,
    median_coordination_by_element,
    site_symbols,
    vacuum_metrics,
)
from cifkit.types import ValidationReport

#: two atoms closer than this are considered duplicates/overlapping (Å)
DUPLICATE_TOL = 0.4
#: shortest acceptable interatomic distance (Å) - below that: error
MIN_DISTANCE_TOL = 0.5
#: distances below this are reported as suspicious even if accepted (Å)
SUSPICIOUS_DISTANCE = 0.9
#: vacuum gap above which a structure is considered slab-like (Å)
SLAB_GAP = 6.0
#: surface-layer depth used for dangling-bond accounting (Å)
SURFACE_WINDOW = 3.0
#: neighbour search radius for distance statistics (Å)
NEIGHBOR_RADIUS = 5.0

CHECK_NAMES = (
    "natoms",
    "composition",
    "lattice",
    "finite_coordinates",
    "duplicate_atoms",
    "min_distance",
    "vacuum",
    "slab_continuity",
    "dangling_bonds",
    "hydrogen",
    "carbon_coordination",
    "charge",
)


# ---------------------------------------------------------------------------
def _neighbor_statistics(structure: Structure) -> dict[str, Any]:
    """Min distances (global + per element pair) and duplicate pairs in one pass."""
    syms = site_symbols(structure)
    n = len(structure)
    min_distance = math.inf
    min_pair: tuple[str, str] | None = None
    min_pair_sites: tuple[int, int] | None = None
    by_pair: dict[str, float] = {}
    duplicates: list[tuple[int, int, float]] = []
    try:
        neighbours = structure.get_all_neighbors(NEIGHBOR_RADIUS)
    except Exception:  # noqa: BLE001 - fall back to the distance matrix
        neighbours = None
    if neighbours is None:
        dm = np.asarray(structure.distance_matrix, dtype=float)
        np.fill_diagonal(dm, np.inf)
        min_distance = float(dm.min()) if n > 1 else math.inf
        idx = np.unravel_index(np.argmin(dm), dm.shape)
        min_pair = tuple(sorted((syms[idx[0]], syms[idx[1]])))
        min_pair_sites = (int(idx[0]), int(idx[1]))
        threshold = DUPLICATE_TOL
        for i in range(n):
            for j in range(i + 1, n):
                if dm[i, j] < threshold:
                    duplicates.append((i, j, float(dm[i, j])))
        return {
            "min_distance": min_distance,
            "min_distance_pair": min_pair,
            "min_distance_sites": min_pair_sites,
            "min_distance_by_element_pair": {},
            "duplicates": duplicates,
        }
    seen_pairs: set[tuple[int, int]] = set()
    for i, nbs in enumerate(neighbours):
        si = syms[i]
        for nb in nbs:
            j = int(nb.index)
            d = float(nb.nn_distance)
            if j == i and d < 1e-6:  # self image of a tiny cell
                continue
            if d < min_distance:
                min_distance = d
                min_pair = tuple(sorted((si, str(getattr(nb, "species_string", si)))))
                min_pair_sites = (int(i), j)
            pair_key = "-".join(sorted((si, "".join(ch for ch in str(getattr(nb, "species_string", si)) if ch.isalpha()))))
            prev = by_pair.get(pair_key)
            if prev is None or d < prev:
                by_pair[pair_key] = d
            if i < j and d < DUPLICATE_TOL:
                key = (i, j)
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    duplicates.append((i, j, d))
    if min_pair is not None and min_pair_sites is not None:
        # normalise the element strings
        min_pair = (
            "".join(ch for ch in min_pair[0] if ch.isalpha()),
            "".join(ch for ch in min_pair[1] if ch.isalpha()),
        )
    return {
        "min_distance": min_distance,
        "min_distance_pair": min_pair,
        "min_distance_sites": min_pair_sites,
        "min_distance_by_element_pair": dict(sorted(by_pair.items())),
        "duplicates": duplicates,
    }


def _surface_mask(structure: Structure) -> tuple[np.ndarray, dict[str, Any]]:
    """Mask of atoms in the top/bottom surface layers (slab geometry)."""
    metrics = vacuum_metrics(structure, axis=2)
    normal, _d_perp, height = along_normal(structure, axis=2)
    h_min, h_max = float(height.min()), float(height.max())
    thickness = float(metrics["thickness"])
    window = float(min(SURFACE_WINDOW, max(1.0, thickness * 0.25)))
    mask = (height >= h_max - window) | (height <= h_min + window)
    return mask, {"thickness": thickness, "window": window, "normal": normal, "height": height}


def _internal_max_gap(height: np.ndarray) -> float:
    """Largest empty interval between consecutive atoms along the surface normal."""
    values = np.sort(np.asarray(height, dtype=float))
    if len(values) < 2:
        return 0.0
    return float(np.diff(values).max())


def _carbon_valence(
    structure: Structure,
    cn: np.ndarray,
    interior: np.ndarray,
) -> dict[str, Any]:
    syms = site_symbols(structure)
    c_indices = [i for i, s in enumerate(syms) if s == "C"]
    total = len(c_indices)
    interior_c = [i for i in c_indices if bool(interior[i])]
    histogram = Counter(int(cn[i]) for i in interior_c)
    under = [i for i in interior_c if int(cn[i]) < 3]
    return {
        "carbon_atoms": total,
        "carbon_interior": len(interior_c),
        "c_coordination": {int(k): int(v) for k, v in sorted(histogram.items())},
        "c_missing_h": len(under),
        "c_missing_h_indices": [int(i) for i in under[:50]],
    }


# ---------------------------------------------------------------------------
def validate_structure(structure: Structure, *, spec=None, extra: dict | None = None) -> ValidationReport:
    """Validate a structure and return a :class:`~cifkit.types.ValidationReport`.

    Args:
        structure: structure to check (bulk, slab or cluster-in-a-box).
        spec: optional :class:`~cifkit.types.TaskSpec`; ``spec.vacuum`` turns the
            vacuum check into a hard requirement, ``spec.repair_h`` turns the
            hydrogen/carbon checks into hard requirements.
        extra: optional dict merged into ``report.metrics["extra"]``.

    Returns:
        ``ValidationReport`` with stable ``checks`` (see module docstring) and
        measured ``metrics``; ``report.ok`` only considers ``error`` checks.
    """
    if structure is None:
        raise ValueError("validate_structure: structure is None")
    report = ValidationReport()
    metrics: dict[str, Any] = {}
    n = len(structure)

    # -- natoms ------------------------------------------------------------
    report.add("natoms", n > 0, detail=f"{n} atoms", severity="error")
    metrics["natoms"] = int(n)
    if n == 0:
        metrics["formula"] = ""
        report.metrics = metrics
        return report

    # -- composition -------------------------------------------------------
    try:
        formula = structure.composition.formula
        reduced = structure.composition.reduced_formula
        counts = element_counts(structure)
        comp_ok = True
        comp_detail = f"{formula} ({n} atoms; {len(counts)} elements)"
    except Exception as exc:  # noqa: BLE001
        formula, reduced, counts = "", "", {}
        comp_ok = False
        comp_detail = f"cannot read composition: {type(exc).__name__}: {exc}"
    report.add("composition", comp_ok, detail=comp_detail, severity="error")
    metrics.update(
        {
            "formula": formula,
            "reduced_formula": reduced,
            "element_counts": dict(sorted(counts.items())),
            "elements": sorted(counts),
        }
    )

    # -- finite coordinates ------------------------------------------------
    frac = np.asarray(structure.frac_coords, dtype=float)
    cart = np.asarray(structure.cart_coords, dtype=float)
    matrix = np.asarray(structure.lattice.matrix, dtype=float)
    finite = bool(np.all(np.isfinite(frac)) and np.all(np.isfinite(cart)) and np.all(np.isfinite(matrix)))
    bad_sites = 0 if finite else int(np.sum(~np.all(np.isfinite(frac), axis=1)))
    report.add(
        "finite_coordinates",
        finite,
        detail="all coordinates finite" if finite else f"{bad_sites} site(s) with non-finite coordinates",
        severity="error",
    )

    # -- lattice -----------------------------------------------------------
    abc = [float(x) for x in structure.lattice.abc]
    angles = [float(x) for x in structure.lattice.angles]
    volume = float(structure.volume)
    lattice_ok = (
        finite
        and all(math.isfinite(v) and v > 0.1 for v in abc)
        and all(math.isfinite(v) and 1.0 < v < 179.0 for v in angles)
        and math.isfinite(volume)
        and volume > 0.0
    )
    report.add(
        "lattice",
        lattice_ok,
        detail=(
            f"a,b,c = {abc[0]:.4f}, {abc[1]:.4f}, {abc[2]:.4f} Å; "
            f"alpha,beta,gamma = {angles[0]:.2f}, {angles[1]:.2f}, {angles[2]:.2f} deg; V = {volume:.3f} Å^3"
        ),
        severity="error",
    )
    metrics["lattice"] = {
        "abc": [round(v, 4) for v in abc],
        "angles": [round(v, 3) for v in angles],
        "volume": round(volume, 3),
        "volume_per_atom": round(volume / n, 4) if n else 0.0,
    }
    try:
        metrics["density_g_cm3"] = round(float(structure.density), 4)
    except Exception:  # noqa: BLE001
        pass

    # -- distances / duplicates -------------------------------------------
    stats = _neighbor_statistics(structure)
    min_distance = stats["min_distance"]
    duplicates = stats["duplicates"]
    report.add(
        "duplicate_atoms",
        len(duplicates) == 0,
        detail=(
            "no atom pair closer than 0.4 Å"
            if not duplicates
            else f"{len(duplicates)} pair(s) closer than {DUPLICATE_TOL} Å, "
            f"shortest {min(d for _, _, d in duplicates):.3f} Å"
        ),
        severity="error",
    )
    metrics["duplicate_pairs"] = len(duplicates)
    if duplicates:
        metrics["duplicate_examples"] = [
            {"i": int(i), "j": int(j), "distance": round(float(d), 4)} for i, j, d in duplicates[:10]
        ]

    if math.isfinite(min_distance):
        min_ok = min_distance >= MIN_DISTANCE_TOL
        if min_distance < SUSPICIOUS_DISTANCE:
            distance_detail = (
                f"shortest interatomic distance {min_distance:.3f} Å "
                f"({'-'.join(stats['min_distance_pair'] or ('?', '?'))})"
            )
            if min_ok:
                distance_detail += " - short, check the structure"
        else:
            distance_detail = (
                f"shortest interatomic distance {min_distance:.3f} Å "
                f"({'-'.join(stats['min_distance_pair'] or ('?', '?'))})"
            )
        metrics["min_distance"] = round(float(min_distance), 4)
        metrics["min_distance_pair"] = list(stats["min_distance_pair"]) if stats["min_distance_pair"] else None
        if stats["min_distance_sites"] is not None:
            metrics["min_distance_sites"] = [int(stats["min_distance_sites"][0]), int(stats["min_distance_sites"][1])]
    else:
        min_ok = True
        distance_detail = f"no atom pair within {NEIGHBOR_RADIUS} Å (isolated atoms / very sparse cluster)"
        metrics["min_distance"] = None
        metrics["min_distance_pair"] = None
    metrics["min_distance_by_element_pair"] = {
        k: round(float(v), 4) for k, v in stats["min_distance_by_element_pair"].items()
    }
    report.add("min_distance", min_ok, detail=distance_detail, severity="error")

    # -- geometry class: slab / cluster / bulk ----------------------------
    gaps = gaps_all_axes(structure)
    metrics["vacuum_gaps_all_axes"] = [round(float(g), 4) if math.isfinite(g) else None for g in gaps]
    cluster_like = all(math.isfinite(g) and g > SLAB_GAP for g in gaps)
    slab_like = False
    if not cluster_like:
        try:
            slab_like = bool(vacuum_metrics(structure, axis=2)["vacuum"] > SLAB_GAP)
        except Exception:  # noqa: BLE001
            slab_like = False
    metrics["is_slab"] = bool(slab_like)
    metrics["is_cluster"] = bool(cluster_like)

    target_vacuum = getattr(spec, "vacuum", None) if spec is not None else None
    interior = np.ones(n, dtype=bool)
    if slab_like:
        surface_mask, slab_geom = _surface_mask(structure)
        interior = ~surface_mask
        m = vacuum_metrics(structure, axis=2)
        # main reported quantity: perpendicular vacuum-layer thickness
        measured = float(m["vacuum_perp"])
        min_image = float(m["min_image_distance"])
        metrics["vacuum_measured"] = round(measured, 4)
        metrics["vacuum_perp"] = round(measured, 4)
        metrics["vacuum"] = round(measured, 4)
        metrics["min_image_distance"] = round(min_image, 4)
        metrics["slab_thickness"] = round(float(m["thickness"]), 3)
        metrics["slab_frac_span"] = round(float(m["frac_span"]), 4)
        try:
            metrics["surface_area"] = round(
                float(np.linalg.norm(np.cross(structure.lattice.matrix[0], structure.lattice.matrix[1]))), 3
            )
        except Exception:  # noqa: BLE001
            pass
        metrics["surface_atoms"] = int(surface_mask.sum())
        if target_vacuum is not None:
            target = float(target_vacuum)
            metrics["vacuum_target"] = target
            vacuum_ok = measured + 0.01 >= target
            vacuum_detail = (
                f"真空层（垂直）= {measured:.3f} Å；最小周期像距离 = {min_image:.3f} Å；"
                f"要求 ≥ {target:.2f} Å"
            )
            severity = "error"
        else:
            vacuum_ok = measured > 0.0
            vacuum_detail = (
                f"真空层（垂直）= {measured:.3f} Å；最小周期像距离 = {min_image:.3f} Å（未给目标值）"
            )
            severity = "info"
        report.add("vacuum", vacuum_ok, detail=vacuum_detail, severity=severity)

        # slab continuity: no internal gap comparable to the vacuum gap
        internal_gap = _internal_max_gap(slab_geom["height"])
        continuity_ok = internal_gap < measured + 1e-6
        report.add(
            "slab_continuity",
            continuity_ok,
            detail=(
                f"largest internal gap along the surface normal is {internal_gap:.2f} Å "
                f"(vacuum layer {measured:.2f} Å, slab thickness {m['thickness']:.2f} Å)"
            ),
            severity="warning",
        )
        metrics["internal_max_gap"] = round(internal_gap, 3)

        # dangling bonds on the two surfaces
        cn = coordination_numbers(structure)
        syms = site_symbols(structure)
        ref_cn = median_coordination_by_element(structure, cn=cn, mask=interior)
        dangling = 0
        dangling_by_element: dict[str, int] = {}
        for i in np.nonzero(surface_mask)[0]:
            el = syms[i]
            ref = ref_cn.get(el)
            if ref is None:
                continue
            missing = max(0, int(round(ref)) - int(cn[i]))
            if missing:
                dangling += missing
                dangling_by_element[el] = dangling_by_element.get(el, 0) + missing
        metrics["dangling_bonds"] = int(dangling)
        metrics["dangling_by_element"] = dict(sorted(dangling_by_element.items()))
        report.add(
            "dangling_bonds",
            dangling == 0,
            detail=(
                "no under-coordinated surface atoms"
                if dangling == 0
                else f"{dangling} dangling bond(s) on {int(surface_mask.sum())} surface atoms: "
                + ", ".join(f"{el}:{cnt}" for el, cnt in sorted(dangling_by_element.items()))
            ),
            severity="warning",
        )
    else:
        if cluster_like:
            metrics["cluster_padding"] = round(float(min(gaps)), 4)
        cn = coordination_numbers(structure)

    # -- hydrogen / carbon valence (always measured, enforced for repair_h) --
    counts = metrics.get("element_counts", {})
    h_count = int(counts.get("H", 0))
    metrics["h_count"] = h_count
    repair_h = bool(getattr(spec, "repair_h", False)) if spec is not None else False
    valence = _carbon_valence(structure, cn, interior)
    metrics.update(valence)
    c_ok = valence["c_missing_h"] == 0
    c_detail = (
        f"all {valence['carbon_interior']} interior C atoms have >= 3 bonds"
        if c_ok
        else f"{valence['c_missing_h']} interior C atom(s) with < 3 bonds (missing H?)"
    )
    if not repair_h:
        report.add("hydrogen", True, detail=f"{h_count} H atoms (repair_h not requested)", severity="info")
    elif h_count > 0:
        report.add("hydrogen", True, detail=f"{h_count} H atoms", severity="info")
    elif valence["carbon_interior"] > 0 and valence["c_missing_h"] > 0:
        # a genuinely under-hydrogenated organic framework: repair failed
        report.add(
            "hydrogen",
            False,
            detail=(
                f"no H atoms and {valence['c_missing_h']} interior C atom(s) with missing H "
                "(repair_h was requested)"
            ),
            severity="error",
        )
    else:
        # inorganic / already-computation-ready structure: H completion is a legitimate no-op
        report.add(
            "hydrogen",
            True,
            detail="0 H atoms, but no organic H sites need completion (inorganic/computation-ready; repair was a no-op)",
            severity="info",
        )

    if repair_h:
        report.add("carbon_coordination", c_ok, detail=c_detail, severity="error")
    else:
        report.add("carbon_coordination", c_ok, detail=c_detail + " (repair_h not requested)", severity="warning")

    # -- charge heuristic --------------------------------------------------
    charge_sum = 0.0
    has_oxi = False
    for site in structure:
        for specie, occupancy in site.species.items():
            oxi_state = getattr(specie, "oxi_state", None)
            if oxi_state is not None:
                has_oxi = True
                charge_sum += float(oxi_state) * float(occupancy)
    if has_oxi:
        charge_sum = round(charge_sum, 4)
        metrics["charge_sum"] = charge_sum
        report.add(
            "charge",
            abs(charge_sum) < 1e-6,
            detail=f"sum of oxidation states = {charge_sum:+.3f}",
            severity="info",
        )
    else:
        metrics["charge_sum"] = None
        report.add("charge", True, detail="no oxidation states in the structure (charge not assessed)", severity="info")

    if extra:
        metrics["extra"] = extra
    report.metrics = metrics
    return report
