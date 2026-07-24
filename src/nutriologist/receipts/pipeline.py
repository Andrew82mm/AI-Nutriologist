"""End-to-end receipt import, reusable outside the HTTP layer.

Chains the receipt pipeline that already existed piecemeal (parse → save →
normalize → income) into one function that both the web endpoint
(`api/receipts_import.py`) and the mail poller (`mail/poller.py`) call, so the
"a PDF becomes fridge stock" logic lives in exactly one place.

The function speaks the domain, not HTTP: it returns an `ImportResult` and lets
the existing domain exceptions (`UnsupportedReceiptFormat`, `PdfExtractionError`)
propagate. Callers translate those into whatever their transport needs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..inventory.operations import income_from_receipt
from ..llm.client import StructuredLLMClient
from ..products.receipt_link import normalize_receipt_items
from .parse import parse_receipt_pdf
from .storage import save_receipt


@dataclass(frozen=True)
class ImportResult:
    receipt_id: int
    store_name: str | None
    items_parsed: int
    items_normalized: int  # lines linked to a product this run (0 on a re-import)
    items_posted: int      # edible lines added to inventory (0 on a re-import)
    duplicate: bool         # the receipt (fd_number, fpd) was already imported


def already_imported(
    conn: sqlite3.Connection, fd_number: str | None, fpd: str | None
) -> bool:
    """True if a receipt with this fiscal fingerprint already exists.

    Mirrors `save_receipt`'s dedup key so callers can tell a re-import was a
    no-op (rather than inferring it from a zero post count, which a receipt of
    only non-food items would also produce). Receipts without both fields have
    no reliable key and are never treated as duplicates — same as storage.
    """
    if fd_number is None or fpd is None:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM receipts WHERE fd_number = ? AND fpd = ?", (fd_number, fpd)
        ).fetchone()
        is not None
    )


def import_receipt_pdf(
    conn: sqlite3.Connection, path: Path | str, llm: StructuredLLMClient
) -> ImportResult:
    """Parse a receipt PDF, normalize its items, and stock the fridge.

    Idempotent by fiscal fingerprint: re-importing the same receipt returns the
    existing id with `duplicate=True` and posts nothing new.

    Raises:
        UnsupportedReceiptFormat: layout unknown and the LLM couldn't parse it.
        PdfExtractionError: the PDF text couldn't be extracted.
    """
    parsed = parse_receipt_pdf(path, llm=llm)

    duplicate = already_imported(conn, parsed.fd_number, parsed.fpd)
    receipt_id = save_receipt(conn, parsed)
    normalized = normalize_receipt_items(conn, receipt_id, llm)
    posted = income_from_receipt(conn, receipt_id)

    return ImportResult(
        receipt_id=receipt_id,
        store_name=parsed.store_name,
        items_parsed=len(parsed.items),
        items_normalized=normalized,
        items_posted=posted,
        duplicate=duplicate,
    )
