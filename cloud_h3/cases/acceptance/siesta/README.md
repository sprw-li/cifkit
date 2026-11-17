# siesta acceptance input (H3)

Structure: H4C8O4 (16 atoms), 15.0 Å cubic cell.
File: `structure.fdf` (SHA256 `2F1AC8541426723F…`)

## What this is

A cifkit SIESTA export template (`%block` fdf syntax, fractional coordinates), uploaded
to the Bohrium H3 container purely as **input for an independent parser** — no SIESTA
calculation has been run or validated against it. `ChemicalSpeciesLabel` uses the
standard H/C/O species labels; no PAO basis or pseudopotential files are shipped
(size/licensing).

## Who reads it

`cloud_h3/probe_independent.py::check_siesta` installs `sisl` in the container and
loads this exact path with `sisl.geom_fdf`, recording `parsed`/`exit`/`stderr` in
`independent_validation.json`.

## How to re-run

Upload `cloud_h3/` to a Linux container and run `python3 probe_independent.py`.
Note the archived run (job `076003da59a54c0f91e4e1a39703dfb8`, 2026-11-11T17:08Z,
`runs/cloud_h3/independent/log`) **failed to install the parsers**: `pip` refused with
PEP 668 for `cp2k-input-tools`/`sisl`/`qeschema` and the `ase==3.22.1` download was
truncated. So there is no recorded independent parse result yet; a re-run must install
into a venv or pass `--break-system-packages`.

## Notes

* This is a *template*: choose a functional, cutoff/`MeshCutoff`, `kgrid` and real
  pseudopotentials before any production run.
