"""Format dispatch: try deterministic parsers first, one per known ОФД/store
layout. When none match and an LLM client is supplied, fall back to
llm_fallback.py; otherwise raise UnsupportedReceiptFormat so the caller can
decide what to do (queue for later, surface to the user, etc.)."""

from __future__ import annotations

from pathlib import Path

from ..llm.client import StructuredLLMClient
from . import llm_fallback, ofdru
from .models import ParsedReceipt
from .pdf_text import extract_text


class UnsupportedReceiptFormat(Exception):
    """Raised when no deterministic parser recognizes the receipt's layout
    and no LLM fallback client was provided."""

    def __init__(self, text: str):
        self.text = text
        super().__init__(
            "No deterministic parser matched this receipt, and no LLM fallback "
            "client was provided. Pass `llm=` to use one."
        )


def parse_receipt_text(text: str, llm: StructuredLLMClient | None = None) -> ParsedReceipt:
    if ofdru.looks_like_ofdru(text):
        return ofdru.parse(text)
    if llm is not None:
        return llm_fallback.extract_receipt(text, llm)
    raise UnsupportedReceiptFormat(text)


def parse_receipt_pdf(pdf_path: Path | str, llm: StructuredLLMClient | None = None) -> ParsedReceipt:
    return parse_receipt_text(extract_text(pdf_path), llm=llm)
