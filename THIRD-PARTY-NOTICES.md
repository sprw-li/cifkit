# Third-party notices

`cifkit` itself is MIT (see [LICENSE](LICENSE)).  This file records what the
repository redistributes, what it merely *talks to*, and under which terms —
so a public clone or a commercial integrator can check the obligations without
reading the whole repo.  It is an engineering record, **not legal advice**; the
upstream pages are authoritative and their terms change.

Everything below was measured on this tree (2026-11); re-check with
`python scripts/license_audit.py --all` and the sources' own pages before you
rely on it.

## 1. Data that is **committed** to this repository

| Where | What | Origin | Terms |
|---|---|---|---|
| `tests/data/*.cif` | 12 test structures (ZIF-8, MOF-5, HKUST-1, UiO-66, …) | **CoRE MOF 2024** (Zenodo record 15055758), annotated with DDEC6 charges by PACMAN | **CC-BY-4.0** — redistribution allowed **with attribution** (record DOI + "CoRE MOF 2024").  The underlying entries are CSD-derived; the CSD itself has separate terms |
| `cifkit/data/nets/*-reference.cif` | 6 topology reference nets (sod/pcu/dia/fcu/tbo/bcu) | CoRE MOF 2024 ASR subset | same as above |
| `runs/demo_sod_zif8/*` | the acceptance demo: raw CIF (`raw.cif`) plus structures derived from it | `SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`, DOI [10.1021/ja204757x](https://doi.org/10.1021/ja204757x) (ZIF-8) | CC-BY-4.0 data (CC-BY-4.0 / CoRE MOF 2024); the tool's own outputs are MIT |
| `usecases/u3_metals/data/cod_cache/*.cif`, `usecases/u1_fd3m/data/structures/*.cif` | metal/symmetry examples | **Crystallography Open Database** | **public domain** (citation appreciated, not required) |
| `usecases/u4_fec/structures/*` | Fe–C compounds | **AFLOW** (derived) | AFLOW terms apply to the data |

Every generated `manifest.json` also records the per-record `doi`, `url`,
`sha256` and `license` string, so a downstream user can reproduce the
attribution of any single structure.

**Not redistributed**: the CoRE MOF archive itself (`_cache/`), Materials
Project entries, QMOF, POTCAR/UPF/Slater-Koster files, force fields and basis
sets.  Run `python scripts/bootstrap_data.py` to fetch the CoRE cache yourself.

## 2. Data sources the tool **queries**

| Source | Terms |
|---|---|
| `core-mof` (CoRE MOF 2024) | CC-BY-4.0 (attribution) |
| `cod` (Crystallography Open Database) | public domain |
| `materials-project` | Materials Project terms + requires your own `MP_API_KEY`; do not treat its data as your own |
| `aflow` | AFLOW terms (no key) |
| `qmof` | DFT-labelled set derived from CoRE/CSD — treat with care |
| `local` | your own files |

## 3. Runtime dependencies (direct)

| Package | Licence | Note |
|---|---|---|
| pymatgen | MIT | |
| spglib | BSD-3-Clause | |
| numpy | BSD-3-Clause (plus permissively licensed components) | |
| scipy | BSD-3-Clause | |
| matplotlib | PSF-based / BSD-compatible | |
| networkx | BSD-3-Clause | |
| rdkit | BSD-3-Clause | |
| Pillow | MIT-CMU | |
| **ASE** | **LGPL-2.1-or-later** | used unmodified as an imported library; modifying or statically embedding it triggers LGPL obligations |
| **openbabel-wheel** | **GPL-2.0** | **not imported by any code path** — `scripts/verify_formats_no_gpl.py` blocks it via `sys.meta_path` and all 31 formats + 12 bundles still pass, so the core API can be used without installing it |

The core path has **no GPL/AGPL code**.  `scripts/sca_scan.py --strict` reports
zero actionable copyleft in source (it runs as a release gate).

## 4. What this repository does **not** ship

POTCAR, UPF pseudopotentials, Slater-Koster files, force fields and basis sets:
they are licence-restricted and are never bundled.  The generated
calculation-input bundles list them under `missing` instead.

## 5. Generated output

Structures, converted files and input templates produced by cifkit are covered
by the same MIT terms as the code.  The *data* they were derived from keeps its
own licence (section 1) — carry the attribution with it.

## 6. How to re-check

```
python scripts/license_audit.py --all      # installed distributions, by licence
python scripts/sca_scan.py --strict        # copyleft in this repo's source
python scripts/verify_formats_no_gpl.py    # 31 formats with Open Babel blocked
python scripts/check_portability.py        # no host paths in generated inputs
```

Known uncertainties are listed in [LICENSING.md](LICENSING.md) §6: this is a
declaration by the authors, not a per-file copyright audit.
