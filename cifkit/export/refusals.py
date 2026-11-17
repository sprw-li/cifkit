"""Honest refusals: one base class for "this format cannot represent the input" (round 58).

The export layer already refuses two classes of input with a *typed* error instead
of writing a silently wrong file:

* :class:`~cifkit.export.disorder_guard.DisorderedStructureError` — partial
  occupancies cannot be expressed by the ordered-only formats;
* :class:`~cifkit.export.format_limits.FormatLimitError` — a format's hard
  structural limit (MDL 999 atoms, WIEN2k's 3-digit atom field, ...).

Round 58 adds a third: a LAMMPS box whose tilt factors exceed the half-box limit
that real LAMMPS enforces (``CellNotRepresentableError``).  The refusal is the
*correct* behaviour — but verifiers have to be able to tell it apart from a real
failure, otherwise a correct refusal is reported as a broken format.

This module gives all three a common base so verification code can catch one type::

    except ExportRefusalError as exc:
        row["unsupported"] = refusal_reason(exc)

The hierarchy keeps ``ValueError`` compatibility, because every one of these
errors has always been a ``ValueError`` and callers already catch that.
"""
from __future__ import annotations

__all__ = ["ExportRefusalError", "CellNotRepresentableError", "refusal_reason"]


class ExportRefusalError(ValueError):
    """Base class for an *honest* refusal: the format cannot represent this input.

    A refusal is not a defect in cifkit and not a broken format: the file was
    deliberately not written because writing it would have produced a wrong or
    unusable artifact.  Verifiers count these as ``unsupported``.
    """

    code = "export-refusal"


class CellNotRepresentableError(ExportRefusalError):
    """The target format's box representation cannot express this cell.

    Raised (currently) by the LAMMPS writer when a tilt factor exceeds half the
    corresponding box length — a box real LAMMPS refuses to read.  Reducing the
    cell instead would silently change the cell *shape*, so the export is
    refused with an actionable message.
    """

    code = "cell-not-representable"

    def __init__(self, fmt: str, detail: str, fix: str = "") -> None:
        self.fmt = fmt
        self.detail = detail
        message = f"format {fmt!r} cannot represent this cell: {detail}"
        if fix:
            message += f" {fix}"
        super().__init__(message)


def refusal_reason(exc: BaseException) -> str:
    """A short, stable ``code: message`` reason string for a refusal row."""
    code = getattr(exc, "code", None) or type(exc).__name__
    return f"{code}: {exc}"
