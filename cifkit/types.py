from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymatgen.core import Structure


@dataclass
class TaskSpec:
    """A parsed user request: what to fetch, how to repair, how to transform, how to export."""

    query: str = ""
    source: str = "auto"
    topology: str | None = None
    structure_name: str | None = None
    structure_id: str | None = None
    typical: bool = True
    repair_h: bool = False
    repair_disorder: bool = True
    remove_close_contacts: bool = True
    extract_cluster: bool = False
    cluster_mode: str = "sbu"
    supercell: tuple[int, int, int] | None = None
    surface: tuple[int, int, int] | None = None
    vacuum: float | None = None
    slab_thickness: float | None = None
    output_formats: list[str] = field(default_factory=lambda: ["vasp"])
    outdir: Path = Path("runs/run")
    notes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["outdir"] = str(self.outdir)
        return d


@dataclass
class StructureRecord:
    """A hit from a structure database, before/after materialisation to a CIF file."""

    record_id: str
    source: str
    formula: str | None = None
    topology: str | None = None
    topology_evidence: str = "unknown"  # metadata | verified | curated | unknown
    refcode: str | None = None
    coreid: str | None = None
    doi: str | None = None
    variant: str | None = None  # computation-ready | raw | unknown
    natoms: int | None = None
    h_count: int | None = None
    h_expected: float | None = None
    path: str | None = None
    url: str | None = None
    sha256: str | None = None
    notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def is_h_deficient(self) -> bool:
        if self.h_count is None:
            return False
        expected = self.h_expected if self.h_expected is not None else 0.0
        return self.h_count + 0.5 < expected

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class SourceQuery:
    topology: str | None = None
    typical: bool = True
    prefer_raw: bool = False
    structure_name: str | None = None
    structure_id: str | None = None
    limit: int = 10
    source: str = "auto"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchedStructure:
    structure: Structure
    record: StructureRecord
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class RepairReport:
    actions: list[dict[str, Any]] = field(default_factory=list)
    added_h: int = 0
    removed_atoms: int = 0
    resolved_disorder: int = 0
    warnings: list[str] = field(default_factory=list)

    def add(self, action: str, detail: str, **data: Any) -> None:
        self.actions.append({"action": action, "detail": detail, **data})

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": self.actions,
            "added_h": self.added_h,
            "removed_atoms": self.removed_atoms,
            "resolved_disorder": self.resolved_disorder,
            "warnings": self.warnings,
        }


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "error"  # error | warning | info


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str = "", severity: str = "error") -> None:
        self.checks.append(CheckResult(name=name, ok=ok, detail=detail, severity=severity))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.severity == "error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [c.__dict__ for c in self.checks],
            "metrics": self.metrics,
        }


@dataclass
class StepResult:
    name: str
    status: str  # ok | skipped | failed
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class RunResult:
    spec: TaskSpec
    steps: list[StepResult] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    outdir: Path = Path("runs/run")
    manifest_path: str | None = None
    validation: ValidationReport | None = None
    ok: bool = False

    def step(self, name: str) -> StepResult | None:
        for s in self.steps:
            if s.name == name:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "outdir": str(self.outdir),
            "manifest": self.manifest_path,
            "spec": self.spec.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "artifacts": self.artifacts,
            "validation": self.validation.to_dict() if self.validation else None,
        }
