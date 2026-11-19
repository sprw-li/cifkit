"""One-command health check for the CIF workbench (used by review rounds / CI).

Runs, in order:
  1. cifkit selftest (offline imports + parser)
  2. pytest tests (full suite, includes the demo pipeline)
  3. scripts/verify_demo.py runs/demo_sod_zif8 (independent acceptance)
  4. scripts/check_skill.py on every ``skills/cif-*`` (each must be errors=0) — the
     eight skill bodies ship in this repository, so this needs no other checkout
  5. scripts/check_eol.py (hash-pinned files are LF; .gitattributes contract)
  6. scripts/sca_scan.py --strict (no copyleft *code* in our sources; MIT claim)
  7. scripts/check_bundles.py, scripts/verify_corpus.py, scripts/check_ci.py,
     scripts/check_portability.py

Optional extras:
  * ``--adversarial``: scripts/adversarial_check.py, which tries to break the
    convert/verify/rings behaviour instead of confirming it;
  * ``CIFKIT_AGENTLIB=<path>``: also exercise an *external* agent catalog's router /
    eval / ci.  Nothing in this project's acceptance depends on that checkout.

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

#: The ``cif-*`` skill bodies ship in this repository under ``skills/`` and are their
#: own source of truth: they are linted here, by `scripts/check_skill.py`, with no
#: other checkout involved.  ``CIFKIT_AGENTLIB`` optionally points at an *external*
#: agent catalog; only when it is set do the router/eval/ci checks for that catalog
#: run, and they are extras — this project's acceptance never depends on another repo.
AGENTLIB = Path(os.environ["CIFKIT_AGENTLIB"]) if os.environ.get("CIFKIT_AGENTLIB") else None
SKILLS_DIR = ROOT / "skills"
SKILL_CHECK = ROOT / "scripts" / "check_skill.py"


def diagnose_agentlib_eval(stdout: str, catalog: Path | None = None) -> str | None:
    """Explain an ``eval_router`` failure from its own output.

    Only used for the *optional* external-catalog extras: when ``CIFKIT_AGENTLIB``
    points at an agent catalog, its router eval can fail because that catalog was
    edited concurrently — "stale expectation", not a router regression.  This turns
    the raw JSON failure lines into a precise statement:

    * the wanted skill still exists in the catalog, but a *different* existing
      skill now ranks first  → ``stale-eval`` candidate (update the expectation);
    * the wanted skill is gone from the catalog → ``missing-skill`` (the eval
      references a deleted skill);
    * anything else → ``router-regression`` (investigate in that catalog).

    ``catalog`` defaults to ``$CIFKIT_AGENTLIB/catalog``; pass it explicitly from
    tests to stay hermetic.
    """
    if catalog is None:
        if AGENTLIB is None:
            return None
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
    head = ("外部 catalog（CIFKIT_AGENTLIB 指向的那个仓）的目录/评测可能不一致；"
            "先确认哪一侧是新意图，再决定改目录还是改评测")
    return head + " :: " + " | ".join(diagnoses[:4])


def check_skills() -> tuple[bool, str]:
    """Lint every ``skills/cif-*`` folder with the in-repo ``scripts/check_skill.py``.

    Keeps the skill bodies and their manifests from drifting apart: a skill whose
    manifest/body stops validating fails ``check_all`` and CI.  No external
    checkout is involved — this used to run a linter that lived in another
    repository, which made our gate depend on that repository's state.
    """
    skills = sorted(
        d for d in SKILLS_DIR.glob("cif-*")
        if d.is_dir() and (d / "SKILL.md").is_file()
    )
    if not SKILL_CHECK.is_file():
        return False, f"check_skill.py not found at {SKILL_CHECK}"
    if not skills:
        return False, f"no cif-* skills found in {SKILLS_DIR}"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    results: list[str] = []
    ok_all = True
    for skill in skills:
        proc = subprocess.run(
            [str(PY), str(SKILL_CHECK), str(skill)],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
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
    ap.add_argument("--skip-agentlib", action="store_true",
                    help="跳过 CIFKIT_AGENTLIB 指向的外部 catalog 附加检查（默认本就不跑）")
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
        # `--junitxml` so a failure of this *second* pytest pass (the one CI caught
        # flaking on windows/py3.13, after the standalone step had passed) leaves a
        # named evidence file instead of a bare exit code; the workflow uploads it.
        checks.append(("pytest (full)", *run(
            "pytest", [str(PY), "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
                       "--junitxml", str(ROOT / "runs" / "check_all_pytest.xml")])))

    checks.append(("verify_demo", *run(
        "verify-demo", [str(PY), str(ROOT / "scripts" / "verify_demo.py"), str(ROOT / "runs" / "demo_sod_zif8")])))

    skills_ok, skills_detail = check_skills()
    checks.append(("skills: check_skill cif-*", skills_ok, skills_detail))

    # Optional extras: only when the caller points CIFKIT_AGENTLIB at an external
    # agent catalog.  These are not part of this project's acceptance criteria — the
    # cif-* skills above are the ones this repository owns.
    if AGENTLIB is not None and AGENTLIB.is_dir():
        route_ok, route_detail = run(
            "route",
            [str(PY), str(AGENTLIB / "router.py"), "route", "--agent", "dsh", DEMO],
            cwd=AGENTLIB,
        )
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [str(PY), str(AGENTLIB / "router.py"), "route", "--agent", "dsh", DEMO],
            cwd=str(AGENTLIB), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=300,
        )
        stdout = proc.stdout or ""
        first_is_workbench = "1. cif-workbench" in stdout
        checks.append(("agentlib(extra): router route", proc.returncode == 0 and first_is_workbench,
                       f"first-candidate-cif-workbench={first_is_workbench}; {route_detail}"))
        eval_ok, eval_detail = run(
            "eval", [str(PY), str(AGENTLIB / "scripts" / "eval_router.py"), "--all"],
            cwd=AGENTLIB)
        if not eval_ok:
            diagnosis = diagnose_agentlib_eval(next(
                (entry["stdout_tail"] for entry in reversed(DETAIL) if entry["name"] == "eval"), ""))
            if diagnosis:
                eval_detail = f"{eval_detail} :: {diagnosis}"
        checks.append(("agentlib(extra): eval_router --all", eval_ok, eval_detail))
        checks.append(("agentlib(extra): ci --fast", *run(
            "ci", [str(PY), str(AGENTLIB / "scripts" / "ci.py"), "--fast"], cwd=AGENTLIB)))

    checks.append(("check_eol", *run(
        "eol", [str(PY), str(ROOT / "scripts" / "check_eol.py")], timeout=600)))

    checks.append(("sca_scan --strict", *run(
        "sca", [str(PY), str(ROOT / "scripts" / "sca_scan.py"), "--strict"], timeout=600)))

    # round 40: the bundle-consistency and portability gates were added recently;
    # wiring them here means CI covers them too (see scripts/check_ci.py, which
    # fails when a gate script is unreachable from the workflow).
    checks.append(("check_bundles", *run(
        "bundles", [str(PY), str(ROOT / "scripts" / "check_bundles.py")], timeout=900)))

    checks.append(("verify_corpus", *run(
        "corpus", [str(PY), str(ROOT / "scripts" / "verify_corpus.py"), "--limit", "8",
                   "--jobs", "4",
                   "--json", str(ROOT / "runs" / "corpus_verification_fast.json")],
        timeout=1800)))

    checks.append(("check_ci", *run(
        "ci", [str(PY), str(ROOT / "scripts" / "check_ci.py")], timeout=600)))

    checks.append(("check_portability", *run(
        "portability", [str(PY), str(ROOT / "scripts" / "check_portability.py")], timeout=900)))

    if args.adversarial:
        checks.append(("adversarial_check", *run(
            "adversarial", [str(PY), str(ROOT / "scripts" / "adversarial_check.py")], timeout=2400)))

    print("\n== check_all ==")
    failed = 0
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name:22s} {detail}")
        failed += 0 if ok else 1
    agentlib_failures = [name for name, ok, _ in checks
                         if not ok and name.startswith("agentlib(extra):")]
    if agentlib_failures:
        print("\nNOTE: 以下组是**可选**的外部 catalog 检查（CIFKIT_AGENTLIB 指向的另一个仓），"
              "不属于本项目的验收范围：" + ", ".join(agentlib_failures))
        print("      该外部仓若正被并发修改（未提交的 intents/catalog 变动），路由评测可能与本工作台无关地失败；")
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
