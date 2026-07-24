"""Import a receipt PDF from a local path into the fridge (web-facing).

Thin HTTP wrapper over `receipts.pipeline.import_receipt_pdf`, which chains the
unit-tested core end to end:

    parse_receipt_pdf → save_receipt → normalize_receipt_items → income_from_receipt

The receipt is referenced by a server-side file path. Fetching receipts
automatically from a mailbox is `mail/` (итерация 8) — see `POST
/api/receipts/poll-mail`. Normalization needs an LLM, so this endpoint requires
one to be configured; parsing an unknown receipt layout also uses it.
"""

from __future__ import annotations

import imaplib
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..mail.config import MailConfigError, load_mail_config_from_env
from ..mail.imap import ImapMailbox
from ..mail.poller import poll_mailbox
from ..receipts.parse import UnsupportedReceiptFormat
from ..receipts.pdf_text import PdfExtractionError
from ..receipts.pipeline import import_receipt_pdf
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
        result = import_receipt_pdf(conn, path, llm)
    except UnsupportedReceiptFormat:
        raise HTTPException(status_code=422, detail="Формат чека не распознан.")
    except PdfExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return ReceiptImportOut(
        receipt_id=result.receipt_id,
        store_name=result.store_name,
        items_parsed=result.items_parsed,
        items_normalized=result.items_normalized,
        items_posted=result.items_posted,
        duplicate=result.duplicate,
    )


class PollMailReceiptOut(BaseModel):
    filename: str
    ok: bool
    receipt_id: int | None = None
    store_name: str | None = None
    items_posted: int | None = None
    duplicate: bool | None = None
    error: str | None = None


class PollMailOut(BaseModel):
    messages_seen: int
    imported: int
    duplicates: int
    errors: int
    receipts: list[PollMailReceiptOut]


@router.post("/receipts/poll-mail", response_model=PollMailOut)
def poll_mail(conn: sqlite3.Connection = Depends(db_conn)) -> PollMailOut:
    """Poll the receipts mailbox once, importing any PDF receipts found.

    Mailbox settings come from `.env` (MAIL_*); an LLM must be configured too
    (normalization + unknown-layout parsing). Idempotent by fiscal fingerprint,
    so a re-run won't double-stock the fridge.
    """
    llm = get_optional_llm()
    if llm is None:
        raise HTTPException(
            status_code=422,
            detail="Для нормализации чека нужен настроенный LLM — заполните .env "
            "(LLM_PROVIDER, LLM_API_KEY, ...).",
        )

    try:
        mail_config = load_mail_config_from_env()
    except MailConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        with ImapMailbox(mail_config) as box:
            summary = poll_mailbox(conn, box, llm)
    except (OSError, imaplib.IMAP4.error) as exc:  # socket/DNS failures + IMAP login/protocol errors
        raise HTTPException(status_code=502, detail=f"Не удалось опросить почту: {exc}")

    return PollMailOut(
        messages_seen=summary.messages_seen,
        imported=summary.imported,
        duplicates=summary.duplicates,
        errors=summary.errors,
        receipts=[
            PollMailReceiptOut(
                filename=r.filename,
                ok=r.ok,
                receipt_id=r.result.receipt_id if r.result else None,
                store_name=r.result.store_name if r.result else None,
                items_posted=r.result.items_posted if r.result else None,
                duplicate=r.result.duplicate if r.result else None,
                error=r.error,
            )
            for r in summary.receipts
        ],
    )
