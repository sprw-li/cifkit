"""CLI/API JSON strictness + hidden-failure reporting (round 58, task-6).

Three things are pinned here, all on *error* paths:

* **Defect C**: RFC 8259 has no ``NaN``/``Infinity`` constants, but a structure
  with a non-finite lattice used to make ``cifkit validate --json`` print the
  bare literal ``NaN`` — so a strict consumer (``parse_constant`` hook,
  ``json.dumps(..., allow_nan=False)``, ``JSON.parse``) rejected the whole
  document.  Non-finite floats must become ``null``, ``ok`` must stay ``False``
  and the exit code must stay ``1``.
* **Unknown ``--spec`` keys** (lead's round-58 addition): a typo such as
  ``supercel`` must warn instead of silently falling back to the default.
* **Defect B**: non-JSON ``cifkit convert`` must print *why* a target failed
  (previously only the ``--json`` payload carried ``errors``).

The non-finite input is written inline by :data:`NAN_CIF` (valid cell lengths,
one ``nan`` angle) so the test is self-contained and runs on a clean checkout.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: valid cell lengths + one non-finite angle: pymatgen parses it, and the report
#: metrics end up with ``nan`` (this is the shape the adversarial fixture uses).
NAN_CIF = """data_C
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   5.0
_cell_length_b   5.0
_cell_length_c   5.0
_cell_angle_alpha   90.0
_cell_angle_beta   nan
_cell_angle_gamma   90.0
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
  C  C0  0.0  0.0  0.0
