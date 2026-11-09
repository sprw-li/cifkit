# Cloud GPU acceptance probe (H3)

This bundle is uploaded to a Bohrium Batch-Job container so we can find out, **with
real evidence**, whether our calculation-software input templates are accepted by
real codes (limitation H3) — and what the platform image actually has installed.

## What runs

`python run_acceptance.py` (stdlib only):

1. prints the GPU/CUDA summary (`nvidia-smi`);
2. detects VASP / Quantum ESPRESSO / CP2K / ORCA / DFTB+ / NWChem / Gaussian /
   LAMMPS / GROMACS on `PATH`;
3. runs a **minimal self-contained** case for each code it finds and checks a
   code-specific success marker (`JOB DONE`, `PROGRAM ENDED AT`,
   `ORCA TERMINATED NORMALLY`, ...);
4. writes `acceptance_result.json` for the host to `fetch`.

Exit code 0 = at least one code verified; 1 = nothing installed (a valid,
informative result: the *image* lacks the software).

## Deliberate options

| flag | effect | cost note |
|---|---|---|
| `--install cp2k` | `apt-get update && apt-get install -y cp2k` before probing | needs container network; ~100 kB/s measured, so a ~100 MB package is ~20+ min |

## Honest framing

* a `dry-run` payload is **not** a GPU result;
* `verified` here means "a real binary accepted this exact minimal input and
  printed its completion marker" — not that our full template is production-ready
  (pseudopotentials, cutoffs, k-points and convergence are still the user's job);
* the default Bohrium image is a **PyTorch CUDA runtime** and contains none of
  these codes; expect `not-installed` for everything unless an appropriate image
  or `--install` is used.
