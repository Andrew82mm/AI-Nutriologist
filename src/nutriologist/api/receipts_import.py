"""Import a receipt PDF from a local path into the fridge (web-facing).

Chains the receipt pipeline that already exists (and is unit-tested) end to end,
which until now was reachable only from the CLI:

    parse_receipt_pdf → save_receipt → normalize_receipt_items → income_from_receipt

The receipt is referenced by a server-side file path (mail automation that would
fetch it automatically is итерация 8, out of scope here). Normalization needs an
LLM, so this endpoint requires one to be configured; parsing an unknown receipt
layout also uses it as a fallback.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..inventory.operations import income_from_receipt
from ..products.receipt_link import normalize_receipt_items
from ..receipts.parse import UnsupportedReceiptFormat, parse_receipt_pdf
from ..receipts.pdf_text import PdfExtractionError
from ..receipts.storage import save_receipt
from .app import db_conn, get_optional_llm

router = APIRouter(prefix="/api", tags=["receipts"])


class ReceiptImportIn(BaseModel):
    path: str


class ReceiptImportOut(BaseModel):
    receipt_id: int
    store_name: str | None
    items_parsed: int
    items_normalized: int  # lines linked to a product this run (0 on a re-import)
    items_posted: int      # edible lines added to inventory (0 on a re-import)
    duplicate: bool        # the receipt (fd_number, fpd) was already imported


def _already_imported(conn: sqlite3.Connection, fd_number: str | None, fpd: str | None) -> bool:
    """True if a receipt with this fiscal fingerprint already exists.

    Mirrors `save_receipt`'s dedup key so we can tell the caller a re-import was a
    no-op (rather than inferring it from a zero post count, which a receipt of
    only non-food items would also produce)."""
    if fd_number is None or fpd is None:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM receipts WHERE fd_number = ? AND fpd = ?", (fd_number, fpd)
        ).fetchone()
        is not None
    )


@router.post("/receipts/import", response_model=ReceiptImportOut)
def import_receipt(
    payload: ReceiptImportIn, conn: sqlite3.Connection = Depends(db_conn)
) -> ReceiptImportOut:
    """Parse a receipt PDF at `path`, normalize its items, and stock the fridge."""
    path = Path(payload.path).expanduser()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"файл не найден: {payload.path}")

    llm = get_optional_llm()
    if llm is None:
        raise HTTPException(
            status_code=422,
            detail="Для нормализации чека нужен настроенный LLM — заполните .env "
            "(LLM_PROVIDER, LLM_API_KEY, ...).",
        )

    try:
        parsed = parse_receipt_pdf(path, llm=llm)
    except UnsupportedReceiptFormat:
        raise HTTPException(status_code=422, detail="Формат чека не распознан.")
    except PdfExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    duplicate = _already_imported(conn, parsed.fd_number, parsed.fpd)
    receipt_id = save_receipt(conn, parsed)
    normalized = normalize_receipt_items(conn, receipt_id, llm)
    posted = income_from_receipt(conn, receipt_id)

    return ReceiptImportOut(
        receipt_id=receipt_id,
        store_name=parsed.store_name,
        items_parsed=len(parsed.items),
        items_normalized=normalized,
        items_posted=posted,
        duplicate=duplicate,
    )
