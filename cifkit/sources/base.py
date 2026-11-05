"""Shared types + helpers for source adapters (Lead-owned; adapters consume it)."""
from __future__ import annotations

from typing import Protocol

from cifkit.types import FetchedStructure, SourceQuery, StructureRecord


class Source(Protocol):
    name: str
    description: str

    def search(self, query: SourceQuery) -> list[StructureRecord]: ...

    def fetch(self, record: StructureRecord) -> FetchedStructure: ...


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def count_hydrogen(structure) -> int:
    return sum(1 for site in structure if site.species_string == "H")


def expected_hydrogen(formula: dict[str, float]) -> float:
    """Rough expected H budget for organic-framework formulas.

    Only used to flag "H-deficient" records; the real completion is done by
    ``cifkit.repair`` from local valence, never from this estimate.
    """
    c = formula.get("C", 0.0)
    n = formula.get("N", 0.0)
    o = formula.get("O", 0.0)
    s = formula.get("S", 0.0)
    # imidazolate/carboxylate mix: ~1.15 H per C on average, N contributes ~0.5,
    # O contributes ~0.5 (hydroxyls), S ~0.3. Deliberately loose.
    return 1.15 * c + 0.5 * n + 0.5 * o + 0.3 * s
