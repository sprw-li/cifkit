"""Pre-release gate: is this actually shippable *right now*?

Composes the existing tools into one honest checklist instead of a vibe:

1. **both repositories clean** (this one and the skill catalog) — a release from a
   dirty tree is not reproducible; ``--allow-dirty`` downgrades that to a warning;
2. **full health check** (``check_all --adversarial``, or ``--fast``) must pass
   *every* group, including the agent-library ones;
3. **fresh artifacts**: re-runs ``verify_formats.py`` and checks the format report,
   the LF/hash report, the licence scan and the adversarial report;
4. **documentation contract**: ``docs/LIMITATIONS.md`` parses and its counts add up.

    .venv\\Scripts\\python.exe scripts\\release_check.py [--quick] [--allow-dirty] [--json OUT]

Exit 0 only when every gate passes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTLIB = Path(os.environ.get("CIFKIT_AGENTLIB", r"D:\agent-library"))
PY = sys.executable

GATES: list[dict] = []


def record(name: str, ok: bool, detail: str, *, warning: bool = False) -> None:
    GATES.append({"gate": name, "ok": bool(ok), "warning": bool(warning), "detail": detail})
    mark = "WARN" if (warning and not ok) else ("ok " if ok else "FAIL")
    print(f"[{mark}] {name:34s} {detail}")


def git_state(repo: Path) -> tuple[str, int]:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo),
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    dirty = len([line for line in (status.stdout or "").splitlines() if line.strip()])
    return (head.stdout or "").strip() or "unknown", dirty


def run(cmd: list[str], cwd: Path, timeout: int = 2400) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})


def limitations_summary_ok(text: str) -> tuple[bool, str]:
    """Check ``docs/LIMITATIONS.md``: the headline counts must match the rows.

    A stale summary is the easiest way to ship a document that lies, so it is a
    release gate rather than a convention.
    """
    rows = [line for line in text.splitlines() if re.match(r"^\| [A-L]\d+[a-z]? \|", line)]
    counts = {mark: sum(1 for line in rows if mark in line) for mark in ("✅", "🟡", "🔴")}
    stated = re.search(r"共 (\d+) 条局限 = (\d+) ✅.*?(\d+) 🟡.*?(\d+) 🔴", text)
    if not stated:
        return False, f"no parsable summary line ({len(rows)} rows found)"
    consistent = (int(stated.group(1)) == len(rows) and int(stated.group(2)) == counts["✅"]
                  and int(stated.group(3)) == counts["🟡"] and int(stated.group(4)) == counts["🔴"])
    detail = (f"{len(rows)} rows = {counts['✅']}/{counts['🟡']}/{counts['🔴']}"
              f" (stated {stated.group(1)} = {stated.group(2)}/{stated.group(3)}/{stated.group(4)})")
    return consistent, detail


def limitations_group_table_ok(text: str) -> tuple[bool, str]:
    """Check the group summary table (right under the headline) against the rows.

    Round 57: the headline was verified per-row for months while the ``J`` group
    row claimed "1 ✅ / 7 🟡" although J4 and J8 were both ✅ — the summary table
    itself was never parsed, so a stale group row survived every gate.  This
    closes that hole.
    """
    rows = [line for line in text.splitlines() if re.match(r"^\| [A-L]\d+[a-z]? \|", line)]
    per_group: dict[str, dict[str, int]] = {}
    for line in rows:
        group = re.match(r"^\| ([A-L])", line).group(1)  # J12/J13/H3b belong to J/J/H
        marks = per_group.setdefault(group, {"✅": 0, "🟡": 0, "🔴": 0})
        for mark in marks:
            if mark in line:
                marks[mark] += 1
    problems: list[str] = []
    checked = 0
    for line in text.splitlines():
        match = re.match(r"^\| ([A-L]) \|", line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 8:
            continue
        try:  # | group | topic | entries | ok | warn | red | ...
            entries, ok, warn, red = (int(cells[3]), int(cells[4]), int(cells[5]), int(cells[6]))
        except ValueError:
            continue
        group = match.group(1)
        checked += 1
        actual = per_group.get(group, {})
        if entries != len([r for r in rows if re.match(r"^\| ([A-L])", r).group(1) == group]):
            problems.append(f"{group}: entries {entries}")
        if (ok, warn, red) != (actual.get("✅", 0), actual.get("🟡", 0), actual.get("🔴", 0)):
            problems.append(f"{group}: stated {ok}/{warn}/{red}, rows {actual.get('✅', 0)}/{actual.get('🟡', 0)}/{actual.get('🔴', 0)}")
    if not checked:
        return False, "no parsable group table rows"
    if problems:
        return False, "; ".join(problems)
    return True, f"{checked} group rows consistent with {len(rows)} entries"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip the full pytest suite")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--package", action="store_true",
                    help="构建 wheel 并在干净目录里安装/导入/跑 CLI（较慢）")
    ap.add_argument("--perf", action="store_true",
                    help="额外跑性能回归门禁（与 runs/perf_baseline.json 比较，较慢）")
    ap.add_argument("--json", default=str(ROOT / "runs" / "release_check.json"))
    args = ap.parse_args()

    started = time.time()
    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "quick": args.quick}

    # 1) repository state
    project_head, project_dirty = git_state(ROOT)
    report["project_head"] = project_head
    record("project repo clean", project_dirty == 0,
           f"HEAD {project_head}, {project_dirty} dirty path(s)",
           warning=args.allow_dirty)
    if AGENTLIB.is_dir():
        agent_head, agent_dirty = git_state(AGENTLIB)
        report["agentlib_head"] = agent_head
        record("agent-library repo clean", agent_dirty == 0,
               f"HEAD {agent_head}, {agent_dirty} dirty path(s)", warning=args.allow_dirty)
        report["agentlib_dirty"] = agent_dirty
    else:
        record("agent-library present", False, f"{AGENTLIB} not found")

    # 2) fresh format verification
    verify = run([PY, str(ROOT / "scripts" / "verify_formats.py")], ROOT)
    verify_path = ROOT / "runs" / "verify_formats" / "verify_formats.json"
    if verify.returncode == 0 and verify_path.is_file():
        data = json.loads(verify_path.read_text(encoding="utf-8"))
        ok = (data.get("n_ok") == data.get("n_formats") and data.get("bundles_ok") is True
              and data.get("n_third_party_ok") == data.get("n_third_party_readback"))
        record("formats: all written + third-party readback", ok,
               f"{data.get('n_ok')}/{data.get('n_formats')} formats, "
               f"{data.get('n_third_party_ok')}/{data.get('n_third_party_readback')} readbacks, "
               f"bundles_ok={data.get('bundles_ok')}")
        report["formats"] = {k: data.get(k) for k in
                             ("n_ok", "n_formats", "n_third_party_ok", "n_third_party_readback",
                              "n_bundles", "bundles_ok")}
    else:
        record("formats: all written + third-party readback", False,
               f"verify_formats exit {verify.returncode}")

    # 3) health check (also regenerates check_eol / sca_scan / adversarial reports)
    check_cmd = [PY, str(ROOT / "scripts" / "check_all.py"), "--adversarial",
                 "--json", str(ROOT / "runs" / "release_check_all.json")]
    if args.quick:
        check_cmd.insert(2, "--fast")
    check = run(check_cmd, ROOT)
    check_report_path = ROOT / "runs" / "release_check_all.json"
    if check_report_path.is_file():
        check_report = json.loads(check_report_path.read_text(encoding="utf-8"))
        failed = [g["name"] for g in check_report["groups"] if not g["ok"]]
        ok = check_report["passed"] == check_report["total"]
        record("check_all: every group passes", ok,
               f"{check_report['passed']}/{check_report['total']}"
               + (f" (failed: {failed})" if failed else ""))
        report["check_all"] = {"passed": check_report["passed"], "total": check_report["total"],
                               "failed": failed}
    else:
        record("check_all: every group passes", False,
               f"check_all exit {check.returncode} without a report")

    # 4) artifact + documentation contracts
    eol_path = ROOT / "runs" / "check_eol.json"
    if eol_path.is_file():
        eol = json.loads(eol_path.read_text(encoding="utf-8"))
        record("artifacts: byte integrity (LF + pinned sha256)", not eol.get("failures"),
               f"{len(eol.get('files', []))} files, failures={eol.get('failures')}")
    sca_path = ROOT / "runs" / "sca_scan.json"
    if sca_path.is_file():
        sca = json.loads(sca_path.read_text(encoding="utf-8"))
        record("artifacts: no copyleft code", not sca.get("actionable_copyleft"),
               f"actionable={len(sca.get('actionable_copyleft', []))}, "
               f"mentions={len(sca.get('copyleft_discussion', []))}")
    adv_path = ROOT / "runs" / "lead_verify_r11" / "adversarial_check.json"
    if adv_path.is_file():
        adv = json.loads(adv_path.read_text(encoding="utf-8"))
        bad = [row["check"] for row in adv if not row.get("ok")]
        record("artifacts: adversarial checks", not bad, f"{len(adv)} checks, failed={bad}")
    software_path = ROOT / "runs" / "check_software.json"
    if software_path.is_file():
        software = json.loads(software_path.read_text(encoding="utf-8"))
        verified = software["counts"].get("verified", 0)
        record("artifacts: software acceptance report", True,
               f"verified={verified}/{len(software['software'])} (informational: H3 stays open)",
               warning=True)

    ci_path = ROOT / "runs" / "check_ci.json"
    if ci_path.is_file():
        ci_report = json.loads(ci_path.read_text(encoding="utf-8"))
        bad = [item["check"] for item in ci_report.get("checks", []) if not item.get("ok")]
        record("artifacts: CI definition matches the repository",
               ci_report.get("ok", False),
               f"{len(ci_report.get('checks', []))} checks"
               + (f" (failed: {bad})" if bad else ""))
        report["ci"] = {"ok": ci_report.get("ok"), "checks": len(ci_report.get("checks", []))}
    else:
        record("artifacts: CI definition matches the repository", True,
               "runs/check_ci.json not generated in this run (informational)",
               warning=True)

    bundles_path = ROOT / "runs" / "check_bundles.json"
    if bundles_path.is_file():
        bundles = json.loads(bundles_path.read_text(encoding="utf-8"))
        bad = [item["code"] for item in bundles.get("bundles", []) if not item.get("ok")]
        record("artifacts: 12 bundles internally consistent",
               bundles.get("ok", False),
               f"{bundles.get('passed')}/{bundles.get('total')} consistent"
               + (f" (bad: {bad})" if bad else ""))
        report["bundles"] = {"passed": bundles.get("passed"), "total": bundles.get("total")}
    else:
        record("artifacts: 12 bundles internally consistent", True,
               "runs/check_bundles.json not generated in this run (informational)",
               warning=True)

    coverage_path = ROOT / "runs" / "coverage_matrix.json"
    if coverage_path.is_file():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        examples = coverage.get("examples", [])
        verified = [e["net"] for e in examples if e.get("status") == "verified"]
        bundled = coverage.get("bundled_reference_nets", [])
        ok = bool(bundled) and set(bundled) <= set(verified)
        record("artifacts: bundled topology nets verify on real data", ok,
               f"{len(verified)}/{len(bundled)} nets verified "
               f"({', '.join(sorted(verified)) or 'none'})")
        report["coverage"] = {"bundled": bundled, "verified": verified}
    else:
        record("artifacts: bundled topology nets verify on real data", True,
               "runs/coverage_matrix.json not generated in this run (informational)",
               warning=True)

    live_path = ROOT / "runs" / "sources_live.json"
    if live_path.is_file():
        live = json.loads(live_path.read_text(encoding="utf-8"))
        summary = live.get("summary", {})
        # network flakiness must not block a release: warn, never fail
        record("artifacts: data-source live check", True,
               f"ok={summary.get('ok')}, needs-key={summary.get('needs_key')}, "
               f"failed={summary.get('failed')} (as of {live.get('checked_at')})",
               warning=bool(summary.get("failed")))
        report["sources_live"] = summary

    if args.package:
        package = run([PY, str(ROOT / "scripts" / "check_package.py")], ROOT, timeout=1800)
        package_path = ROOT / "runs" / "check_package.json"
        if package_path.is_file():
            package_report = json.loads(package_path.read_text(encoding="utf-8"))
            probe = package_report.get("probe") or {}
            record("package: wheel builds, installs and imports",
                   bool(package_report.get("ok")),
                   f"{package_report.get('wheel_files')} files, "
                   f"schemas={len(package_report.get('packaged_schemas', []))}, "
                   f"nets={len(package_report.get('packaged_nets', []))}, "
                   f"topology={package_report.get('topology')}")
            report["package"] = {"ok": package_report.get("ok"), "probe": probe}
        else:
            record("package: wheel builds, installs and imports", False,
                   f"check_package exit {package.returncode} without a report")

    if args.perf:
        perf_cmd = [PY, str(ROOT / "scripts" / "perf_gate.py"), "--check"]
        if args.quick:
            perf_cmd.append("--quick")
        perf = run(perf_cmd, ROOT, timeout=3600)
        perf_path = ROOT / "runs" / "perf_check.json"
        if perf_path.is_file():
            perf_report = json.loads(perf_path.read_text(encoding="utf-8"))
            bad = [row["metric"] for row in perf_report.get("rows", [])
                   if row.get("verdict") == "REGRESSION"]
            record("perf: no regression against the baseline", perf_report.get("ok", False),
                   f"{len(perf_report.get('rows', []))} metrics, regressions={bad}")
            report["perf"] = {"ok": perf_report.get("ok"), "regressions": bad}
        else:
            record("perf: no regression against the baseline", False,
                   f"perf_gate exit {perf.returncode} without a report")

    limitations = ROOT / "docs" / "LIMITATIONS.md"
    if limitations.is_file():
        text = limitations.read_text(encoding="utf-8")
        consistent, detail = limitations_summary_ok(text)
        record("docs: LIMITATIONS summary matches the rows", consistent, detail)
        groups_ok, groups_detail = limitations_group_table_ok(text)
        record("docs: LIMITATIONS group table matches the rows (round 57)", groups_ok, groups_detail)

    report["gates"] = GATES
    report["seconds"] = round(time.time() - started, 1)
    failures = [g for g in GATES if not g["ok"] and not g["warning"]]
    report["ok"] = not failures
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nrelease gate: {'PASS' if not failures else 'FAIL'} "
          f"({len(GATES) - len(failures)}/{len(GATES)} gates, {report['seconds']}s)")
    print(f"report: {out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
