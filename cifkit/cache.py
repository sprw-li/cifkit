"""Cache root resolution shared by every module.

Order: ``$CIFKIT_CACHE`` -> ``<project>/_cache``.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_root() -> Path:
    return PROJECT_ROOT


def cache_root() -> Path:
    env = os.environ.get("CIFKIT_CACHE")
    root = Path(env).expanduser() if env else PROJECT_ROOT / "_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir(name: str) -> Path:
    d = cache_root() / name
    d.mkdir(parents=True, exist_ok=True)
    return d
