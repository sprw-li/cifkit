"""Adversarial round-10 self-verification (Lead-run; the delegated reviewer agent failed).

Unlike ``tests/`` which asserts intended behaviour, this script tries to BREAK the
four round-10 changes: single vs batch convert semantics, duplicate stems, bad
inputs, unknown bundles, whether ``verify_formats`` can be fooled, ring-count
semantics cross-checked against an independent formula, and whether the
``check_all`` skill group is really wired to the external script.

    .venv\\Scripts\\python.exe scripts\\adversarial_check.py [--work DIR]

Exit code 0 when every check passes; 1 otherwise.  Results are written to
``<work>/adversarial_check.json``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"

results: list[tuple[str, bool, str]] = []


def load_reference() -> float:
    """Pure-Python loop; printed so a slow run can be attributed to the machine.

    Round 27: a release gate on a loaded box timed out a 900 s subprocess on a
    command that normally takes 1.3 s.  Recording the load keeps that diagnosable.
    """
    started = time.perf_counter()
    total = 0
    for i in range(3_000_000):
        total += i * i % 97
    return time.perf_counter() - started


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")


def run(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), "-m", "cifkit", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def loads(text: str) -> dict:
    raw = text.encode("utf-8", "surrogatepass")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return json.loads(raw.decode("utf-16"))
    return json.loads(text.lstrip("\ufeff"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(ROOT / "runs" / "lead_verify_r11"))
    args = ap.parse_args()
    print(f"[load] pure-Python control loop: {load_reference():.2f}s "
          f"(baseline ~0.3s; a much larger value means the machine is loaded)")
    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 1) convert
    single = work / "single"
    proc = run(["convert", str(ZIF8), "--to", "vasp,xyz", "--outdir", str(single), "--json"])
    data = loads(proc.stdout)
    check("convert single: exit 0 + files at outdir root",
          proc.returncode == 0 and (single / f"{ZIF8.stem}.vasp").is_file()
          and (single / f"{ZIF8.stem}.xyz").is_file() and "runs" not in data,
          f"exit={proc.returncode} files={sorted(p.name for p in single.iterdir())}")

    # single input + --stem keeps the round-9 flat behaviour (outdir/X.vasp)
    stem_out = work / "stem"
    proc = run(["convert", str(ZIF8), "--to", "vasp", "--stem", "myslab",
                "--outdir", str(stem_out), "--json"])
    check("convert single + --stem stays flat (outdir/myslab.vasp, no subdir)",
          proc.returncode == 0 and (stem_out / "myslab.vasp").is_file()
          and not (stem_out / "myslab").exists(),
          f"contents={sorted(p.name for p in stem_out.iterdir())}")

    # a *directory* argument always means batch, even with a single CIF inside
    one_dir = work / "one_cif"
    one_dir.mkdir()
    shutil.copyfile(ZIF8, one_dir / "only.cif")
    proc = run(["convert", str(one_dir), "--to", "vasp", "--outdir", str(work / "one_out"), "--json"])
    data = loads(proc.stdout)
    check("convert dir-with-one-cif is batch (manifest + subdir)",
          proc.returncode == 0 and data["n_inputs"] == 1 and "runs" in data
          and (work / "one_out" / "convert_manifest.json").is_file()
          and (work / "one_out" / "only" / "only.vasp").is_file(),
          f"n_inputs={data['n_inputs']} manifest={(work / 'one_out' / 'convert_manifest.json').is_file()}")

    batch_src = work / "src"
    batch_src.mkdir()
    shutil.copyfile(ZIF8, batch_src / "a.cif")
    shutil.copyfile(ZIF8, batch_src / "b.CIF")
    shutil.copyfile(ZIF8, batch_src / "c.cif")
    out = work / "batch"
    proc = run(["convert", str(batch_src), "--to", "vasp", "--outdir", str(out), "--json"])
    data = loads(proc.stdout)
    check("convert batch: case-insensitive dedupe (3 inputs, not 6)",
          proc.returncode == 0 and data["n_inputs"] == 3 and data["n_ok"] == 3,
          f"n_inputs={data['n_inputs']} n_ok={data['n_ok']}")
    manifest = json.loads((out / "convert_manifest.json").read_text(encoding="utf-8"))
    check("convert batch: manifest has per-run outdir",
          all("outdir" in r and Path(r["outdir"]).is_dir() for r in manifest["runs"]),
          f"run outdirs={[Path(r['outdir']).name for r in manifest['runs']]}")

    # stem collision across two directories must NOT overwrite (explicit file list)
    coll = work / "coll"
    (coll / "d1").mkdir(parents=True)
    (coll / "d2").mkdir(parents=True)
    shutil.copyfile(ZIF8, coll / "d1" / "same.cif")
    shutil.copyfile(ZIF8, coll / "d2" / "same.cif")
    proc = run(["convert", str(coll / "d1" / "same.cif"), str(coll / "d2" / "same.cif"),
                "--to", "vasp", "--outdir", str(work / "coll_out"), "--json"])
    data = loads(proc.stdout)
    written = sorted(p.name for p in (work / "coll_out").glob("*/same*.vasp"))
    check("convert batch: same stem from two dirs is disambiguated (2 distinct outputs)",
          data["n_inputs"] == 2 and data["n_ok"] == 2 and len(written) == 2,
          f"n_inputs={data['n_inputs']} outputs={written}")

    # nested directories are NOT scanned recursively (documented behaviour)
    proc = run(["convert", str(coll), "--to", "vasp", "--outdir", str(work / "nested"), "--json"])
    check("convert batch: nested dirs without top-level *.cif -> clear error",
          proc.returncode != 0 and "没有" in (proc.stderr or ""),
          f"exit={proc.returncode} stderr={proc.stderr.strip()[:70]}")

    mixed = work / "mixed"
    mixed.mkdir()
    shutil.copyfile(ZIF8, mixed / "good.cif")
    (mixed / "bad.cif").write_text("not a cif\n", encoding="utf-8")
    proc = run(["convert", str(mixed), "--to", "vasp", "--outdir", str(work / "mixed_out"), "--json"])
    data = loads(proc.stdout)
    check("convert: bad input -> exit 1 but good input converted",
          proc.returncode == 1 and data["n_ok"] == 1 and data["n_failed"] == 1
          and (work / "mixed_out" / "good" / "good.vasp").is_file(),
          f"exit={proc.returncode} ok={data['n_ok']} failed={data['n_failed']}")

    proc = run(["convert", str(ZIF8), "--bundle", "nope", "--outdir", str(work / "ub"), "--json"])
    check("convert: unknown bundle -> exit 2 with available list",
          proc.returncode == 2 and "bundle" in (proc.stderr or "").lower(),
          f"exit={proc.returncode} stderr={proc.stderr.strip()[:80]}")

    # ---------------------------------------------------- 2) verify_formats
    vf_out = work / "vf"
    proc = subprocess.run([str(PY), str(ROOT / "scripts" / "verify_formats.py"),
                           "--outdir", str(vf_out)],
                          cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                          timeout=1800)
    report = json.loads((vf_out / "verify_formats.json").read_text(encoding="utf-8"))
    check("verify_formats: full run 31/31 + 25 third-party + 12 bundles",
          proc.returncode == 0 and report["n_ok"] == 31 and report["n_third_party_ok"] == 25
          and report["n_bundles"] == 12 and report["bundles_ok"] is True,
          f"formats={report['n_ok']}/{report['n_formats']} "
          f"tp={report['n_third_party_ok']}/{report['n_third_party_readback']} "
          f"bundles_ok={report['bundles_ok']}")
    readers = {r["format"]: r["reader"] for r in report["formats"]}
    templates = {f for f, r in readers.items() if r == "structural-check"}
    check("verify_formats: templates labelled, not claimed as read-back",
          templates == {"cp2k", "siesta", "abacus", "orca", "dftb"} and "软件接受" in report["note"],
          f"templates={sorted(templates)}")

    from pymatgen.core import Lattice, Structure

    bad_cif = vf_out / "corrupt.cif"
    bad_cif.write_text("data_bad\n_cell_length_a 1\n", encoding="utf-8")
    try:
        Structure.from_file(str(bad_cif))
        corrupt_detected = False
    except Exception:  # noqa: BLE001
        corrupt_detected = True
    check("verify_formats premise: a corrupt CIF is actually rejected by the reader",
          corrupt_detected, "pymatgen raised on the truncated file")

    # -------------------------------------------------- 3) ring statistics
    from cifkit.features import extract_features
    from cifkit.topology import ring_statistics

    diamond = Structure(Lattice.cubic(3.567), ["C"] * 8,
                        [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0],
                         [.25, .25, .25], [.25, .75, .75], [.75, .25, .75], [.75, .75, .25]])
    stats = ring_statistics(diamond)
    check("ring_statistics: diamond 6-rings == 16/cell (independent formula 8*12/6)",
          stats["rings_per_cell"]["6"] == 16.0 and stats["n_bonds"] == 16
          and stats["truncated"] is False,
          f"6-rings={stats['rings_per_cell']['6']} bonds={stats['n_bonds']}")
    sums = {k: round(v * int(k), 3) for k, v in stats["rings_per_cell"].items()}
    check("ring_statistics: canonical rings (size*per_cell integral)",
          all(abs(v - round(v)) < 1e-6 for v in sums.values()), f"size*per_cell={sums}")

    tiny = Structure(Lattice.cubic(3.0), ["C"], [[0, 0, 0]])
    check("ring_statistics: isolated atom -> zero rings, no crash",
          ring_statistics(tiny)["rings_per_cell"]["6"] == 0.0,
          f"result={ring_statistics(tiny)['rings_per_cell']}")

    big = Structure(Lattice.cubic(30.0), ["C"] * 700, [[i / 700, 0, 0] for i in range(700)])
    big_stats = ring_statistics(big)
    check("ring_statistics: >600 atoms returns truncated instead of running",
          big_stats["truncated"] is True and big_stats["ring_sizes"] == [],
          f"truncated={big_stats['truncated']} warnings={big_stats['warnings'][:1]}")

    fz = extract_features(Structure.from_file(str(ZIF8)), rdf=False, rings=True)
    fd = extract_features(diamond, rdf=False, rings=True)
    check("features --rings: metal vs non-metal basis",
          fz["ring_basis"] == "metal-net" and fd["ring_basis"] == "full-bond-graph"
          and json.loads(fd["rings_per_cell"])["6"] == 16.0,
          f"zif8={fz['ring_basis']} diamond={fd['ring_basis']}")

    # ------------------------------------------- 3b) embedding interface
    from cifkit.contract import OP_SCHEMAS, validate_request, validate_response
    from cifkit.service import OPS, handle

    check("contract: schemas cover every op",
          set(OP_SCHEMAS) == set(OPS),
          f"ops={sorted(OPS)}")
    violated = handle({"op": "features", "params": {"rdf_bins": 0, "api_key": "SECRET"}})
    blob = json.dumps(violated, ensure_ascii=False)
    check("service: contract violation -> 400 with JSON paths + no secret leak",
          violated["http_status"] == 400
          and violated["error"]["code"] == "invalid-request"
          and any("rdf_bins" in v for v in violated["error"]["detail"]["violations"])
          and "SECRET" not in blob,
          f"violations={violated['error']['detail']['violations']}")
    ok_response = handle({"op": "features", "params": {"path": str(ZIF8), "rdf": False}})
    check("service: successful response satisfies RESPONSE_SCHEMA",
          ok_response["ok"] is True and validate_response(ok_response) == []
          and validate_request({"op": "features", "params": {"path": str(ZIF8)}}) == [],
          f"natoms={ok_response['data']['natoms']}")

    # ------------------------------------------- 3c) hosting guard
    import tempfile as _tempfile

    from cifkit.platform import GuardedService, Policy

    box = Path(_tempfile.mkdtemp(prefix="cifkit-adv-"))
    (box / "uploads").mkdir()
    (box / "work").mkdir()
    shutil.copyfile(ZIF8, box / "uploads" / "a.cif")
    (box / "secret.cif").write_bytes(ZIF8.read_bytes())
    guarded = GuardedService(Policy(read_roots=[str(box / "uploads")],
                                    write_roots=[str(box / "work")],
                                    allow_network=False, timeout_s=120))
    inside = guarded.handle({"op": "features", "params": {"path": str(box / "uploads" / "a.cif"),
                                                          "rdf": False}})
    outside = guarded.handle({"op": "features", "params": {"path": str(box / "secret.cif")}})
    traversal = guarded.handle({"op": "features",
                                "params": {"path": str(box / "uploads" / ".." / "secret.cif")}})
    check("platform: sandbox blocks outside + traversal, allows inside",
          inside["ok"] is True and outside["error"]["code"] == "forbidden-path"
          and traversal["error"]["code"] == "forbidden-path"
          and outside["http_status"] == 403,
          f"inside={inside['ok']} outside={outside['error']['code']} traversal={traversal['error']['code']}")
    offline = guarded.handle({"op": "fetch", "params": {"source": "cod", "structure_id": "7111973"}})
    check("platform: network disabled by policy -> 403 network-disabled",
          offline["error"]["code"] == "network-disabled" and offline["http_status"] == 403,
          f"code={offline['error']['code']}")
    write_out = guarded.handle({"op": "convert", "params": {"path": str(box / "uploads" / "a.cif"),
                                                            "formats": ["vasp"], "outdir": str(box / "elsewhere")}})
    check("platform: writes outside the write root are refused",
          write_out["error"]["code"] == "forbidden-path",
          f"code={write_out['error']['code']}")
    guarded.shutdown()

    # ------------------------------------------- 3d) dataset streaming + paging
    import tempfile as _tf

    from cifkit import api as _api
    from cifkit.dataset import build_dataset as _build

    ds_root = Path(_tf.mkdtemp(prefix="cifkit-adv-ds-"))
    runs = ds_root / "runs"
    for index in range(7):
        # NOTE: do not name this `run` — that would shadow the module-level run() helper
        run_dir = runs / f"run{index}"
        run_dir.mkdir(parents=True)
        shutil.copyfile(ZIF8, run_dir / "standardized.cif")
        (run_dir / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(run_dir / "standardized.cif")},
            "source": {"source": "local", "record": {"record_id": f"local:{index}"}},
        }), encoding="utf-8")
    streamed = _build(runs, ds_root / "s", rdf=False, stream=True)
    material = _build(runs, ds_root / "m", rdf=False, stream=False)

    def _norm(path, outdir):
        text = path.read_text(encoding="utf-8-sig")
        return text.replace(json.dumps(str(outdir))[1:-1], "<OUT>").replace(str(outdir), "<OUT>")

    check("dataset: stream == materialised (CSV/JSONL, path-normalised)",
          _norm(ds_root / "s" / "dataset.csv", ds_root / "s")
          == _norm(ds_root / "m" / "dataset.csv", ds_root / "m")
          and _norm(ds_root / "s" / "dataset.jsonl", ds_root / "s")
          == _norm(ds_root / "m" / "dataset.jsonl", ds_root / "m"),
          f"n_ok stream={streamed['n_ok']} materialised={material['n_ok']}")
    check("dataset: streaming holds one row, materialised holds all",
          streamed["max_rows_held"] == 1 and material["max_rows_held"] == material["n_runs"],
          f"max_rows_held={streamed['max_rows_held']} vs {material['max_rows_held']}")

    pages = [_api.dataset_rows(dataset_dir=ds_root / "s", offset=off, limit=3)
             for off in (0, 3, 6)]
    ids = [row["run_id"] for page in pages for row in page["rows"]]
    check("dataset_rows: paging covers every row exactly once",
          ids == [f"run{i}" for i in range(7)] and pages[0]["total"] == 7
          and pages[2]["has_more"] is False,
          f"ids={ids} total={pages[0]['total']} has_more_last={pages[2]['has_more']}")

    # ------------------------------------------- 3e) rate limiting (A6)
    import http.server as _http_server
    import threading as _threading

    from cifkit.sources.http import HttpClient, HttpError

    _state = {"statuses": [429, 503], "retry_after": "0", "hits": 0}

    class _Handler(_http_server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            _state["hits"] += 1
            status = _state["statuses"].pop(0) if _state["statuses"] else 200
            self.send_response(status)
            if status in (429, 503):
                self.send_header("Retry-After", _state["retry_after"])
            body = b"ok" if status == 200 else b"throttled"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # noqa: D102
            return

    _server = _http_server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _thread = _threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    _base = f"http://127.0.0.1:{_server.server_address[1]}"
    try:
        sleeps: list[float] = []
        client = HttpClient(retries=4, jitter=0.0, base_backoff=9.0,
                            sleeper=lambda s: sleeps.append(s))
        body = client.get(f"{_base}/x")
        check("rate-limit: 429+503 are retried and Retry-After wins over backoff",
              body == b"ok" and _state["hits"] == 3 and sleeps == [0.0, 0.0],
              f"hits={_state['hits']} sleeps={sleeps}")

        _state["statuses"] = [404, 200]
        _state["hits"] = 0
        fails_fast = HttpClient(retries=4, sleeper=lambda s: None)
        try:
            fails_fast.get(f"{_base}/missing")
            status_404 = False
        except HttpError as exc:
            status_404 = exc.status == 404 and exc.retryable is False
        check("rate-limit: 404 is not retried (exactly one request, no sleep)",
              status_404 and _state["hits"] == 1,
              f"hits={_state['hits']} status_404={status_404}")
    finally:
        _server.shutdown()
        _server.server_close()
        _thread.join(timeout=5)

    # ------------------------------------------- 3f) organometallic M–C (C3)
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
    from cifkit.repair.bonds import hydrogen_demand as _demand, perceive_bonds as _perceive
    from organometallic import carboxylate_like as _acetate, ferrocene as _ferrocene

    fe_graph = _perceive(_ferrocene())
    fe_h = sum(max(0, d.missing) for d in _demand(fe_graph))
    acetate_graph = _perceive(_acetate(zr_c=2.50))
    check("organometallic: ferrocene gets 10 Fe–C bonds and 0 bogus H",
          fe_graph.organometallic_bonds == 10 and fe_h == 0,
          f"M–C={fe_graph.organometallic_bonds} bogus_H={fe_h}")
    check("organometallic: saturated carboxylate carbon rejects a 2.5 Å Zr···C contact",
          acetate_graph.organometallic_bonds == 0,
          f"kept M–C bonds={acetate_graph.organometallic_bonds}")

    # ---------------------------------------------------- 4) check_all group
    text = (ROOT / "scripts" / "check_all.py").read_text(encoding="utf-8")
    check("check_all: check_skill group wired to the real script",
          "check_skill.py" in text and "check_skills()" in text
          and 'agentlib: check_skill' in text and "--skip-agentlib" in text,
          "helper runs catalog/skill-retro/scripts/check_skill.py over cif-* skills")

    print("\n== summary ==")
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("failed:", failed)
    (work / "adversarial_check.json").write_text(
        json.dumps([{"check": n, "ok": ok, "detail": d} for n, ok, d in results],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
