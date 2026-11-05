"""Shared helpers for the 4 use-case deliverables (Lead-owned; read-only for teammates).

* ``aflux(query, paging=...)`` — raw AFLUX query, tolerant of both JSON list and
  ``{"1 of N": {...}}`` paging dicts.
* ``element_ground_state(el)`` — element ground state from AFLOW LIB1 by lowest
  ``energy_atom`` (verified: Fe->cI2, Cu->cF4, Mg->hP2, W->cI2, Al->cF4).
* ``fetch_structure(aurl)`` — download + parse an AFLOW entry's CIF via cifkit.
* ``binary_entries(a, b, catalog)`` — binary-system AFLUX rows with formation enthalpy.
* ``save_table_csv(rows, path)`` / ``slug`` — small I/O conveniences.

Network calls are cached by cifkit's AFLOW adapter (CIF files) and mirrored in
``_cache/aflow``; AFLUX responses are not cached here (small + fast enough).
"""
from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

AFLUX_URL = "https://aflow.org/API/aflux/"
_USER_AGENT = "cifkit-usecases/0.1 (python-urllib)"
ROOT = Path(__file__).resolve().parents[2]


def aflux(query: str, *, paging: tuple[int, int] = (0, 50), timeout: float = 60.0,
          retries: int = 2) -> list[dict[str, Any]]:
    """Run an AFLUX query and return rows (handles list and paged-dict responses)."""
    q = query.strip().rstrip(",")
    url = f"{AFLUX_URL}?{q},paging({paging[0]},{paging[1]})"
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed host
                data = json.loads(resp.read().decode("utf-8", "replace"))
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
            if isinstance(data, dict):
                return [r for r in data.values() if isinstance(r, dict)]
            raise RuntimeError(f"AFLUX 返回结构异常：{type(data).__name__}")
        except Exception as exc:  # noqa: BLE001 - retry
            last = exc
    raise RuntimeError(f"AFLUX 查询失败：{url}（{type(last).__name__}: {last}）") from last


def element_ground_state(el: str, *, catalog: str = "LIB1", limit: int = 60) -> dict[str, Any] | None:
    """Lowest ``energy_atom`` LIB1 entry for an element (ground-state prototype)."""
    rows = aflux(
        f"species({el}),nspecies(1),catalog({catalog}),energy_atom",
        paging=(0, limit),
    )
    scored = []
    for row in rows:
        try:
            energy = float(row["energy_atom"])
        except (KeyError, TypeError, ValueError):
            continue
        scored.append((energy, row))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    row = dict(scored[0][1])
    row["_energy_atom"] = scored[0][0]
    row["_n_candidates"] = len(scored)
    return row


def fetch_structure(aurl: str):
    """Download + parse the CIF of an AFLOW entry (uses the cifkit adapter/cache)."""
    from cifkit.sources.aflow import AFLOWSource
    from cifkit.types import SourceQuery

    src = AFLOWSource()
    hits = src.search(SourceQuery(structure_id=aurl))
    if not hits:
        raise RuntimeError(f"AFLOW 检索无命中：{aurl}")
    fetched = src.fetch(hits[0])
    return fetched.structure, fetched.provenance, fetched.record


def binary_entries(a: str, b: str, *, catalog: str | None = None, limit: int = 400,
                   extra: str = "enthalpy_formation_atom") -> list[dict[str, Any]]:
    """Binary-system AFLUX rows (optionally restricted to a catalog)."""
    query = f"species({a},{b}),nspecies(2)"
    if catalog:
        query += f",catalog({catalog})"
    if extra:
        query += f",{extra}"
    return aflux(query, paging=(0, max(1, limit)))


def save_table_csv(rows: Iterable[dict[str, Any]], path: str | Path) -> Path:
    rows = list(rows)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return p


def slug(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in str(text))[:80]
