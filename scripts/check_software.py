"""Acceptance harness for real calculation software (limitation H3).

The workbench emits *templates* for VASP/QE/CP2K/... and has never run one in a
real code, so H3 stays open.  This script makes the missing evidence mechanical:

1. **detect** the executables on ``PATH`` (and any custom paths you add);
2. report, per code, the extra data it needs (POTCAR / UPF / basis / .skf / force
   field) and whether that data is present, from an env var or the usual location;
3. with ``--run``, actually execute a **minimal self-contained** case for the codes
   that are ready, with a timeout, and check a code-specific success marker;
4. write ``runs/check_software.json`` and print a table.

Honest framing: "detected" != "accepted".  A code is only reported as *verified*
when the minimal run completed **and** its success marker appeared.  On a machine
without these codes (like the author's) every row is ``not-installed`` and H3
remains unverified — which is exactly what the report says.

    python scripts\\check_software.py [--run] [--timeout 120] [--json OUT]

Environment overrides: ``CIFKIT_VASP_PP``, ``CIFKIT_QE_PSEUDO_DIR``,
``CIFKIT_DFTB_SK``, ``CIFKIT_CP2K_DATA``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Software:
    name: str
    binaries: tuple[str, ...]
    #: env var and a few conventional locations for the required data
    data_env: str | None = None
    data_candidates: tuple[str, ...] = ()
    data_label: str = ""
    min_case: str = ""
    success_marker: str = ""
    note: str = ""
    found: str | None = None
    data_path: str | None = None
    data_ok: bool | None = None
    run_status: str = "not-run"
    run_detail: str = ""

    @property
    def runnable(self) -> bool:
        if self.found is None:
            return False
        if self.data_env is None:
            return True
        return bool(self.data_ok)


SOFTWARE: list[Software] = [
    Software(
        name="VASP",
        binaries=("vasp_std", "vasp_gam", "vasp_ncl", "vasp"),
        data_env="CIFKIT_VASP_PP",
        data_candidates=("~/vasp/potpaw_PBE", "C:/vasp/potpaw_PBE"),
        data_label="POTCAR (licensed, user-supplied)",
        min_case="POSCAR+KPOINTS+INCAR+POTCAR, 1 ionic step (NSW=0)",
        success_marker="General timing and accounting",
        note="license-restricted; the workbench never ships POTCAR",
    ),
    Software(
        name="Quantum ESPRESSO",
        binaries=("pw.x",),
        data_env="CIFKIT_QE_PSEUDO_DIR",
        data_candidates=("~/qe/pseudo", "C:/qe/pseudo", "/usr/share/espresso/pseudo"),
        data_label="UPF pseudopotentials (user-supplied)",
        min_case="pw.x scf, single k-point, 1 iteration (electron_maxstep=1)",
        success_marker="JOB DONE",
        note="needs a UPF for every element in the structure",
    ),
    Software(
        name="CP2K",
        binaries=("cp2k.psmp", "cp2k.popt", "cp2k.ssmp", "cp2k"),
        data_env="CIFKIT_CP2K_DATA",
        data_candidates=("~/cp2k/data", "C:/cp2k/data", "/usr/share/cp2k/data"),
        data_label="CP2K data dir (BASIS_SET/POTENTIAL)",
        min_case="ENERGY_FORCE single point on H2O, 1 SCF step",
        success_marker="PROGRAM ENDED AT",
        note="cp2k usually ships its own data dir next to the binary",
    ),
    Software(
        name="DFTB+",
        binaries=("dftb+", "dftbplus"),
        data_env="CIFKIT_DFTB_SK",
        data_candidates=("~/dftb/slakos", "C:/dftb/slakos"),
        data_label="Slater-Koster .skf files",
        min_case="dftb+ single point, SCC off",
        success_marker="Total Energy",
    ),
    Software(
        name="ORCA",
        binaries=("orca",),
        min_case="ORCA single point (RHF/STO-3G) on H2",
        success_marker="ORCA TERMINATED NORMALLY",
        note="the input templates cifkit writes are single-point shells",
    ),
    Software(
        name="Gaussian",
        binaries=("g16", "g09"),
        min_case="Gaussian single point (HF/STO-3G) on H2",
        success_marker="Normal termination",
        note="license-restricted",
    ),
    Software(
        name="LAMMPS",
        binaries=("lmp", "lmp_mpi", "lmp_serial"),
        data_label="a force field (user-supplied)",
        data_env="CIFKIT_LAMMPS_POTENTIAL",
        min_case="0-step run with a user-supplied potential",
        success_marker="Total wall time",
    ),
    Software(
        name="GROMACS",
        binaries=("gmx", "gmx_mpi"),
        data_env="CIFKIT_GMX_FORCEFIELD",
        data_label="a force field (user-supplied)",
        min_case="grompp + one mdrun step",
        success_marker="Finished mdrun",
    ),
    Software(
        name="SIESTA",
        binaries=("siesta",),
        data_env="CIFKIT_SIESTA_PP",
        data_label=".psf/.psml pseudopotentials",
        min_case="siesta single point, 1 SCF step",
        success_marker="siesta: End of run",
    ),
    Software(
        name="ABACUS",
        binaries=("abacus", "abacus.x"),
        data_env="CIFKIT_ABACUS_PP",
        data_label="pseudopotentials + numerical orbitals",
        min_case="abacus scf, 1 iteration",
        success_marker="charge density convergence",
    ),
    Software(
        name="NWChem",
        binaries=("nwchem",),
        min_case="NWChem single point (STO-3G) on H2",
        success_marker="Total times",
    ),
    Software(
        name="FHI-aims",
        binaries=("aims.x", "aims"),
        data_env="CIFKIT_AIMS_SPECIES",
        data_label="species defaults (licensed)",
        min_case="aims single point, 1 SCF iteration",
        success_marker="Have a nice day",
    ),
]


def detect(software: Software) -> None:
    for name in software.binaries:
        found = shutil.which(name)
        if found:
            software.found = found
            break
    if software.data_env is None:
        return
    env_value = os.environ.get(software.data_env)
    candidates = [env_value] if env_value else []
    candidates.extend(software.data_candidates)
    # also look next to the binary (CP2K-style layouts)
    if software.found:
        candidates.append(str(Path(software.found).parent / "data"))
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.exists() and any(path.iterdir() if path.is_dir() else [path]):
            software.data_path = str(path)
            software.data_ok = True
            return
    software.data_ok = False


def minimal_case_path(software: Software, directory: Path) -> tuple[Path, str] | None:
    """Write a minimal, self-contained input for the codes we can actually run."""
    if software.name == "ORCA":
        inp = directory / "h2.inp"
        inp.write_text("! RHF STO-3G\n* xyz 0 1\nH 0 0 0\nH 0 0 0.74\n*\n", encoding="utf-8")
        return inp, f"{software.binaries[0]} {inp.name}"
    if software.name == "Gaussian":
        inp = directory / "h2.com"
        inp.write_text("#p HF/STO-3G\n\nH2 single point\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n",
                       encoding="utf-8")
        return inp, f"{software.binaries[0]} {inp.name}"
    if software.name == "NWChem":
        inp = directory / "h2.nw"
        inp.write_text("start h2\ngeometry units angstrom\nH 0 0 0\nH 0 0 0.74\nend\n"
                       "basis\nH library sto-3g\nend\ntask scf energy\n", encoding="utf-8")
        return inp, f"nwchem {inp.name}"
    if software.name == "CP2K" and software.data_ok:
        inp = directory / "h2o.inp"
        inp.write_text(
            "&GLOBAL\n  PROJECT h2o\n  RUN_TYPE ENERGY\n&END GLOBAL\n"
            "&FORCE_EVAL\n  METHOD Quickstep\n  &DFT\n"
            "    BASIS_SET_FILE_NAME BASIS_MOLOPT\n    POTENTIAL_FILE_NAME GTH_POTENTIALS\n"
            "    &MGRID\n      CUTOFF 200\n    &END MGRID\n"
            "    &SCF\n      MAX_SCF 1\n      SCF_GUESS ATOMIC\n    &END SCF\n"
            "  &END DFT\n  &SUBSYS\n    &CELL\n      ABC 10 10 10\n    &END CELL\n"
            "    &COORD\nO 0 0 0\nH 0.757 0.586 0\nH -0.757 0.586 0\n    &END COORD\n"
            "    &KIND H\n      BASIS_SET DZVP-MOLOPT-GTH\n      POTENTIAL GTH-PBE-q1\n    &END KIND\n"
            "    &KIND O\n      BASIS_SET DZVP-MOLOPT-GTH\n      POTENTIAL GTH-PBE-q6\n    &END KIND\n"
            "  &END SUBSYS\n&END FORCE_EVAL\n", encoding="utf-8")
        return inp, f"{software.binaries[0]} -i {inp.name}"
    if software.name == "Quantum ESPRESSO" and software.data_ok:
        # use whatever UPF the user pointed at, for the elements in H2O
        pseudos = sorted(Path(software.data_path).glob("*.UPF")) + \
            sorted(Path(software.data_path).glob("*.upf"))
        picked: dict[str, str] = {}
        for element in ("H", "O"):
            for pseudo in pseudos:
                if pseudo.stem.upper().startswith(element):
                    picked[element] = pseudo.name
                    break
        if len(picked) == 2:
            inp = directory / "pw.in"
            inp.write_text(
                "&CONTROL\n calculation='scf', prefix='h2o', pseudo_dir='{pseudo}'\n"
                " outdir='./tmp'\n/\n&SYSTEM\n ibrav=0, nat=2, ntyp=2, ecutwfc=20\n/\n"
                "&ELECTRONS\n electron_maxstep=1\n/\nATOMIC_SPECIES\n"
                " H 1.008 {h}\n O 15.999 {o}\nCELL_PARAMETERS angstrom\n"
                " 8 0 0\n 0 8 0\n 0 0 8\nATOMIC_POSITIONS angstrom\n"
                " O 0 0 0\n H 0.757 0.586 0\nK_POINTS gamma\n".format(
                    pseudo=software.data_path, h=picked["H"], o=picked["O"]),
                encoding="utf-8")
            return inp, f"{software.binaries[0]} -in {inp.name}"
    return None


def run_case(software: Software, timeout: float) -> None:
    with tempfile.TemporaryDirectory(prefix=f"cifkit-{software.name.split()[0].lower()}-") as tmp:
        directory = Path(tmp)
        prepared = minimal_case_path(software, directory)
        if prepared is None:
            software.run_status = "no-minimal-case"
            software.run_detail = (f"需要 {software.data_label or '外部数据'}；"
                                   "请设置对应环境变量后重跑 --run")
            return
        _, command = prepared
        executable = software.found
        command = command.replace(software.binaries[0], f'"{executable}"', 1)
        try:
            proc = subprocess.run(command, shell=True, cwd=str(directory), capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            software.run_status = "timeout"
            software.run_detail = f"> {timeout:.0f}s"
            return
        blob = f"{proc.stdout}\n{proc.stderr}"
        if software.success_marker and software.success_marker in blob:
            software.run_status = "verified"
            software.run_detail = f"marker {software.success_marker!r} found"
        elif proc.returncode == 0:
            software.run_status = "ran-no-marker"
            software.run_detail = "exit 0 but the success marker was missing"
        else:
            software.run_status = "failed"
            tail = blob.strip().splitlines()[-1][:120] if blob.strip() else ""
            software.run_detail = f"exit {proc.returncode}: {tail}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="actually execute minimal cases")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--json", default=str(ROOT / "runs" / "check_software.json"))
    args = ap.parse_args()

    for software in SOFTWARE:
        detect(software)
        if args.run and software.runnable:
            run_case(software, args.timeout)

    counts: dict[str, int] = {}
    for software in SOFTWARE:
        key = software.run_status if software.found else "not-installed"
        counts[key] = counts.get(key, 0) + 1

    print(f"{'software':16s} {'binary':28s} {'data':18s} status")
    for software in SOFTWARE:
        binary = software.found or "-"
        data = "ok" if software.data_ok else ("missing" if software.data_ok is False else "-")
        status = software.run_status if software.found else "not-installed"
        print(f"{software.name:16s} {binary[:28]:28s} {data:18s} {status}"
              + (f"  ({software.run_detail})" if software.run_detail else ""))
    print("\nstatus counts:", counts)

    report = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ran": bool(args.run),
        "counts": counts,
        "software": [{
            "name": s.name, "binary": s.found, "data_env": s.data_env,
            "data_path": s.data_path, "data_ok": s.data_ok,
            "min_case": s.min_case, "success_marker": s.success_marker,
            "run_status": s.run_status if s.found else "not-installed",
            "run_detail": s.run_detail, "note": s.note,
        } for s in SOFTWARE],
        "honesty": (
            "「检测到可执行文件」≠「输入被接受」。只有 run_status='verified' 才算真实验证；"
            "本报告不改变 docs/LIMITATIONS.md H3 的状态，除非至少一个代码达到 verified。"
        ),
    }
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")

    verified = [s.name for s in SOFTWARE if s.run_status == "verified"]
    if verified:
        print("VERIFIED:", ", ".join(verified))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
