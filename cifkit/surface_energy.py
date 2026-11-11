"""Surface energy from a slab and a bulk reference (round 49, limitation D3).

D3 said the slab output is only an input structure: no energy, so no surface energy.
That remains true of *our* pipeline (we do not run DFT), but the arithmetic and the
bookkeeping around a user's two energies can be exact and auditable — and getting the
convention wrong is the classic error.  This module implements

    E_surf = (E_slab - n_slab * e_bulk_per_atom) / (2 A)

with:

* **two** ways to give the bulk reference (per-atom energy, or a bulk total plus its
  atom count) and an explicit error if they disagree;
* a stoichiometry check: the slab's formula must be a multiple of the bulk's, because
  otherwise the subtraction is meaningless (that is how people accidentally subtract
  a bulk *cell* from a slab with a different composition);
* units: eV/Å² (native), J/m² (1 eV/Å² = 16.02176634 J/m²) and meV/Å²;
* both surfaces counted by default, with ``symmetric=False`` for a slab that is
  terminated on one side only.

No DFT here — the energies must come from the user's converged calculation of the
same cell, thickness and vacuum.
"""
from __future__ import annotations

from dataclasses import dataclass

#: 1 eV/Å² in J/m² (CODATA-consistent: 1 eV = 1.602176634e-19 J, 1 Å² = 1e-20 m²)
EV_PER_ANGSTROM2_TO_J_PER_M2 = 16.02176634


@dataclass
class SurfaceEnergy:
    e_surf_ev_per_a2: float
    e_surf_j_per_m2: float
    e_surf_mev_per_a2: float
    surfaces: int
    n_slab: int
    e_bulk_per_atom: float
    area_a2: float
    excess_ev: float
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "E_surf_eV_per_A2": round(self.e_surf_ev_per_a2, 8),
            "E_surf_J_per_m2": round(self.e_surf_j_per_m2, 6),
            "E_surf_meV_per_A2": round(self.e_surf_mev_per_a2, 4),
            "surfaces": self.surfaces,
            "n_slab_atoms": self.n_slab,
            "E_bulk_eV_per_atom": self.e_bulk_per_atom,
            "area_A2": self.area_a2,
            "excess_energy_eV": round(self.excess_ev, 8),
            "note": self.note,
        }


def _stoichiometry_multiple(n_slab_elements: dict[str, int],
                            bulk_elements: dict[str, int]) -> int | None:
    """Largest integer ``k`` with ``slab == k * bulk``, else ``None``."""
    if not bulk_elements or not n_slab_elements:
        return None
    ratios = []
    for symbol, count in bulk_elements.items():
        slab_count = n_slab_elements.get(symbol, 0)
        if slab_count == 0:
            return None
        ratios.append(slab_count / count)
    extra = set(n_slab_elements) - set(bulk_elements)
    if any(n_slab_elements[symbol] > 0 for symbol in extra):
        return None
    first = ratios[0]
    if abs(first - round(first)) > 1e-6:
        return None
    multiple = int(round(first))
    if multiple <= 0:
        return None
    for ratio in ratios:
        if abs(ratio - multiple) > 1e-6:
            return None
    return multiple


def surface_energy(
    *,
    e_slab: float,
    n_slab: int,
    area_a2: float,
    e_bulk_per_atom: float | None = None,
    e_bulk_total: float | None = None,
    n_bulk: int | None = None,
    slab_formula: dict[str, int] | None = None,
    bulk_formula: dict[str, int] | None = None,
    surfaces: int = 2,
) -> SurfaceEnergy:
    """Compute the surface energy; raises ``ValueError`` on inconsistent input."""
    if n_slab <= 0:
        raise ValueError(f"n_slab must be positive, got {n_slab}")
    if area_a2 <= 0:
        raise ValueError(f"area must be positive, got {area_a2} A^2")
    if surfaces not in (1, 2):
        raise ValueError(f"surfaces must be 1 or 2, got {surfaces}")

    if e_bulk_per_atom is None:
        if e_bulk_total is None or not n_bulk:
            raise ValueError("give either e_bulk_per_atom or both e_bulk_total and n_bulk")
        e_bulk_per_atom = e_bulk_total / n_bulk
    elif e_bulk_total is not None and n_bulk:
        derived = e_bulk_total / n_bulk
        if abs(derived - e_bulk_per_atom) > 1e-6:
            raise ValueError(
                f"e_bulk_total/n_bulk = {derived:.6f} disagrees with "
                f"e_bulk_per_atom = {e_bulk_per_atom:.6f}")

    if slab_formula and bulk_formula:
        multiple = _stoichiometry_multiple(slab_formula, bulk_formula)
        if multiple is None:
            raise ValueError(
                "the slab composition is not an integer multiple of the bulk "
                f"composition ({slab_formula} vs {bulk_formula}): subtracting a bulk "
                "reference with a different stoichiometry is meaningless")

    excess = e_slab - n_slab * e_bulk_per_atom
    per_area = excess / (surfaces * area_a2)
    return SurfaceEnergy(
        e_surf_ev_per_a2=per_area,
        e_surf_j_per_m2=per_area * EV_PER_ANGSTROM2_TO_J_PER_M2,
        e_surf_mev_per_a2=per_area * 1000.0,
        surfaces=surfaces,
        n_slab=n_slab,
        e_bulk_per_atom=e_bulk_per_atom,
        area_a2=area_a2,
        excess_ev=excess,
        note=("energies must come from converged calculations of the SAME cell, "
              "slab thickness and vacuum; relaxation lowers the surface energy"),
    )


def render_markdown(result: SurfaceEnergy, *, title: str = "surface energy") -> str:
    data = result.as_dict()
    lines = [f"### {title}", "",
             f"- E_surf = **{data['E_surf_J_per_m2']:.4f} J/m²** "
             f"({data['E_surf_meV_per_A2']:.2f} meV/Å², {data['E_surf_eV_per_A2']:.6f} eV/Å²)",
             f"- slab: {result.n_slab} atoms, area {result.area_a2:.3f} Å², "
             f"{result.surfaces} surface(s)",
             f"- bulk reference: {result.e_bulk_per_atom:.6f} eV/atom",
             f"- excess energy: {result.excess_ev:.6f} eV", "",
             f"_{result.note}_"]
    return "\n".join(lines) + "\n"


__all__ = ["SurfaceEnergy", "surface_energy", "render_markdown",
           "EV_PER_ANGSTROM2_TO_J_PER_M2"]
