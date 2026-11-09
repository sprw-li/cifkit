"""Bootstrap that makes ``openbabel`` unimportable, then runs verify_formats.

Used by ``tests/test_licensing.py`` to prove the *core* export path does not
depend on the GPL-licensed Open Babel bindings: if the full 31-format suite still
passes with Open Babel blocked, a commercial embedding can ship without it.

    python scripts/verify_formats_no_gpl.py [--outdir DIR]
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BLOCKED_PREFIXES = ("openbabel", "pybel", "openbabel_py")


class _Blocker:
    """Meta-path finder that rejects the blocked modules."""

    def find_module(self, fullname: str, path=None):  # noqa: D401 - legacy API
        return self if fullname.split(".")[0] in BLOCKED_PREFIXES else None

    def load_module(self, fullname: str):  # pragma: no cover - legacy API
        raise ImportError(f"{fullname} is blocked for the GPL-free core check")

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED_PREFIXES:
            raise ImportError(f"{fullname} is blocked for the GPL-free core check")
        return None


sys.meta_path.insert(0, _Blocker())


def main() -> int:
    outdir = "runs/verify_formats_no_gpl"
    argv = sys.argv[1:]
    if "--outdir" in argv:
        outdir = argv[argv.index("--outdir") + 1]
    else:
        argv = [*argv, "--outdir", outdir]
    sys.argv = ["verify_formats.py", *argv]
    from cifkit import export

    print(f"[no-gpl] openbabel blocked; formats={len(export.supported_formats())}")
    runpy.run_path(str(ROOT / "scripts" / "verify_formats.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
