"""Convergence-study machinery (round 45, limitation E3).

Every template we ship uses default parameters (NWChem ``cutoff 20``, VASP ``ENCUT``
from the INCAR template, ...), and E3 said no convergence testing was done.  This
module provides the machinery:

1. :func:`sweep` — derive a series of input variants from an exported input by
   substituting the parameter(s) that a code actually exposes;
2. :func:`parse_energy` — read the final energy out of a code's *output* (several
   dialects are understood);
3. :func:`analyse` — decide where the quantity is converged (Δ < threshold), and
   report the smallest converged setting rather than the largest tested.

Design rules learned in this project:

* never invent a parameter a code does not have (the sweep is per-code);
* report **all** samples, including failures — a sweep with holes must not look
  complete;
* convergence needs at least two consecutive points inside the threshold.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

#: per code: (parameter, {value: substitution}) applied to an exported input
SWEEPS: dict[str, dict] = {
    "nwchem": {
        "parameter": "cutoff",
        "unit": "hartree",
        "defaults": [20, 30, 40, 50, 60],
        "pattern": r"(?m)^(\s*)cutoff\s+\S+\s*$",
        "render": r"\g<1>cutoff {value}",
    },
    "vasp": {
        "parameter": "ENCUT",
        "unit": "eV",
        "defaults": [400, 450, 520, 600, 700],
        "pattern": r"(?m)^(\s*ENCUT\s*=\s*)\S+\s*$",
        "render": r"\g<1>{value}",
    },
    "qe": {
        "parameter": "ecutwfc",
        "unit": "Ry",
        "defaults": [20, 30, 40, 50, 60],
        "pattern": r"(?m)^(\s*ecutwfc\s*=\s*)\S+\s*$",
        "render": r"\g<1>{value}",
    },
    "cp2k": {
        "parameter": "CUTOFF",
        "unit": "Ry",
        "defaults": [200, 300, 400, 500, 600],
        "pattern": r"(?m)^(\s*CUTOFF\s+)\S+\s*$",
        "render": r"\g<1>{value}",
    },
}

#: output dialects -> final-energy regex (first match wins)
ENERGY_PATTERNS = (
    re.compile(r"Total DFT energy\s*=\s*(-?\d+\.\d+)"),
    re.compile(r"Total PSPW energy\s*=\s*(-?\d+\.\d+)"),
    re.compile(r"Total energy\s*=\s*(-?\d+\.\d+)"),
    re.compile(r"^!\s+total energy\s*=\s*(-?\d+\.\d+)\s*Ry", re.M),
    re.compile(r"energy\s+without entropy\s*=\s*(-?\d+\.\d+)"),
    re.compile(r"ENERGY\|\s+Total energy\s*=\s*(-?\d+\.\d+)"),
    re.compile(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)"),
    re.compile(r"Total times.*?\n", re.S),      # marker only; energy parsed elsewhere
)


@dataclass
class Sample:
    value: float
    energy: float | None
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict:
        # a failed sample must serialise as null, not as bare NaN: `NaN` is not
        # valid JSON and breaks strict consumers (asserted by tests)
        energy = self.energy
        if energy is not None and not math.isfinite(float(energy)):
            energy = None
        return {"value": self.value, "energy": energy, "ok": self.ok,
                "detail": self.detail}


@dataclass
class ConvergenceReport:
    code: str
    parameter: str
    unit: str
    threshold: float
    samples: list[Sample] = field(default_factory=list)
    converged_at: float | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {"code": self.code, "parameter": self.parameter, "unit": self.unit,
                "threshold": self.threshold,
                "samples": [sample.as_dict() for sample in self.samples],
                "converged_at": self.converged_at, "note": self.note,
                "complete": all(sample.ok for sample in self.samples)}


def sweep(code: str, text: str, values: list[float] | None = None) -> list[tuple[float, str]]:
    """Return ``[(value, input_text), ...]`` for the code's convergence parameter."""
    spec = SWEEPS.get(code)
    if spec is None:
        raise ValueError(f"no convergence sweep defined for {code!r}; "
                         f"known: {sorted(SWEEPS)}")
    chosen = values if values is not None else spec["defaults"]
    out: list[tuple[float, str]] = []
    for value in chosen:
        pattern = spec["pattern"]
        if not re.search(pattern, text):
            raise ValueError(
                f"{code}: parameter line matching {pattern!r} not found in the input; "
                "the template must expose it before a sweep can be built")
        rendered = spec["render"].replace("{value}", str(value))
        out.append((float(value), re.sub(pattern, rendered, text)))
    return out


def parse_energy(output: str) -> float | None:
    """Extract the final energy from a code's output (any supported dialect)."""
    for pattern in ENERGY_PATTERNS:
        match = pattern.search(output)
        if match and match.groups():
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                continue
    return None


def analyse(code: str, samples: list[Sample], threshold: float,
            per_atom: int | None = None) -> ConvergenceReport:
    """Decide the smallest parameter value where the energy has converged.

    ``threshold`` is in the energy unit of the code's output (eV for NWChem/VASP,
    Ry for QE/CP2K).  ``per_atom`` divides the differences by the atom count, which
    is what "1 meV/atom" discussions actually mean.
    """
    spec = SWEEPS.get(code, {})
    report = ConvergenceReport(code=code, parameter=spec.get("parameter", "?"),
                               unit=spec.get("unit", "?"), threshold=threshold,
                               samples=sorted(samples, key=lambda s: s.value))
    usable = [sample for sample in report.samples if sample.ok and sample.energy is not None]
    if len(usable) < 3:
        report.note = (f"only {len(usable)} usable sample(s): "
                       "convergence needs at least 3 successful points")
        return report
    divisor = per_atom or 1
    # converged_at = the smallest value from which **no later step** exceeds the
    # threshold.  (Naming the first value of a locally-flat triple would credit a
    # setting whose very next step still moved by a lot.)
    deltas = [abs(usable[i + 1].energy - usable[i].energy) / divisor
              for i in range(len(usable) - 1)]
    converged = None
    for index, value in enumerate(usable[:-1]):
        if all(delta <= threshold for delta in deltas[index:]):
            converged = value.value
            break
    report.converged_at = converged
    if converged is None:
        smallest = usable[0].value
        largest = usable[-1].value
        span = abs(usable[-1].energy - usable[0].energy) / divisor
        report.note = (f"not converged within {threshold} up to {largest} "
                       f"(total change {span:.6g} from {smallest})")
    else:
        report.note = f"converged at {converged} (threshold {threshold}, per_atom={divisor})"
    return report


def render_markdown(report: ConvergenceReport, *, title: str | None = None) -> str:
    lines = [f"### {title or report.code} convergence", "",
             f"parameter: `{report.parameter}` ({report.unit}) · "
             f"threshold: {report.threshold} · "
             f"converged at: **{report.converged_at}**" if report.converged_at
             else f"parameter: `{report.parameter}` ({report.unit}) · "
                  f"threshold: {report.threshold} · **not converged**",
             "", "| value | energy | ok | detail |", "|---|---|---|---|"]
    for sample in report.samples:
        energy = "" if sample.energy is None else f"{sample.energy:.6f}"
        lines.append(f"| {sample.value} | {energy} | {sample.ok} | {sample.detail[:60]} |")
    lines += ["", f"_{report.note}_" if report.note else ""]
    return "\n".join(lines) + "\n"


__all__ = ["SWEEPS", "Sample", "ConvergenceReport", "sweep", "parse_energy", "analyse",
           "render_markdown"]
