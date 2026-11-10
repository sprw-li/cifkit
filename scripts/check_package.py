"""Release-readiness: build a wheel, install it into a target dir, exercise it.

Round 35: packaging had only ever run as CI *definitions*; nothing built or
installed the distribution locally (limitation H6).  This script does it:

1. build the wheel (no network, no build isolation) into ``runs/dist``;
2. ``pip install --no-deps --target runs/dist_target`` the freshly built wheel —
   an isolated directory, so the *installed* copy is what gets imported (the dev
   dependencies still come from the project venv);
3. from a **different working directory** and with ``PYTHONPATH`` pointing at the
   target dir, import the public modules, run the CLI, dump the contract schemas,
   and verify the bundled topology references (these are package data — the first
   wheel, built before ``schemas/*.json`` were declared, would fail here);
4. write ``runs/check_package.json``.

    .venv\\Scripts\\python.exe scripts\\check_package.py [--json OUT]
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
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "runs" / "dist"
TARGET = ROOT / "runs" / "dist_target"


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 900,
        env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env={**os.environ, **(env or {})})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "check_package.json"))
    args = ap.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "steps": [],
                    "ok": False, "errors": []}

    def step(name: str, proc: subprocess.CompletedProcess) -> bool:
        ok = proc.returncode == 0
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
        report["steps"].append({"step": name, "exit": proc.returncode, "ok": ok, "tail": tail})
        print(f"[{'ok ' if ok else 'FAIL'}] {name}")
        if not ok:
            report["errors"].append(f"{name}: exit {proc.returncode}")
            print(tail[-900:])
        return ok

    def fail() -> int:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"package check: FAIL — {args.json}")
        return 1

    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(TARGET, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)
    if not step("build wheel", run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                                    "--no-build-isolation", "-w", str(DIST)])):
        return fail()
    wheels = sorted(DIST.glob("*.whl"))
    if not wheels:
        report["errors"].append("no wheel produced")
        return fail()
    wheel = wheels[0]
    report["wheel"] = str(wheel)
    report["wheel_bytes"] = wheel.stat().st_size

    names = zipfile.ZipFile(wheel).namelist()
    report["wheel_files"] = len(names)
    report["packaged_schemas"] = sorted(n for n in names if "/schemas/" in n)
    report["packaged_nets"] = sorted(n for n in names if "/nets/" in n)
    if not report["packaged_schemas"]:
        report["errors"].append("wheel has no schemas/*.json (contract would break when installed)")
    if not report["packaged_nets"]:
        report["errors"].append("wheel has no data/nets references")

    if not step("install wheel into a clean target dir",
                run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
                     "--target", str(TARGET), str(wheel)])):
        return fail()

    workdir = Path(tempfile.mkdtemp(prefix="cifkit-wheel-cwd-"))
    env = {"PYTHONPATH": str(TARGET), "PYTHONIOENCODING": "utf-8",
           "PYTHONDONTWRITEBYTECODE": "1"}
    probe = workdir / "probe.py"
    probe.write_text(r'''
import json, sys
import cifkit
from cifkit import api, cli, service, contract
from pathlib import Path
root = Path(cifkit.__file__).resolve().parent
print(json.dumps({
    "loaded_from": str(root),
    "is_target_copy": "dist_target" in str(root),
    "version": getattr(cifkit, "__version__", None),
    "api_version": getattr(api, "API_VERSION", None),
    "schemas": sorted(p.name for p in (root / "schemas").glob("*.json")),
    "nets": sorted(p.stem.replace("-reference", "") for p in (root / "data" / "nets").glob("*-reference.cif")),
    "capabilities_ok": bool(service.handle({"op": "capabilities"}).get("ok")),
}, ensure_ascii=False))
''', encoding="utf-8")
    proc = run([sys.executable, str(probe)], cwd=workdir, env=env)
    if not step("import + contract + service from the installed wheel", proc):
        return fail()
    try:
        report["probe"] = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        report["probe"] = None

    cli_proc = run([sys.executable, "-m", "cifkit", "formats"], cwd=workdir, env=env)
    if not step("CLI from the installed wheel", cli_proc):
        return fail()
    report["cli_formats"] = len([line for line in (cli_proc.stdout or "").splitlines()
                                 if line.strip()])

    topo_dir = Path(tempfile.mkdtemp(prefix="cifkit-wheel-topo-"))
    topo_probe = topo_dir / "topo.py"
    topo_probe.write_text('''
import json
from pathlib import Path
import cifkit
from pymatgen.core import Structure
from cifkit.topology import verify
nets = Path(cifkit.__file__).resolve().parent / "data" / "nets"
print(json.dumps({ref.stem.replace("-reference", ""):
                  bool(verify(Structure.from_file(str(ref)), ref.stem.replace("-reference", "")).get("ok"))
                  for ref in sorted(nets.glob("*-reference.cif"))}))
''', encoding="utf-8")
    topo_proc = run([sys.executable, str(topo_probe)], cwd=topo_dir, env=env)
    if not step("bundled topology data usable from the installed wheel", topo_proc):
        return fail()
    try:
        report["topology"] = json.loads((topo_proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        report["topology"] = None

    report["ok"] = not report["errors"]
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    print(f"\npackage check: {'PASS' if report['ok'] else 'FAIL'} — {args.json}")
    if report.get("probe"):
        print("probe:", json.dumps(report["probe"], ensure_ascii=False)[:400])
    if report.get("topology"):
        print("topology:", report["topology"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
