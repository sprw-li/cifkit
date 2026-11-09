"""One-command health check for the CIF workbench (used by review rounds / CI).

Runs, in order:
  1. cifkit selftest (offline imports + parser)
  2. pytest tests (full suite, includes the demo pipeline)
  3. scripts/verify_demo.py runs/demo_sod_zif8 (independent acceptance)
  4. agent-library router route on the demo sentence (must pick cif-workbench)
  5. agent-library eval_router --all (must keep 0 false positives)
  6. agent-library ci.py --fast
  7. agent-library check_skill on the cif-* skills (each must be errors=0)

Optional (``--adversarial``): scripts/adversarial_check.py, which tries to break the
convert/verify/rings behaviour instead of confirming it.

Usage::

    .venv\\Scripts\\python.exe scripts\\check_all.py [--fast] [--skip-agentlib]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
AGENTLIB = Path(r"D:\agent-library")
DEMO = (
    "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），"
    "沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。"
)


def run(name: str, cmd: list[str], *, cwd: Path = ROOT, timeout: int = 1800, env_extra: dict | None = None) -> tuple[bool, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout}s"
    dt = time.time() - t0
    tail = (proc.stdout or "").strip().splitlines()[-4:]
    tail_s = " | ".join(line.strip() for line in tail if line.strip())[:300]
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-3:]
        return False, f"exit {proc.returncode} in {dt:.1f}s :: {' | '.join(err)[:400]}"
    return True, f"ok in {dt:.1f}s :: {tail_s}"


SKILL_CHECK = AGENTLIB / "catalog" / "skill-retro" / "scripts" / "check_skill.py"


def check_skills() -> tuple[bool, str]:
    """Run agent-library ``check_skill.py`` on every ``cif-*`` skill.

    Keeps the workbench docs and the skill catalog from drifting apart: a skill
    whose manifest/body stops validating fails ``check_all`` and CI.
    """
    catalog = AGENTLIB / "catalog"
    skills = sorted(
        d for d in catalog.glob("cif-*")
        if d.is_dir() and (d / "SKILL.md").is_file()
    )
    if not SKILL_CHECK.is_file():
        return False, f"check_skill.py not found at {SKILL_CHECK}"
    if not skills:
        return False, "no cif-* skills found in the catalog"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    results: list[str] = []
    ok_all = True
    for skill in skills:
        proc = subprocess.run(
            ["py", "-3", str(SKILL_CHECK), str(skill)],
            cwd=str(AGENTLIB), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=300,
        )
        out = (proc.stdout or "").strip()
        last = out.splitlines()[-1] if out else ""
        good = proc.returncode == 0 and "errors=0" in last
        ok_all = ok_all and good
        results.append(f"{skill.name}:{last or 'no output'}")
    return ok_all, f"{len(skills)} skills :: " + "; ".join(results)[:400]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the full pytest suite")
    ap.add_argument("--skip-agentlib", action="store_true")
    ap.add_argument("--adversarial", action="store_true",
                    help="额外跑 scripts/adversarial_check.py（对抗性自检，较慢）")
    args = ap.parse_args()

    checks: list[tuple[str, bool, str]] = []

    checks.append(("selftest", *run("selftest", [str(PY), "-m", "cifkit", "selftest"])))

    if args.fast:
        checks.append(("pytest (fast: cli+spec)", *run(
            "pytest-fast", [str(PY), "-m", "pytest", "tests/test_spec.py", "tests/test_cli.py", "-q"])))
    else:
        checks.append(("pytest (full)", *run("pytest", [str(PY), "-m", "pytest", "tests", "-q"])))

    checks.append(("verify_demo", *run(
        "verify-demo", [str(PY), str(ROOT / "scripts" / "verify_demo.py"), str(ROOT / "runs" / "demo_sod_zif8")])))

    if not args.skip_agentlib and AGENTLIB.is_dir():
        route_ok, route_detail = run(
            "route",
            ["py", "-3", str(AGENTLIB / "router.py"), "route", "--agent", "dsh", DEMO],
            cwd=AGENTLIB,
        )
        # full-output check: the first candidate must be the workbench skill
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            ["py", "-3", str(AGENTLIB / "router.py"), "route", "--agent", "dsh", DEMO],
            cwd=str(AGENTLIB), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=300,
        )
        stdout = proc.stdout or ""
        first_is_workbench = "1. cif-workbench" in stdout
        checks.append(("router route", proc.returncode == 0 and first_is_workbench,
                       f"first-candidate-cif-workbench={first_is_workbench}; {route_detail}"))
        checks.append(("eval_router --all", *run(
            "eval", ["py", "-3", str(AGENTLIB / "scripts" / "eval_router.py"), "--all"], cwd=AGENTLIB)))
        checks.append(("ci --fast", *run(
            "ci", ["py", "-3", str(AGENTLIB / "scripts" / "ci.py"), "--fast"], cwd=AGENTLIB)))

        skills_ok, skills_detail = check_skills()
        checks.append(("check_skill cif-*", skills_ok, skills_detail))

    if args.adversarial:
        checks.append(("adversarial_check", *run(
            "adversarial", [str(PY), str(ROOT / "scripts" / "adversarial_check.py")], timeout=2400)))

    print("\n== check_all ==")
    failed = 0
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name:22s} {detail}")
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} groups passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
