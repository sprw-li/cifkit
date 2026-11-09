"""One-command health check for the CIF workbench (used by review rounds / CI).

Runs, in order:
  1. cifkit selftest (offline imports + parser)
  2. pytest tests (full suite, includes the demo pipeline)
  3. scripts/verify_demo.py runs/demo_sod_zif8 (independent acceptance)
  4. agent-library router route on the demo sentence (must pick cif-workbench)
  5. agent-library eval_router --all (must keep 0 false positives)
  6. agent-library ci.py --fast
  7. agent-library check_skill on the cif-* skills (each must be errors=0)
  8. scripts/check_eol.py (hash-pinned files are LF; .gitattributes contract)
  9. scripts/sca_scan.py --strict (no copyleft *code* in our sources; MIT claim)

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
    DETAIL.append({
        "name": name,
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "seconds": round(dt, 1),
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-4000:],
    })
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-3:]
        return False, f"exit {proc.returncode} in {dt:.1f}s :: {' | '.join(err)[:400]}"
    return True, f"ok in {dt:.1f}s :: {tail_s}"


#: full output of every group, for the optional --json report
DETAIL: list[dict] = []

SKILL_CHECK = AGENTLIB / "catalog" / "skill-retro" / "scripts" / "check_skill.py"


def diagnose_agentlib_eval(stdout: str) -> str | None:
    """Explain an ``eval_router`` failure from its own output.

    The skill catalog lives in a *different* repository that other agents edit
    concurrently, so an eval failure is often "stale expectation", not a router
    regression.  This turns the raw JSON failure lines into a precise statement:

    * the wanted skill still exists in the catalog, but a *different* existing
      skill now ranks first  → ``stale-eval`` candidate (update the expectation);
    * the wanted skill is gone from the catalog → ``missing-skill`` (the eval
      references a deleted skill);
    * anything else → ``router-regression`` (investigate in the other repo).
    """
    catalog = AGENTLIB / "catalog"
    diagnoses: list[str] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            case = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        want = str(case.get("want") or "")
        got_ids = case.get("got_ids") or []
        wanted_skill = want.split("/")[-1].strip() if "/" in want else ""
        if not wanted_skill or not got_ids:
            continue
        wanted_exists = (catalog / wanted_skill).is_dir()
        top = str(got_ids[0])
        top_exists = (catalog / top).is_dir()
        if wanted_exists and top_exists and top != wanted_skill:
            diagnoses.append(
                f"stale-eval? 期望 {wanted_skill}，但目录里更专门的 {top} 被排在前面 "
                f"(query={case.get('query')!r})")
        elif not wanted_exists:
            diagnoses.append(
                f"missing-skill? 评测期望的 {wanted_skill} 已不在目录 (query={case.get('query')!r})")
        else:
            diagnoses.append(f"router-regression? {want!r} 未被命中，top={top}")
    if not diagnoses:
        return None
    head = ("外部仓库 D:\\agent-library 的目录/评测可能不一致；"
            "先确认哪一侧是新意图，再决定改目录还是改评测")
    return head + " :: " + " | ".join(diagnoses[:4])


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
        DETAIL.append({"name": f"check_skill {skill.name}",
                       "command": f"check_skill.py {skill}",
                       "exit_code": proc.returncode, "stdout_tail": out[-2000:],
                       "stderr_tail": (proc.stderr or "")[-2000:]})
        good = proc.returncode == 0 and "errors=0" in last
        ok_all = ok_all and good
        results.append(f"{skill.name}:{last or 'no output'}")
    return ok_all, f"{len(skills)} skills :: " + "; ".join(results)[:400]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the full pytest suite")
    ap.add_argument("--skip-agentlib", action="store_true")
    ap.add_argument("--json", default=None,
                    help="把每组状态与完整输出写成 JSON（失败排查用）")
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
        checks.append(("agentlib: router route", proc.returncode == 0 and first_is_workbench,
                       f"first-candidate-cif-workbench={first_is_workbench}; {route_detail}"))
        eval_ok, eval_detail = run(
            "eval", ["py", "-3", str(AGENTLIB / "scripts" / "eval_router.py"), "--all"],
            cwd=AGENTLIB)
        if not eval_ok:
            # the catalog lives in another repo: say *why* it failed, not just "exit 1"
            diagnosis = diagnose_agentlib_eval(next(
                (entry["stdout_tail"] for entry in reversed(DETAIL) if entry["name"] == "eval"), ""))
            if diagnosis:
                eval_detail = f"{eval_detail} :: {diagnosis}"
        checks.append(("agentlib: eval_router --all", eval_ok, eval_detail))
        checks.append(("agentlib: ci --fast", *run(
            "ci", ["py", "-3", str(AGENTLIB / "scripts" / "ci.py"), "--fast"], cwd=AGENTLIB)))

        skills_ok, skills_detail = check_skills()
        checks.append(("agentlib: check_skill cif-*", skills_ok, skills_detail))

    checks.append(("check_eol", *run(
        "eol", [str(PY), str(ROOT / "scripts" / "check_eol.py")], timeout=600)))

    checks.append(("sca_scan --strict", *run(
        "sca", [str(PY), str(ROOT / "scripts" / "sca_scan.py"), "--strict"], timeout=600)))

    if args.adversarial:
        checks.append(("adversarial_check", *run(
            "adversarial", [str(PY), str(ROOT / "scripts" / "adversarial_check.py")], timeout=2400)))

    print("\n== check_all ==")
    failed = 0
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name:22s} {detail}")
        failed += 0 if ok else 1
    agentlib_failures = [name for name, ok, _ in checks if not ok and name.startswith("agentlib:")]
    if agentlib_failures:
        print("\nNOTE: 以下组依赖另一个仓库 D:\\agent-library 的当前状态："
              + ", ".join(agentlib_failures))
        print("      该项目若正被并发修改（未提交的 intents/catalog 变动），路由评测可能与本工作台无关地失败；")
        print("      排查用 `--json` 报告里的 outputs[].stdout_tail（见 docs/PIPELINE.md §8.14）。")
    print(f"\n{len(checks) - failed}/{len(checks)} groups passed")
    if args.json:
        report = {
            "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "passed": len(checks) - failed,
            "total": len(checks),
            "groups": [{"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks],
            "outputs": DETAIL,
        }
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
