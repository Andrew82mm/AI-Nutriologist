"""Locate the sample receipt PDFs used by the benchmarks.

The receipts live in the repo's «чеки для парса» folder (real OFD email exports
across several chains — Лента, О'КЕЙ, Магнит, Перекрёсток). They are the shared
input for the reconciliation and coverage benchmarks.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECEIPTS_DIR = REPO_ROOT / "чеки для парса"

_CHAINS = [
    ("лента", "Лента"), ("о'кей", "О'КЕЙ"), ("окей", "О'КЕЙ"),
    ("магнит", "Магнит"), ("перекрёст", "Перекрёсток"), ("перекрест", "Перекрёсток"),
]


def receipt_pdfs() -> list[Path]:
    """All receipt PDFs in the corpus, sorted by name (stable ordering)."""
    if not RECEIPTS_DIR.is_dir():
        return []
    return sorted(RECEIPTS_DIR.glob("*.pdf"))


def chain_of(filename: str) -> str:
    """Retail chain guessed from a receipt filename (the exports name the store)."""
    low = filename.lower()
    for key, label in _CHAINS:
        if key in low:
            return label
    return "прочее"
