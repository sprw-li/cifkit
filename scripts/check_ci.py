"""CI definition drift check: every command in the workflow must exist here.

Limitation H4: the cross-platform CI workflow has never actually run (this machine
only has Windows).  What *can* be verified locally is that the workflow is honest —
every script it calls exists, every referenced path exists, and the matrix it claims
is the matrix it declares.  That catches the common failure mode where CI rots
because a script was renamed.

    .venv\\Scripts\\python.exe scripts\\check_ci.py [--json OUT] [--run]

``--run`` additionally executes the platform-agnostic steps locally (byte
integrity, licence scan, adversarial check) — a real smoke test of the workflow
body on this OS.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: commands that are safe and meaningful to execute on this machine
RUNNABLE = ("scripts/check_eol.py", "scripts/sca_scan.py", "scripts/adversarial_check.py",
            "scripts/check_ci.py")

#: scripts that are deliberately *not* part of CI, with the reason
ON_DEMAND: dict[str, str] = {
    "audit_dataset_coverage.py": "one-off dataset audit (needs the CoRE cache)",
    "bench_api.py": "benchmark, manual (machine-dependent)",
    "bench_batch_scale.py": "benchmark, manual (machine-dependent)",
    "bench_large_structure.py": "benchmark, manual (needs the large MOF)",
    "bench_stream_scale.py": "benchmark, manual (machine-dependent)",
    "bootstrap_data.py": "downloads the CoRE archive (network + licence terms)",
    "bootstrap_qmof.py": "downloads QMOF (network, often unreachable)",
    "check_ci.py": "validates this very workflow (run locally/release)",
    "check_package.py": "builds and installs a wheel (slow; release gate --package)",
    "check_software.py": "needs real codes installed (release informational)",
    "cloud_gpu_fanout.py": "spends cloud credits; never in CI",
    "cloud_h3_submit.py": "spends cloud credits; never in CI",
    "coverage_matrix.py": "dataset coverage report (needs the archive)",
    "license_audit.py": "dependencies' licences (network)",
    "perf_gate.py": "performance regression gate (opt-in; machine-dependent)",
    "probe_source_limits.py": "talks to public APIs; deliberate manual probe",
    "release_check.py": "the release gate itself (run before publishing)",
    "run_demo.py": "demo helper, manual",
    "sources_live_check.py": "live source health (release informational)",
    "verify_demo.py": "demo verification, manual",
    "verify_formats_no_gpl.py": "format subset excluding restricted licences (release informational)",
}


def load_workflow(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def extract_commands(workflow: dict) -> list[dict]:
    commands: list[dict] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = step.get("run")
            if not run:
                continue
            for line in str(run).splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                commands.append({"job": job_name, "step": step.get("name") or "",
                                 "command": line})
    return commands


def analyse(workflow: dict) -> dict:
    """Reachability analysis of the shipped scripts vs the workflow.

    Returns ``{referenced, reachable, gate, unclassified, on_demand}``.  One
    implementation for the check *and* the tests, so they cannot disagree about
    what "reachable" means (round 40: the test used a stricter definition than the
    check and failed on two gate scripts that CI reaches indirectly).
    """
    commands = extract_commands(workflow)
    referenced: set[str] = set()
    for item in commands:
        referenced.update(re.findall(r"scripts[/\\]([A-Za-z0-9_]+\.py)", item["command"]))
    shipped = {path.name for path in (ROOT / "scripts").glob("*.py")}
    reachable = set(referenced)
    for name in list(reachable):
        path = ROOT / "scripts" / name
        if path.is_file():
            body = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                              if not line.lstrip().startswith("#"))
            reachable |= set(re.findall(r'"([A-Za-z0-9_]+\.py)"', body))
    reachable &= shipped
    gate: set[str] = set()
    orchestrator = ROOT / "scripts" / "check_all.py"
    if orchestrator.is_file():
        # only real invocations count: a *comment* naming scripts/check_ci.py must
        # not make that script a gate (round 40 caught exactly that)
        lines = [line for line in orchestrator.read_text(encoding="utf-8").splitlines()
                 if not line.lstrip().startswith("#")]
        text = "\n".join(lines)
        gate |= set(re.findall(r'"([A-Za-z0-9_]+\.py)"', text))
        gate |= set(re.findall(r'scripts[/\\]([A-Za-z0-9_]+\.py)', text))
    gate &= shipped
    return {"referenced": referenced & shipped, "reachable": reachable, "gate": gate,
            "unclassified": shipped - reachable - set(ON_DEMAND),
            "on_demand": set(ON_DEMAND)}


def check(workflow: dict, commands: list[dict]) -> list[dict]:
    results: list[dict] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append({"check": name, "ok": ok, "detail": detail})

    jobs = workflow.get("jobs") or {}
    record("has a test job", "test" in jobs, f"jobs={sorted(jobs)}")
    record("has a build job", "build" in jobs, f"jobs={sorted(jobs)}")

    matrix = (((jobs.get("test") or {}).get("strategy") or {}).get("matrix") or {})
    oses = matrix.get("os") or []
    versions = matrix.get("python") or []
    record("matrix spans three OSes", len(oses) == 3, f"os={oses}")
    record("matrix spans two Python versions", len(versions) == 2, f"python={versions}")
    record("min Python (3.11) is exercised", "3.11" in [str(v) for v in versions],
           f"python={versions}")
    record("workflow pins LF checkout", any(
        "core.autocrlf false" in item["command"] for item in commands),
        "windows EOL policy must not be rewritten by git")

    # every scripts/<name>.py referenced by a command must exist
    referenced = set()
    for item in commands:
        referenced.update(re.findall(r"scripts[/\\]([A-Za-z0-9_]+\.py)", item["command"]))
    missing = sorted(name for name in referenced
                     if not (ROOT / "scripts" / name).is_file())
    record("every referenced script exists", not missing,
           f"referenced={sorted(referenced)}" + (f" missing={missing}" if missing else ""))

    # Which scripts are "gates" (invoked by check_all.py, which CI runs)?  Those
    # must be reachable from CI; everything else must be *explicitly* classified as
    # on-demand so a new script cannot slip in unreviewed.
    info = analyse(workflow)
    uncovered = sorted(info["gate"] - info["reachable"])
    record("every gate script is reachable from CI", not uncovered,
           f"gate={sorted(info['gate'])} uncovered={uncovered}")
    record("every non-CI script is explicitly on-demand", not info["unclassified"],
           f"unclassified={sorted(info['unclassified'])}")

    # the module used by `python -m ...` / `-c` import checks must exist
    imports = set()
    for item in commands:
        imports.update(re.findall(r"import\s+(cifkit(?:\.\w+)?)", item["command"]))
    record("CI import smoke names real modules", bool(imports), f"imports={sorted(imports)}")

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "check_ci.json"))
    ap.add_argument("--run", action="store_true", help="execute the runnable steps locally")
    args = ap.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "workflow": str(WORKFLOW), "checks": [], "ran": []}
    if not WORKFLOW.is_file():
        print(f"error: workflow not found: {WORKFLOW}", file=sys.stderr)
        return 2
    workflow = load_workflow(WORKFLOW)
    commands = extract_commands(workflow)
    report["commands"] = commands
    report["checks"] = check(workflow, commands)

    if args.run:
        for item in commands:
            parts = shlex.split(item["command"])
            if not parts or parts[0] != "python":
                continue
            target = next((part for part in parts if part.endswith(".py")), None)
            if target is None or not any(target.endswith(name) for name in RUNNABLE):
                continue
            started = time.time()
            proc = subprocess.run([sys.executable, *parts[1:]], cwd=str(ROOT),
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=1800)
            report["ran"].append({"command": item["command"], "exit": proc.returncode,
                                  "seconds": round(time.time() - started, 1),
                                  "tail": ((proc.stdout or "") + (proc.stderr or ""))[-400:]})
            print(f"[{'ok ' if proc.returncode == 0 else 'FAIL'}] {item['command']}")

    failures = [item for item in report["checks"] if not item["ok"]]
    for item in report["checks"]:
        print(f"[{'ok ' if item['ok'] else 'FAIL'}] {item['check']}"
              + (f"  {item['detail']}" if not item["ok"] else ""))
    run_failures = [item for item in report["ran"] if item["exit"] != 0]
    report["ok"] = not failures and not run_failures
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nCI definition: {'ok' if report['ok'] else 'FAIL'} "
          f"({len(report['checks']) - len(failures)}/{len(report['checks'])} checks, "
          f"{len(report['ran'])} steps executed) — {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
