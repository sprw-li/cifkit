# Surface-energy inputs (`surface_energy/`)

Static VASP templates for the densest-plane slab of every metal in this kit.

## Files

| file | meaning |
|---|---|
| `INCAR` | static single-point template (no ionic relaxation), see the comments |
| `KPOINTS` | generic Gamma-centred template; each element has its own tuned one in `elements/<El>/KPOINTS` |

## Formula

For a symmetric slab with two equivalent surfaces

    E_surf = (E_slab - N_slab * mu) / (2 * A)

* `E_slab` 鈥?total energy of `elements/<El>/slab_POSCAR` (eV)
* `mu` 鈥?bulk energy per atom: `E_bulk_cell / Z` from `elements/<El>/bulk_POSCAR`
  (`Z` is given in `lattice.csv`; `E_bulk_cell` is the VASP energy of that cell)
* `N_slab` 鈥?number of atoms in `slab_POSCAR` (also in `metals_summary.csv`)
* `A` 鈥?surface area of the slab cell, `|a x b|` in 脜虏 (also in
  `metals_summary.csv` as `surface_area`)
* `2A` 鈥?top and bottom surfaces (the slabs are built symmetric, so both have
  the same termination)

Equivalently with per-atom energies: `E_surf = (E_slab/N_slab - mu) * N_slab/(2A)`.

## Procedure

1. **Bulk reference** 鈥?run VASP on `elements/<El>/bulk_POSCAR` (k-mesh: the
   `KPOINTS` comment suggests the matching 3D mesh) and extract the total energy.
2. **Slab** 鈥?run VASP on `elements/<El>/slab_POSCAR` (vacuum 鈮?15 脜 in `c`;
   `KPOINTS` has `kz = 1`). To relax the surface, set `NSW`/`IBRION` as noted in
   `INCAR` and freeze the two bottom layers with Selective dynamics.
3. Apply the formula above with `N_slab` and `A` from `metals_summary.csv`.

## Notes / limitations

* Both surfaces of each slab are equivalent by construction 鈥?do **not** double
  count; the `2A` in the denominator already accounts for both.
* Use the same `POTCAR`, `ENCUT` and smearing for bulk and slab, otherwise the
  energy difference is not meaningful.
* The slabs are ideal (unrelaxed) crystallographic cuts at the experimental
  (Kittel / AFLOW / ICSD) lattice constants; a real surface energy needs the
  relaxed geometry and a convergence study (`ENCUT`, k-mesh, slab thickness,
  vacuum).
* `ISPIN = 2` is set for all elements; for non-magnetic metals the spin moment
  converges to zero (harmless, slightly slower).
* These files are inputs/templates only 鈥?**no VASP energies are included or
  claimed** in this kit.
