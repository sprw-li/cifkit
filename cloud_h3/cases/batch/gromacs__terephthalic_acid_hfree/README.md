# gromacs input bundle

Structure: H4C8O4 (16 atoms)
Files: conf.gro, coords.xyz, topol.top, md.mdp, TOP.readme

## What you must supply / review
- force-field atom types/charges (the shipped .top lists real atoms and bonds but its types/charges are PLACEHOLDERS)
- box/charge equilibration

## Notes
- The geometry is written in Angstrom by cifkit.
- This is a *template*, not a converged input: review cutoffs, k-points, functional,
  charges/spins and pseudopotential names before running.
- cifkit does not provide POTCAR/UPF/skf files (licensing/size); no calculation has
  been run or validated against the target code in this bundle.

