"""Internal consistency of the 12 computation-software bundles.

A bundle is only useful if its files agree with each other: DFTB+'s ``dftb_in.hsd``
must point at the ``geo.gen`` that ships next to it, LAMMPS's ``in.min`` must read
the ``data.lammps`` we wrote, QE's ``pw.in`` must name exactly the UPFs that
``PSEUDO.readme`` tells the user to supply, and everything the bundle *claims* is
missing must really be absent.

``check_bundle`` encodes those contracts.  It is an in-house check (no external
reader required) and complements ``template_check`` (which validates each file's
own content).
"""
from __future__ import annotations

import re
from pathlib import Path

#: per bundle: required files, cross-file references, and tokens that the
#: declared ``missing`` list must mention
RULES: dict[str, dict] = {
    "vasp": {"required": ["POSCAR", "INCAR", "KPOINTS"],
             "missing_must_mention": ["POTCAR"]},
    "qe": {"required": ["pw.in", "PSEUDO.readme"],
           "missing_must_mention": ["UPF"]},
    "cp2k": {"required": ["cp2k.inp"],
             "missing_must_mention": ["BASIS_SET"]},
    "dftb": {"required": ["dftb_in.hsd", "geo.gen", "SLKO.readme"],
             "refs": [("dftb_in.hsd", r'<<<\s*"([^"]+)"', "geo.gen")],
             "missing_must_mention": ["Slater-Koster"]},
    "lammps": {"required": ["data.lammps", "in.min"],
               "refs": [("in.min", r"read_data\s+(\S+)", "data.lammps")],
               "missing_must_mention": ["force field"]},
    "orca": {"required": ["orca.inp"],
             "missing_must_mention": ["basis"]},
    "nwchem": {"required": ["mol.nw"],
               "missing_must_mention": ["basis"]},
    "siesta": {"required": ["structure.fdf"],
               "missing_must_mention": ["pseudopotential"]},
    "abacus": {"required": ["STRU", "INPUT.readme"],
               "missing_must_mention": ["INPUT"]},
    "aims": {"required": ["geometry.in", "control.readme"],
             "missing_must_mention": ["control.in"]},
    "gromacs": {"required": ["conf.gro", "md.mdp", "topol.top", "TOP.readme"],
                # the shipped .top is a skeleton; the *force field* is still missing
                "missing_must_mention": ["atom types"]},
    "gaussian": {"required": ["mol.gjf"],
                 "missing_must_mention": ["basis"]},
}

#: what the declared-missing check looks for, per abstract token

#: per bundle: the *only* comment character that file dialect understands, and the
#: files it applies to.  A wrong comment char is an "unknown command" in several of
#: these codes (LAMMPS aborts on ';'), so this is checked, not assumed.
COMMENT_STYLE: dict[str, tuple[str, tuple[str, ...]]] = {
    "lammps": ("#", ("data.lammps", "in.min")),
    "gromacs": (";", ("conf.gro", "md.mdp", "topol.top")),
    "cp2k": ("!", ("cp2k.inp",)),
    "nwchem": ("#", ("mol.nw",)),
    "siesta": ("#", ("structure.fdf",)),
    "abacus": ("#", ("STRU",)),
    "aims": ("#", ("geometry.in",)),
    "dftb": ("#", ("dftb_in.hsd", "geo.gen")),
    "qe": ("!", ("pw.in",)),
}

ABSENT_SUFFIXES = {
    "POTCAR": ("POTCAR",),
    "UPF": (".UPF", ".upf"),
    "Slater-Koster": (".skf",),
    "force field": (".top", ".itp"),
    "force-field": (".top", ".itp"),
}


def check_bundle(code: str, directory: Path, declared_missing: list[str]) -> dict:
    """Validate one written bundle; returns ``{code, ok, checks, errors}``."""
    directory = Path(directory)
    rules = RULES.get(code)
    checks: list[dict] = []
    errors: list[str] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    if rules is None:
        return {"code": code, "ok": False, "checks": checks,
                "errors": [f"no bundle rules for {code!r}"]}

    # 1) required files exist and are non-empty
    for name in rules.get("required", []):
        path = directory / name
        record(f"file {name}", path.is_file() and path.stat().st_size > 0,
               "missing" if not path.is_file() else
               ("empty" if path.stat().st_size == 0 else "ok"))

    # 2) cross-file references resolve
    for source, pattern, target in rules.get("refs", []):
        source_path = directory / source
        if not source_path.is_file():
            record(f"ref {source}->{target}", False, f"{source} missing")
            continue
        text = source_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(pattern, text)
        if not match:
            record(f"ref {source}->{target}", False, f"pattern {pattern!r} not found")
            continue
        referenced = match.group(1)
        # the reference may be a bare filename or a relative path
        candidate = directory / referenced
        record(f"ref {source}->{target}", candidate.is_file(),
               f"{source} references {referenced!r}; "
               f"{'found' if candidate.is_file() else 'not shipped'}")

    # 3) declared 'missing' means really absent
    for token in rules.get("missing_must_mention", []):
        declared = any(token.lower() in item.lower() for item in declared_missing)
        record(f"declares missing {token}", declared,
               f"missing list = {declared_missing}")
        suffixes = ABSENT_SUFFIXES.get(token, ())
        if suffixes:
            present = [path.name for path in directory.rglob("*")
                       if path.is_file()
                       and not path.name.lower().endswith((".readme", ".md", ".txt"))
                       and any(path.name.endswith(s) or s in path.name for s in suffixes)]
            record(f"{token} really absent", not present,
                   f"unexpectedly shipped: {present}")

    # 4) comment characters: the wrong one is a syntax error in most of these codes
    style = COMMENT_STYLE.get(code)
    if style:
        char, files = style
        wrong = ";" if char == "#" else "#"
        for name in files:
            path = directory / name
            if not path.is_file():
                continue
            offenders = []
            for number, line in enumerate(path.read_text(encoding="utf-8",
                                                       errors="replace").splitlines(), 1):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(wrong):
                    offenders.append(number)
            record(f"comments in {name} use {char!r}", not offenders,
                   f"lines starting with {wrong!r}: {offenders[:5]}")

    return {"code": code, "ok": not errors, "checks": checks, "errors": errors}


__all__ = ["RULES", "check_bundle"]