"""


def _reject_constant(name: str):
    """``parse_constant`` hook: any bare NaN/Infinity makes the parse fail."""
    raise ValueError(f"non-JSON constant {name}")


def _strict(text: str):
    """Parse ``text`` as strict RFC-8259 JSON (no NaN/Infinity tolerated)."""
    return json.loads(text, parse_constant=_reject_constant)


@pytest.fixture()
def nan_cif(tmp_path: Path) -> Path:
    path = tmp_path / "nan_angle.cif"
    path.write_text(NAN_CIF, encoding="utf-8")
    return path


def _cli(*argv: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "cifkit", *argv],
                          capture_output=True, text=True, encoding="utf-8",
                          cwd=ROOT, env=env, timeout=300)


# --------------------------------------------------------------- defect C: CLI
def test_validate_json_with_nonfinite_lattice_is_strict_json(nan_cif):
    """The acceptance judgement: exit 1 AND stdout parseable as strict JSON."""
    proc = _cli("validate", str(nan_cif), "--json")
    assert proc.returncode == 1, proc.stderr
    assert "NaN" not in proc.stdout, "bare NaN literal leaked to stdout"
    assert "Infinity" not in proc.stdout, "bare Infinity literal leaked to stdout"
    payload = _strict(proc.stdout)  # raises ValueError('NaN') before the fix
    assert payload["ok"] is False
    json.dumps(payload, allow_nan=False)  # must not raise either
    abc = payload["metrics"]["lattice"]["abc"]
    assert None in abc, f"non-finite cell length should be null, got {abc}"
    # the human-readable reason must survive (null must not hide the problem)
    assert any("nan" in check["detail"].lower() for check in payload["checks"])


def test_validate_json_strictness_survives_a_pipe(nan_cif):
    """Exactly the shape of the documented acceptance command."""
    proc = _cli("validate", str(nan_cif), "--json")
    checker = subprocess.run(
        [sys.executable, "-c",
         "import json,sys;"
         "json.loads(sys.stdin.read(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)));"
         "print('strict ok')"],
        input=proc.stdout, capture_output=True, text=True, encoding="utf-8", env={
            **os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60)
    assert checker.returncode == 0, checker.stderr
    assert "strict ok" in checker.stdout
    assert proc.returncode == 1, "validate must still fail for a non-finite cell"


def test_print_json_scrubs_non_finite_values(capsys):
    from cifkit.cli import _print_json

    _print_json({"a": [float("nan"), float("inf"), -float("inf"), 1.5],
                 "b": {"c": float("nan")}, "d": "text", "e": None})
    payload = _strict(capsys.readouterr().out)
    assert payload["a"] == [None, None, None, 1.5]  # finite value untouched
    assert payload["b"] == {"c": None}
    assert payload["d"] == "text" and payload["e"] is None


# --------------------------------------------------------------- defect C: API
def test_api_validate_returns_strictly_serialisable_dict(nan_cif):
    from cifkit import api

    result = api.validate(path=nan_cif)
    assert result["ok"] is False
    blob = json.dumps(result, allow_nan=False)  # must not raise
    assert "NaN" not in blob and "Infinity" not in blob
    assert None in result["metrics"]["lattice"]["abc"]
    # the checks still say what is wrong
    assert any("nan" in check["detail"].lower() for check in result["checks"])


def test_sanitize_nonfinite_handles_numpy_and_huge_ints():
    np = pytest.importorskip("numpy")
    from cifkit.api import sanitize_nonfinite

    out = sanitize_nonfinite({"x": np.float32("nan"), "y": np.float64("inf"),
                              "n": np.int64(3), "big": 10 ** 400,
                              "finite": np.float64(2.5), "s": "nan"})
    assert out["x"] is None and out["y"] is None
    assert out["n"] == 3
    assert out["big"] == 10 ** 400  # float()-ing it would overflow
    assert out["finite"] == 2.5
    assert out["s"] == "nan"  # strings are left alone


def test_sanitize_nonfinite_preserves_container_types():
    """Only non-finite floats may change: a tuple must stay a tuple."""
    from cifkit.api import sanitize_nonfinite

    out = sanitize_nonfinite({"t": (1.0, float("nan")), "l": [2.0, float("inf")]})
    assert out["t"] == (1.0, None) and isinstance(out["t"], tuple)
    assert out["l"] == [2.0, None] and isinstance(out["l"], list)


def test_streaming_ndjson_rows_are_strict_json(tmp_path):
    """A dataset row carrying NaN must be scrubbed before it becomes NDJSON."""
    from cifkit.api import stream_dataset_rows_ndjson

    (tmp_path / "dataset.jsonl").write_text(
        '{"run_id": "r0", "meta": {"run_id": "r0", "gap": NaN}}\n', encoding="utf-8")
    lines = list(stream_dataset_rows_ndjson(dataset_dir=tmp_path))
    assert len(lines) == 1
    assert "NaN" not in lines[0]
    row = _strict(lines[0])
    assert row["run_id"] == "r0" and row["gap"] is None


# ------------------------------------------- unknown --spec keys (round 58)
def _load_spec_args(spec_path: Path) -> argparse.Namespace:
    return argparse.Namespace(spec=str(spec_path), query=None, outdir=None, source=None,
                              format=None, topology=None, surface_frame=None, ingest=False)


def test_unknown_spec_key_warns_and_does_not_change_behaviour(tmp_path, capsys):
    from cifkit.cli import _load_spec

    spec_file = tmp_path / "spec.json"
    raw = {"topology": "sod", "supercel": [2, 2, 1]}
    spec_file.write_text(json.dumps(raw), encoding="utf-8")

    spec = _load_spec(_load_spec_args(spec_file))
    captured = capsys.readouterr()

    assert "supercel" in captured.err, "unknown key must be named on stderr"
    assert captured.out == "", "the warning must not pollute stdout"
    assert spec.spec_unknown_keys == ["supercel"]
    assert spec.spec_inputs == raw, "the raw JSON is still preserved verbatim"
    # the typo is ignored (default), not silently applied
    assert spec.supercell is None
    # ... and known keys keep working
    assert spec.topology == "sod"


def test_no_warning_when_every_key_is_known(tmp_path, capsys):
    from cifkit.cli import _load_spec

    spec_file = tmp_path / "spec.json"
    (spec_file).write_text(json.dumps({"topology": "sod", "vacuum": 15.0}), encoding="utf-8")
    spec = _load_spec(_load_spec_args(spec_file))
    captured = capsys.readouterr()
    assert captured.err == ""
    assert spec.spec_unknown_keys == []
    assert spec.vacuum == 15.0


def test_unknown_spec_keys_are_visible_in_the_json_payload(tmp_path, monkeypatch, capsys):
    """--json: warning on stderr, key list inside the result object, clean stdout."""
    from cifkit.cli import cmd_pipeline
    from cifkit.types import RunResult

    spec_file = tmp_path / "spec.json"
    (spec_file).write_text(json.dumps({"topology": "sod", "supercel": [2, 2, 1]}),
                           encoding="utf-8")

    def fake_run(spec, *, ingest_run=False):  # noqa: ARG001 - matches pipeline.run
        return RunResult(spec=spec, ok=True, outdir=tmp_path / "run")

    monkeypatch.setattr("cifkit.pipeline.run", fake_run)
    args = argparse.Namespace(spec=str(spec_file), query=None, outdir=str(tmp_path / "run"),
                              source=None, format=None, topology=None, surface_frame=None,
                              ingest=False, json=True, bundle=None)
    rc = cmd_pipeline(args)
    captured = capsys.readouterr()

    assert rc == 0
    payload = _strict(captured.out)  # stdout stays one strict JSON document
    assert payload["spec"]["spec_unknown_keys"] == ["supercel"]
    assert payload["spec"]["spec_inputs"]["supercel"] == [2, 2, 1]
    assert "supercel" in captured.err and "未知键" in captured.err
    assert "未知键" not in captured.out, "the warning must not be in the JSON document"


# ---------------------------------------------- defect B: convert error reason
def test_convert_non_json_reports_failed_targets_and_keeps_exit_1(tmp_path, monkeypatch, capsys):
    """`--to cif,lammps` where lammps refuses: stdout must name the failure.

    The refusal is simulated at the ``cifkit.export.write_structure`` seam so the
    test pins the *CLI reporting* contract without depending on which cells the
    real exporters happen to support (that is tested elsewhere).
    """
    import cifkit.export as export

    from cifkit.cli import cmd_convert

    src = ROOT / "tests" / "data" / "sod_zn_mof.cif"
    assert src.is_file(), src

    monkeypatch.setattr(export, "supported_formats",
                        lambda: {"cif": "cif", "lammps": "lammps"})

    def fake_write_structure(structure, path, fmt, title=None):  # noqa: ARG001
        if fmt == "lammps":
            raise ValueError("simulated refusal: tilt exceeds half the box")
        Path(path).write_text("data_x\n", encoding="utf-8")
        return str(path)

    monkeypatch.setattr(export, "write_structure", fake_write_structure)

    args = argparse.Namespace(file=[str(src)], to="cif,lammps", bundle="",
                              outdir=str(tmp_path / "out"), stem=None, title=None, json=False)
    rc = cmd_convert(args)
    out = capsys.readouterr().out

    assert rc == 1, "a failed target must still exit 1"
    assert "lammps" in out and "simulated refusal" in out, (
        "the single-file non-JSON branch must print the failing target and its reason; "
        f"stdout was:\n{out}")
    assert "  cif " in out, "the succeeding target is still listed"


def test_convert_non_json_batch_reports_failed_targets(tmp_path, monkeypatch, capsys):
    """The batch branch had the same gap for format failures (loads succeeded)."""
    import cifkit.export as export

    from cifkit.cli import cmd_convert

    src = tmp_path / "inputs"
    src.mkdir()
    for name in ("a", "b"):
        (src / f"{name}.cif").write_text(
            (ROOT / "tests" / "data" / "sod_zn_mof.cif").read_text(encoding="utf-8"),
            encoding="utf-8")

    monkeypatch.setattr(export, "supported_formats",
                        lambda: {"cif": "cif", "lammps": "lammps"})

    def fake_write_structure(structure, path, fmt, title=None):  # noqa: ARG001
        if fmt == "lammps" and path.name.startswith("a."):
            raise ValueError("simulated refusal for a.cif")
        Path(path).write_text("data_x\n", encoding="utf-8")
        return str(path)

    monkeypatch.setattr(export, "write_structure", fake_write_structure)

    args = argparse.Namespace(file=[str(src)], to="cif,lammps", bundle="",
                              outdir=str(tmp_path / "out"), stem=None, title=None, json=False)
    rc = cmd_convert(args)
    out = capsys.readouterr().out

    assert rc == 1
    assert "simulated refusal for a.cif" in out, out
    assert "1/2 ok" in out, out


# ------------------------- addition 3: reported files == files actually written
def _reported_paths(payload: dict, outdir: Path) -> set[str]:
    """The file set the JSON manifest claims, as paths relative to ``outdir``."""
    names = {str(Path(path).relative_to(outdir)) for path in payload["formats"].values()}
    names |= {str(Path(path).relative_to(outdir))
              for path in payload.get("companion_files") or []}
    for code, info in (payload.get("bundles") or {}).items():
        for name in (info.get("files") if isinstance(info, dict) else None) or []:
            names.add(str(Path(code) / name))
    return names


def _on_disk(directory: Path) -> set[str]:
    return {str(entry.relative_to(directory))
            for entry in directory.rglob("*") if entry.is_file()}


def test_convert_json_reports_the_files_it_wrote_for_dftb(tmp_path):
    """`--to dftb` is a *pair* (HSD + geo.gen); n_files must not say 1.

    The manifest is the contract a caller uses to decide whether the export is
    complete, so `reported == on disk` has to hold — otherwise a half-product
    (HSD without the geometry it references) looks finished.
    """
    src = ROOT / "tests" / "data" / "sod_zn_mof.cif"
    out = tmp_path / "dftb"

    proc = _cli("convert", str(src), "--to", "dftb", "--outdir", str(out), "--json")
    assert proc.returncode == 0, proc.stderr
    payload = _strict(proc.stdout)

    disk = _on_disk(out)
    assert len(disk) == 2 and any(name.endswith(".gen") for name in disk), disk
    assert _reported_paths(payload, out) == disk, (payload, disk)
    assert payload["n_files"] == len(disk) == 2, payload

    # re-running into the same directory rewrites the pair: it must still be reported
    again = _cli("convert", str(src), "--to", "dftb", "--outdir", str(out), "--json")
    assert again.returncode == 0, again.stderr
    payload2 = _strict(again.stdout)
    assert _reported_paths(payload2, out) == _on_disk(out) == disk, (payload2, _on_disk(out))
    assert payload2["n_files"] == 2, payload2


def test_convert_json_reported_set_matches_disk_with_several_formats(tmp_path):
    """Two formats + one sidecar: no cross-attribution, no undercount."""
    src = ROOT / "tests" / "data" / "sod_zn_mof.cif"
    out = tmp_path / "multi"

    proc = _cli("convert", str(src), "--to", "cif,dftb", "--outdir", str(out), "--json")
    assert proc.returncode == 0, proc.stderr
    payload = _strict(proc.stdout)

    disk = _on_disk(out)
    assert len(disk) == 3, disk
    assert _reported_paths(payload, out) == disk, (payload, disk)
    assert payload["n_files"] == len(disk) == 3, payload


def test_convert_json_reported_set_matches_disk_for_a_bundle(tmp_path):
    """`--bundle dftb`: every file on disk is reported (union of formats + bundle files).

    `write_bundle` now lists ``README.md`` itself (export-gate fixed the source), so
    there is nothing undeclared left for this export: ``companion_files`` is absent
    and `n_files` must still equal the file count on disk.
    """
    src = ROOT / "tests" / "data" / "sod_zn_mof.cif"
    out = tmp_path / "bundle"

    proc = _cli("convert", str(src), "--to", "cif", "--bundle", "dftb",
                "--outdir", str(out), "--json")
    assert proc.returncode == 0, proc.stderr
    payload = _strict(proc.stdout)

    disk = _on_disk(out)
    assert _reported_paths(payload, out) == disk, (payload, disk)
    assert payload["n_files"] == len(disk), (payload["n_files"], disk)
    # nothing undeclared -> the key is simply absent (not an empty list)
    companions = {str(Path(path).relative_to(out))
                  for path in payload.get("companion_files") or []}
    assert companions == set(), companions


def test_convert_cli_still_reports_undeclared_bundle_files(tmp_path, monkeypatch, capsys):
    """Defence in depth: an undeclared bundle file is still reported by the CLI.

    `write_bundle` lists everything it writes today, so the on-disk detection has
    no real target in this export — this pins that it *would* fire if a writer ever
    again omitted a file it wrote (which is how the README hole was found).
    """
    import cifkit.export as export

    from cifkit.cli import cmd_convert

    src = ROOT / "tests" / "data" / "sod_zn_mof.cif"
    out = tmp_path / "out"

    monkeypatch.setattr(export, "supported_formats", lambda: {"cif": "cif"})
    monkeypatch.setattr(export, "supported_bundles", lambda: {"fake": "fake bundle"})

    def fake_write_structure(structure, path, fmt, title=None):  # noqa: ARG001
        Path(path).write_text("data_x\n", encoding="utf-8")
        return str(path)

    def fake_write_bundle(structure, code, outdir, *, title=None):  # noqa: ARG001
        bundle_dir = Path(outdir)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "geo.gen").write_text("g\n", encoding="utf-8")
        (bundle_dir / "README.md").write_text("r\n", encoding="utf-8")
        return {"files": ["geo.gen"], "missing": []}  # README deliberately undeclared

    monkeypatch.setattr(export, "write_structure", fake_write_structure)
    monkeypatch.setattr(export, "write_bundle", fake_write_bundle)

    args = argparse.Namespace(file=[str(src)], to="cif", bundle="fake",
                              outdir=str(out), stem=None, title=None, json=True)
    assert cmd_convert(args) == 0
    payload = _strict(capsys.readouterr().out)

    disk = _on_disk(out)
    assert _reported_paths(payload, out) == disk, (payload, disk)
    assert payload["n_files"] == len(disk) == 3, payload
    companions = {str(Path(path).relative_to(out))
                  for path in payload.get("companion_files") or []}
    assert companions == {str(Path("fake") / "README.md")}, companions
