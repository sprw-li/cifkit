"""Source adapters: database lookup + download, behind one registry.

Every adapter must return ``StructureRecord`` hits from ``search`` and a
``FetchedStructure`` from ``fetch``. ``resolve(spec)`` picks adapters based on
``spec.source`` (``auto`` = core-mof when a topology is requested, cod for
numeric COD ids, local for filesystem paths).
"""
from __future__ import annotations

from cifkit.types import FetchedStructure, SourceQuery, StructureRecord, TaskSpec

__all__ = ["SourceQuery", "StructureRecord", "FetchedStructure", "get_source", "resolve", "available_sources"]


def available_sources() -> dict[str, str]:
    """Return {source_name: human description}."""
    raise NotImplementedError("sources.available_sources not implemented yet")


def get_source(name: str):
    """Return a source adapter instance by name (``core-mof``, ``cod``, ``local``, ...)."""
    raise NotImplementedError("sources.get_source not implemented yet")


def resolve(spec: TaskSpec) -> FetchedStructure:
    """Search + fetch the structure requested by ``spec``; raise on ambiguity."""
    raise NotImplementedError("sources.resolve not implemented yet")
