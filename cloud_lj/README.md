# `cloud_lj/` — the shipped LAMMPS bundles behind the physics cross-check

Four `data.lammps` files (plus the cloud-side runner) used by
`scripts/check_lammps_physics.py` and `tests/test_lammps_physics.py` to check a
**number computed by LAMMPS** against a number computed by this project
(`cifkit.lammps_reference`), reading the *same shipped data file*.

Everything here is offline: no network and no LAMMPS binary is needed to run the gate.
`run_lj_check.py` is the cloud-side script that produced the recorded energies — it is
kept for provenance and for re-running the job, not used by the gate.

## Contents

| bundle | structure | atoms | cell (Å) | recorded LAMMPS energy |
|---|---|---|---|---|
| `data/lammps__hkust1_hfree/data.lammps` | Cu12C72O48 | 132 | 18.6538³ | 409124.98253649 eV |
| `data/lammps__mof5_hfree/data.lammps` | Zn8C48O26 | 82 | 18.2486³ | 173145.377770684 eV |
| `data/lammps__terephthalic_acid_hfree/data.lammps` | H4C8O4 | 16 | 15.0³ | 178719.393379894 eV |
| `data/lammps__zif8_cr_sod/data.lammps` | Zn6H60C48N24 | 138 | 14.6693³ | — (not probed) |

The recorded energies are the `Energy initial` value of a `minimize` run, i.e. the
potential energy at the **unrelaxed** exported coordinates; that is what the reference
evaluates. LAMMPS reports them at 15 digits in `realphysics_probe.json` (the thermo
table itself prints only 8), which is why the gate can use a 1e-8 tolerance.

## Provenance

* The four files are byte-identical (SHA256 prefixes `E3E3BB05`, `B3C71B27`,
  `70A5A8ED`, `160ED22B`) to `cloud_h3/cases/batch/lammps__*/data.lammps`, which were
  produced by `cifkit`'s LAMMPS writer and uploaded to the Bohrium H3 container.
* Cloud job (this project's label: `060f75f5`, 2026-11-11), LAMMPS
  `7 Feb 2024 - Update 1`, run by `cloud_h3/probe_real_physics.py` with
  `units metal`, `pair_style lj/cut 10.0`, `pair_coeff * * 0.0103 3.4`
  (a **placeholder** force field, not a fitted one), `neighbor 2.0 bin`,
  `minimize 1e-6 1e-8 200 2000`.
  The label `060f75f5` comes from the WIP notes around this work; it is **not**
  independently verifiable from the artifacts (the probe JSON carries no job id), so it
  is recorded as a project label rather than as a verified job reference.
* Raw artifacts (gitignored, local evidence):
  `runs/cloud_h3/real_physics2/realphysics_probe.json` and `runs/cloud_h3/real_physics2/log`.
  The job probed the **first three sorted batches**, which is why `lammps__zif8_cr_sod`
  ships without a recorded energy.
* The values are not taken on faith: the round-58 follow-up (which found and fixed two
  image-enumeration defects in `cifkit/lammps_reference.py`) pins them with hand-computed
  and self-image cases in `tests/test_lammps_physics.py` at `rtol=1e-8`, and
  `scripts/check_lammps_physics.py` re-runs the comparison offline (3/3 cases at
  ~2e-15 relative).

## How to reproduce

Offline (the gate; needs only `pymatgen`):

```
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe scripts\check_lammps_physics.py     # exit 0, writes runs/lammps_physics.json
.venv\Scripts\python.exe -m pytest tests\test_lammps_physics.py -q
```

On the cloud (re-measuring the LAMMPS numbers; needs `apt-get install lammps`, i.e.
network + a Linux container, and spends photons):

```
# upload this directory as the job's working directory, then
python3 run_lj_check.py     # writes lj_check.json with E_pair_eV per case
```

`run_lj_check.py` runs `run 0` for every `data/*/*.lammps` and records the last thermo
row. A new value must be pasted into `RECORDED` in `scripts/check_lammps_physics.py`
with its job id, since the gate compares against recorded, not live, LAMMPS output.

## What this does and does not show

* shows: the exported coordinates, box and masses drive the LJ sum LAMMPS actually
  evaluates, i.e. the file is not merely parseable — the physics of the file matches;
* does not show: chemical accuracy. `0.0103 eV / 3.4 Å` is a documented placeholder,
  not UFF/DREIDING; and it says nothing about pseudopotentials, cutoffs or the target
  code's own convergence.
