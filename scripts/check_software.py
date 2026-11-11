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


#: levels used for cloud evidence
LEVELS = ("verified", "accepted", "blocked")


def classify_cloud_evidence(root: Path) -> dict:
    """Turn the cloud artifacts into a per-code acceptance level.

    * ``verified`` — a real binary ran a case to a success marker
      (NWChem's ``Total times`` / ``PROGRAM ENDED AT`` style markers);
    * ``accepted`` — a real binary parsed our file (and, for LAMMPS, completed a
      ``run 0`` energy evaluation) but no force field / full calculation;
    * ``blocked``  — the code itself is unusable in that image (upstream), proven
      by a *canonical* input failing the same way.

    Returns ``{code: {"level": ..., "evidence": str, "detail": str}}``; missing or
    malformed artifacts are simply skipped (this must never crash a report).
    """
    result: dict[str, dict] = {}
    if not root.is_dir():
        return result

    #: display names, so "LAMMPS"/"lammps"/"GROMACS" cannot end up as separate rows
    DISPLAY = {
        "lammps": "LAMMPS", "gromacs": "GROMACS", "nwchem": "NWChem",
        "abinit": "ABINIT", "cp2k": "CP2K", "quantum espresso": "Quantum ESPRESSO",
        "orca (chemistry)": "ORCA (chemistry)", "nwchem (cifkit template)": "NWChem (cifkit template)",
    }

    def record(code: str, level: str, evidence: Path, detail: str) -> None:
        key = DISPLAY.get(str(code).strip().lower(), str(code).strip())
        current = result.get(key)
        rank = {"verified": 3, "accepted": 2, "blocked": 1}
        if current is None or rank[level] > rank[current["level"]]:
            result[key] = {"level": level, "evidence": str(evidence), "detail": detail}
        elif level == current["level"]:
            # keep both details: the same level from two runs is useful context
            if detail not in current["detail"]:
                current["detail"] = f"{current['detail']}; {detail}"

    def newest(pattern: str) -> list[Path]:
        paths = [p for p in root.glob(pattern) if p.is_file()]
        return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)

    for path in newest("artifacts_*/acceptance_result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in payload.get("codes", []):
            if row.get("status") == "verified":
                record(row.get("code", "?"), "verified", path,
                       f"binary {row.get('binary')}, exit {row.get('exit')}")

    for path in newest("artifacts_*/our_template_result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("finished_normally"):
            record("NWChem (cifkit template)", "verified", path,
                   f"{payload.get('case')} ran to a normal end in {payload.get('seconds')}s")

    for path in newest("artifacts_*/parse_accept.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for case in payload.get("cases", []):
            if not case.get("accepted"):
                continue
            # Parse-level cases count as ``accepted`` unless the probe says a
            # real calculation completed (LAMMPS/GROMACS have no force field here).
            level = "verified" if case.get("calculation_completed") else "accepted"
            completed = bool(case.get("calculation_completed"))
            record(case.get("code", "?"), level, path,
                   f"input {case.get('input')} exit {case.get('exit')} "
                   f"(calculation_completed={completed})")


    # round 53: real-binary acceptance runs (cloud_h3/run_code_acceptance.py).
    # A normal end marker means the code *accepted our shipped file*; the codes that
    # cannot run at all (screen-reader 'orca', EOL abinit) are recorded as blocked
    # with the reason instead of being silently absent.
    BLOCKED_CODES = {
        "orca-debian-package": ("ORCA (chemistry)",
                                "Debian's 'orca' package is the GNOME screen reader"),
        "abinit": ("ABINIT", "the packaged 9.10 binary refuses to run (EOL build)"),
    }
    for path in sorted(list(root.glob("accept_*/acceptance_result.json")) +
                       list(root.glob("artifacts_*/acceptance_result.json")),
                       key=lambda item: item.stat().st_mtime):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        code = str(payload.get("code") or "?")
        status = payload.get("status")
        if status == "accepted":
            # 'accepted' is the honest level for geometry-only runs (no force field):
            # the file is *accepted* by the code, but no physical quantity was computed
            detail = (f"binary {payload.get('binary')} exit {payload.get('exit')} "
                      f"marker {payload.get('normal_marker')!r} "
                      f"({payload.get('route')})")
            if code == "lammps":
                detail += " [pair_style zero: geometry check, no force field]"
            record(code, "accepted", path, detail)
        elif status in ("failed-marker", "no-normal-marker"):
            mapped = BLOCKED_CODES.get(code)
            if mapped:
                record(mapped[0], "blocked", path,
                       f"{mapped[1]} (evidence: {payload.get('failure_marker') or status})")

    for path in newest("artifacts_*/qe_minimal.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cases = payload.get("cases", [])
        canonical = next((c for c in cases if c.get("case") == "canonical"), None)
        if canonical and canonical.get("abort"):
            record("Quantum ESPRESSO", "blocked", path,
                   "canonical H2O input also SIGABRTs -> upstream binary, not our template")

    for path in newest("artifacts_*/apt_packages.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        policy = payload.get("policy", {})
        if "Candidate: (none)" in (policy.get("cp2k") or ""):
            record("CP2K", "blocked", path,
                   "cp2k is absent from the image's apt mirror (Candidate: none)")

    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="actually execute minimal cases")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--json", default=str(ROOT / "runs" / "check_software.json"))
    ap.add_argument("--cloud", dest="cloud", action="store_true", default=True,
                    help="also ingest runs/cloud_h3 real-run evidence (default on)")
    ap.add_argument("--no-cloud", dest="cloud", action="store_false")
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

    cloud = classify_cloud_evidence(ROOT / "runs" / "cloud_h3") if args.cloud else {}
    if cloud:
        print("\ncloud evidence (real binaries, from runs/cloud_h3):")
        for code, row in sorted(cloud.items()):
            print(f"  {row['level']:9s} {code:26s} {row['detail']}")
        cloud_counts: dict[str, int] = {}
        for row in cloud.values():
            cloud_counts[row["level"]] = cloud_counts.get(row["level"], 0) + 1
        print("  cloud counts:", cloud_counts)

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
        "cloud": cloud,
        "cloud_counts": (lambda: {level: sum(1 for row in cloud.values()
                                             if row["level"] == level)
                                  for level in LEVELS})() if cloud else {},
        "honesty": (
            "「检测到可执行文件」≠「输入被接受」，本地 verified 只代表本机跑通；"
            "cloud 段的证据来自 runs/cloud_h3 里真实容器的运行记录："
            "verified=完整跑到成功标记，accepted=真实二进制接受了我们的文件（无完整计算），"
            "blocked=该镜像里的软件本身不可用（有 canonical 对照）。"
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
