# cp2k acceptance input (H3)

Structure: H4C8O4 (16 atoms), 15.0 Å cubic cell.
File: `cp2k.inp` (SHA256 `A1CD0BDC5830B900…`)

## What this is

The cifkit CP2K export template for this structure, with the leading `#` comments
rewritten to CP2K's `!` so a real parser sees valid syntax (content is otherwise
identical to `cloud_h3/cases/cp2k_export.inp`). It was uploaded to the Bohrium H3
container purely as **input for an independent parser** — no CP2K calculation has
been run or validated against it.

## Who reads it

`cloud_h3/probe_independent.py::check_cp2k` installs `cp2k-input-tools` in the
container and parses this exact path, recording `parsed`/`exit`/`stderr` in
`independent_validation.json`.

## How to re-run

Upload `cloud_h3/` to a Linux container and run `python3 probe_independent.py`.
Note the archived run (job `076003da59a54c0f91e4e1a39703dfb8`, 2026-11-11T17:08Z,
`runs/cloud_h3/independent/log`) **failed to install the parsers**: `pip` refused with
PEP 668 (`externally-managed-environment`) for `cp2k-input-tools`/`sisl`/`qeschema`
and the `ase==3.22.1` download was truncated. So there is no recorded independent
parse result yet; a re-run must install into a venv or pass
`--break-system-packages`.

## Notes

* This is a *template*, not a converged input: review functional, cutoffs, basis sets
  and k-points before running real chemistry — `&KIND`/`BASIS_SET`/`POTENTIAL`
  sections are deliberately absent.
* cifkit does not ship basis-set/potential files (size/licensing).
