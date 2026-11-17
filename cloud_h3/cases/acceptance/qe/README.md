# qe acceptance input (H3)

Structure: H4C8O4 (16 atoms), 15.0 Å cubic cell.
File: `pw.in` (SHA256 `BED0FC99F10AF242…`, byte-identical to
`cloud_h3/cases/qe_export.in`)

## What this is

The cifkit Quantum ESPRESSO export template for this structure, uploaded to the
Bohrium H3 container purely as **input for an independent parser** — no `pw.x`
calculation has been run or validated against it. `ATOMIC_SPECIES` uses placeholder
`H.UPF`/`C.UPF`/`O.UPF` names (cifkit cannot ship pseudopotentials).

## Who reads it

`cloud_h3/probe_independent.py::check_qe` installs `qeschema` in the container and
parses this exact path, recording `parsed`/`exit`/`stderr` in
`independent_validation.json`.

## How to re-run

Upload `cloud_h3/` to a Linux container and run `python3 probe_independent.py`.
Note the archived run (job `076003da59a54c0f91e4e1a39703dfb8`, 2026-11-11T17:08Z,
`runs/cloud_h3/independent/log`) **failed to install the parsers**: `pip` refused with
PEP 668 for `cp2k-input-tools`/`sisl`/`qeschema` and the `ase==3.22.1` download was
truncated. So there is no recorded independent parse result yet; a re-run must install
into a venv or pass `--break-system-packages`.

## Notes

* This is a *template*: converge `ecutwfc`/`ecutrho` and the k-mesh, and supply real
  pseudopotential files, before any production run.
