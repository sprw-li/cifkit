"""On-disk slab cache (round 47, limitation G2).

The in-process memo was per process, so a batch of separate workers recomputed the
same slabs.  These tests pin the disk layer: it must actually be reused across
processes, must never serve a *wrong* slab, and must never break geometry when the
cache is broken.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pymatgen.core import Structure

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CIFKIT_CACHE", str(tmp_path / "cache"))
    from cifkit.geom import disk_cache

    disk_cache.clear()
    yield
    disk_cache.clear()


@pytest.fixture(scope="module")
def structure() -> Structure:
    return Structure.from_file(FIXTURE)


def test_second_call_is_served_from_disk(structure):
    from cifkit.geom import disk_cache
    from cifkit.geom.surface import clear_slab_cache, make_slab, slab_cache_info

    clear_slab_cache()
    first, info_first = make_slab(structure, (1, 1, 1), slab_thickness=8.0)
    assert info_first["cache"] == "miss"
    assert slab_cache_info()["disk"]["disk_writes"] == 1

    # drop the in-process layer: only the disk entry can answer now
    clear_slab_cache()
    second, info_second = make_slab(structure, (1, 1, 1), slab_thickness=8.0)
    assert info_second["cache"] == "disk"
    assert len(second) == len(first)
    assert second.lattice.abc == pytest.approx(first.lattice.abc)
    assert slab_cache_info()["disk"]["disk_hits"] == 1


def test_different_parameters_do_not_collide(structure):
    from cifkit.geom.surface import clear_slab_cache, make_slab

    clear_slab_cache()
    thin, _ = make_slab(structure, (1, 1, 1), slab_thickness=6.0)
    clear_slab_cache()
    thick, info = make_slab(structure, (1, 1, 1), slab_thickness=12.0)
    assert info["cache"] == "miss", "different thickness must not hit"
    assert len(thick) > len(thin)
    clear_slab_cache()
    again, info_again = make_slab(structure, (1, 1, 1), slab_thickness=6.0)
    assert info_again["cache"] == "disk"
    assert len(again) == len(thin)


def test_corrupt_entry_is_ignored_and_replaced(structure):
    from cifkit.geom import disk_cache
    from cifkit.geom.surface import clear_slab_cache, make_slab, slab_cache_info

    clear_slab_cache()
    make_slab(structure, (1, 1, 0), slab_thickness=8.0)
    entry = next(disk_cache.cache_dir().glob("*.json"))
    entry.write_text("{not json", encoding="utf-8")

    clear_slab_cache()
    slab, info = make_slab(structure, (1, 1, 0), slab_thickness=8.0)
    assert info["cache"] == "miss", "a corrupt entry must be a miss"
    assert len(slab) > 0
    assert slab_cache_info()["disk"]["disk_corrupt"] >= 1
    assert json.loads(entry.read_text(encoding="utf-8"))["key"], "entry was rewritten"


def test_cache_can_be_disabled(structure, monkeypatch):
    monkeypatch.setenv("CIFKIT_SLAB_DISK_CACHE", "0")
    from cifkit.geom import disk_cache
    from cifkit.geom.surface import clear_slab_cache, make_slab

    clear_slab_cache()
    make_slab(structure, (0, 1, 1), slab_thickness=8.0)
    assert not list(disk_cache.cache_dir().glob("*.json")) if disk_cache.cache_dir().is_dir() else True
    clear_slab_cache()
    _, info = make_slab(structure, (0, 1, 1), slab_thickness=8.0)
    assert info["cache"] == "miss"


def test_cache_is_shared_across_processes(tmp_path, structure):
    """The whole point of G2: a *separate* process must hit the same entry."""
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent(
        """
        import json, sys
        from pymatgen.core import Structure
        from cifkit.geom.surface import make_slab, slab_cache_info
        structure = Structure.from_file(sys.argv[1])
        slab, info = make_slab(structure, (1, 1, 1), slab_thickness=8.0)
        print(json.dumps({"cache": info["cache"], "natoms": len(slab),
                          "hits": slab_cache_info()["disk"]["disk_hits"]}))
        """),
        encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # populate the disk cache in THIS process first; the child must then hit it
    from cifkit.geom.surface import clear_slab_cache, make_slab

    clear_slab_cache()
    make_slab(structure, (1, 1, 1), slab_thickness=8.0)

    first = subprocess.run([sys.executable, str(script), str(FIXTURE)], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=600)
    assert first.returncode == 0, first.stderr[-800:]
    payload = json.loads(first.stdout.strip().splitlines()[-1])
    assert payload["cache"] == "disk", payload
    assert payload["natoms"] > 0
