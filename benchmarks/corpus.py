"""Locate the sample receipt PDFs used by the benchmarks.

The receipts live in the repo's «чеки для парса» folder (real OFD email exports
across several chains — Лента, О'КЕЙ, Магнит, Перекрёсток). They are the shared
input for the reconciliation and coverage benchmarks.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECEIPTS_DIR = REPO_ROOT / "чеки для парса"


def receipt_pdfs() -> list[Path]:
    """All receipt PDFs in the corpus, sorted by name (stable ordering)."""
    if not RECEIPTS_DIR.is_dir():
        return []
    return sorted(RECEIPTS_DIR.glob("*.pdf"))
