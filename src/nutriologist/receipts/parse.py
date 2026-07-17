"""Format dispatch: try deterministic parsers first, one per known ОФД/store
layout. When none match, raise so the caller can fall back to an LLM-based
parser (not implemented yet — see PLAN.md, module M1)."""

from __future__ import annotations

from pathlib import Path

from . import ofdru
from .models import ParsedReceipt
from .pdf_text import extract_text


class UnsupportedReceiptFormat(Exception):
    """Raised when no deterministic parser recognizes the receipt's layout."""

    def __init__(self, text: str):
        self.text = text
        super().__init__(
            "No deterministic parser matched this receipt — needs the LLM fallback parser."
        )


def parse_receipt_text(text: str) -> ParsedReceipt:
    if ofdru.looks_like_ofdru(text):
        return ofdru.parse(text)
    raise UnsupportedReceiptFormat(text)


def parse_receipt_pdf(pdf_path: Path | str) -> ParsedReceipt:
    return parse_receipt_text(extract_text(pdf_path))
