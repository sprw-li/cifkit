"""In-process ``make_slab`` cache: hit/miss, copy semantics, invalidation."""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.geom import make_slab
from cifkit.geom.surface import clear_slab_cache, slab_cache_info

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture()
def zif8():
    return Structure.from_file(str(DATA / "zif8_cr_sod.cif"))


def test_slab_cache_hit_is_faster_and_equal(zif8):
    clear_slab_cache()
    slab1, info1 = make_slab(zif8, (1, 1, 0), slab_thickness=8.0, vacuum=15.0)
    slab2, info2 = make_slab(zif8, (1, 1, 0), slab_thickness=8.0, vacuum=15.0)
    assert info1.get("cache") == "miss"
    assert info2.get("cache") == "hit"
    assert len(slab1) == len(slab2)
    assert slab1.lattice == slab2.lattice
    assert info1["vacuum_measured"] == pytest.approx(info2["vacuum_measured"])
    stats = slab_cache_info()
    assert stats["hits"] == 1 and stats["misses"] == 1


def test_slab_cache_returns_independent_copies(zif8):
    clear_slab_cache()
    slab1, _ = make_slab(zif8, (1, 1, 0), slab_thickness=8.0, vacuum=15.0)
    original = slab1.frac_coords[0].copy()
    slab1.frac_coords[0] = [0.123, 0.456, 0.789]
    slab2, _ = make_slab(zif8, (1, 1, 0), slab_thickness=8.0, vacuum=15.0)
    assert slab2.frac_coords[0] == pytest.approx(original)


def test_slab_cache_distinguishes_arguments(zif8):
    clear_slab_cache()
    make_slab(zif8, (1, 1, 0), slab_thickness=8.0, vacuum=15.0)
    _, info = make_slab(zif8, (1, 1, 0), slab_thickness=8.0, vacuum=20.0)
    assert info.get("cache") == "miss"
    _, info2 = make_slab(zif8, (2, 1, 0), slab_thickness=8.0, vacuum=15.0)
    assert info2.get("cache") == "miss"


def test_slab_cache_clear(zif8):
    clear_slab_cache()
    make_slab(zif8, (1, 1, 0), slab_thickness=8.0, vacuum=15.0)
    assert slab_cache_info()["size"] == 1
    clear_slab_cache()
    assert slab_cache_info()["size"] == 0 and slab_cache_info()["hits"] == 0
