"""Independent LJ reference evaluator (round 57, "perfect even if complex").

Our LAMMPS input uses ``pair_style lj/cut`` with explicit ``(epsilon, sigma, cutoff)``.
That means the energy LAMMPS reports is *checkable*: the same sum can be evaluated
here, independently of LAMMPS, from the exported coordinates.

Why this matters: everything verified so far was "the file parses" or "the code ran".
This compares a **number computed by LAMMPS** with a **number computed by us** from the
same data file.  If they agree, the input drives the physics the parameters describe.

Conventions (must match LAMMPS ``lj/cut`` defaults):

* ``E_ij = 4 * eps * ((sigma/r)^12 - (sigma/r)^6)`` for ``r < cutoff``;
* **no** energy shift at the cutoff (LAMMPS's default ``lj/cut`` does not shift);
* periodic images are included, **including an atom's images of itself**, and every
  *unordered* pair is counted once::

      E = sum_{i<j} sum_m v(|r_i - r_j + m L|) + (natoms / 2) * sum_{m != 0} v(|m L|)

  The self-image term is not optional: with these parameters a single C atom in a
  6 A cubic cell has ``E = -4.9758e-3 eV`` (its own images at 6 A and 8.49 A).  This
  is the convention ASE's neighbor list implements (``self_interaction=False`` still
  returns the periodic self images) and the one LAMMPS's ghost-atom half pair lists
  implement.  Omitting it makes the reference *not* the periodic lattice sum.
* the image set is **exhaustive** for the cutoff.  A shift can only contribute when
  ``|shift| < cutoff + max_pair_separation``, so that is the bound used; the integer
  range follows from the interplanar spacings.  (The earlier ``cutoff + max(|a_i|)``
  filter dropped the body-diagonal shift of a cubic cell - for hkust1 that is a
  +1.6e-3 eV error and for mof5 +2.6e-2 eV, both invisible at the old ``rtol=1e-5``
  gate, which is exactly why the gate could not have caught a broken enumerator.)
* LAMMPS mixes nothing when ``pair_coeff * * eps sigma`` gives the same pair values for
  every type pair, which is what our generated input does.
"""
from __future__ import annotations

import itertools
import math

import numpy as np


def _max_pair_separation(cart: np.ndarray) -> float:
    """Largest separation between two atoms as written in the cell.

    Upper bound for how far a lattice shift has to reach to matter; using the
    *actual* structure (rather than the cell diagonal) keeps the shift loop small.
    """
    if len(cart) < 2:
        return 0.0
    diff = cart[:, None, :] - cart[None, :, :]
    return float(np.sqrt((diff ** 2).sum(-1)).max())


def _image_shifts(lattice: np.ndarray, cutoff: float, max_separation: float) -> list[np.ndarray]:
    """Every integer cell shift ``s`` with ``|s| < cutoff + max_separation``.

    Exact: any shift at or beyond that reach cannot bring an atom pair inside the
    cutoff, so the returned set is sufficient (and every entry is checked).
    """
    reach = cutoff + max_separation
    inverse = np.linalg.inv(lattice)
    spacings = 1.0 / np.linalg.norm(inverse, axis=0)
    counts = [int(math.ceil(reach / spacing)) for spacing in spacings]
    shifts: list[np.ndarray] = []
    for i, j, k in itertools.product(range(-counts[0], counts[0] + 1),
                                     range(-counts[1], counts[1] + 1),
                                     range(-counts[2], counts[2] + 1)):
        if i == 0 and j == 0 and k == 0:
            continue
        shift = np.array([i, j, k], dtype=float) @ lattice
        if np.linalg.norm(shift) < reach:
            shifts.append(shift)
    return shifts


def _lj_sum(distances: np.ndarray, epsilon_ev: float, sigma_a: float) -> float:
    """``sum 4 eps ((sigma/r)^12 - (sigma/r)^6)`` over distances already inside the cutoff."""
    if distances.size == 0:
        return 0.0
    ratio6 = (sigma_a / distances) ** 6
    return float((4.0 * epsilon_ev * (ratio6 ** 2 - ratio6)).sum())


def lj_cut_energy(structure, *, epsilon_ev: float, sigma_a: float,
                  cutoff_a: float) -> float:
    """Total LJ energy (eV) for a periodic structure, LAMMPS ``lj/cut`` convention.

    ``epsilon_ev``/``sigma_a`` are the *pair* values (all type pairs identical, which is
    how our generated ``pair_coeff * * epsilon sigma`` is written).
    """
    cart = np.asarray(structure.cart_coords, dtype=float)
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    n_atoms = len(cart)
    shifts = _image_shifts(lattice, cutoff_a, _max_pair_separation(cart))

    # --- distinct atom pairs: the in-cell separation plus one term per image ----
    pair_distances: list[np.ndarray] = []
    if n_atoms >= 2:
        upper = np.triu_indices(n_atoms, k=1)
        diff = cart[:, None, :] - cart[None, :, :]
        pair_distances.append(np.sqrt((diff ** 2).sum(-1))[upper])
        for shift in shifts:
            image_diff = cart[:, None, :] - (cart[None, :, :] + shift)
            pair_distances.append(np.sqrt((image_diff ** 2).sum(-1))[upper])
    if pair_distances:
        inside = np.concatenate(pair_distances)
        inside = inside[(inside > 0.0) & (inside < cutoff_a)]
    else:
        inside = np.empty(0, dtype=float)
    energy = _lj_sum(inside, epsilon_ev, sigma_a)

    # --- an atom also interacts with its own images: (natoms/2) * sum_{m!=0} v(|mL|)
    if shifts and n_atoms:
        self_distances = np.array([float(np.linalg.norm(shift)) for shift in shifts])
        self_distances = self_distances[(self_distances > 0.0)
                                        & (self_distances < cutoff_a)]
        energy += 0.5 * n_atoms * _lj_sum(self_distances, epsilon_ev, sigma_a)
    return float(energy)


def lj_cut_energy_per_atom(structure, **kwargs) -> float:
    """``lj_cut_energy`` divided by the number of atoms."""
    return lj_cut_energy(structure, **kwargs) / len(structure)


def compare_with_lammps(structure, *, epsilon_ev: float, sigma_a: float,
                        cutoff_a: float, lammps_energy: float,
                        rtol: float = 1e-6, atol: float = 1e-4) -> dict:
    """Return a verdict dict comparing our reference energy with LAMMPS's."""
    ours = lj_cut_energy(structure, epsilon_ev=epsilon_ev, sigma_a=sigma_a,
                         cutoff_a=cutoff_a)
    difference = ours - float(lammps_energy)
    scale = max(abs(ours), abs(float(lammps_energy)), 1e-12)
    relative = abs(difference) / scale
    ok = relative <= rtol or abs(difference) <= atol
    return {"ours_eV": ours, "lammps_eV": float(lammps_energy),
            "difference_eV": difference, "relative": relative,
            "tolerance": {"rtol": rtol, "atol": atol}, "match": ok,
            "natoms": len(structure)}


__all__ = ["lj_cut_energy", "lj_cut_energy_per_atom", "compare_with_lammps"]
