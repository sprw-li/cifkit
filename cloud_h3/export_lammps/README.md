# lammps input bundle

Structure: H4C8O4 (16 atoms)
Files: data.lammps, in.min

## What you must supply / review
- pair_style/force field
- masses if not in data file

## Notes
- The geometry is written in Angstrom by cifkit.
- This is a *template*, not a converged input: review cutoffs, k-points, functional,
  charges/spins and pseudopotential names before running.
- cifkit does not provide POTCAR/UPF/skf files (licensing/size); no calculation has
  been run or validated against the target code in this bundle.

