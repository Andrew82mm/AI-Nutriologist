"""Orchestrate one poll: mailbox → PDF on disk → fridge stock.

For each unseen message we save its PDF attachment(s) under `data/receipts/` and
run the shared import pipeline. Import is idempotent by fiscal fingerprint, so a
message that gets processed twice (e.g. it was marked seen but the flag didn't
stick) can't double-stock the fridge.

`mark_seen` policy: a message is marked seen once all of its attachments have
been handled without a hard error — non-receipt mail (no PDF) is marked seen too
(nothing to retry), while a message whose PDF failed to parse is left unseen so a
later poll can retry it (useful when the failure was a transient LLM outage).
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..llm.client import StructuredLLMClient
from ..receipts.parse import UnsupportedReceiptFormat
from ..receipts.pdf_text import PdfExtractionError
from ..receipts.pipeline import ImportResult, import_receipt_pdf
from .extract import pdf_attachments
from .mailbox import Mailbox

DEFAULT_RECEIPTS_DIR = Path("data/receipts")

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def default_receipts_dir() -> Path:
    """Where fetched PDFs are stored; override with `$NUTRIOLOGIST_RECEIPTS_DIR`."""
    return Path(os.environ.get("NUTRIOLOGIST_RECEIPTS_DIR", DEFAULT_RECEIPTS_DIR))


@dataclass
class PolledReceipt:
    """Outcome of importing one PDF attachment from one message."""

    uid: str
    filename: str
    saved_path: Path
    result: ImportResult | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class PollSummary:
    messages_seen: int = 0
    receipts: list[PolledReceipt] = field(default_factory=list)

    @property
    def imported(self) -> int:
        return sum(1 for r in self.receipts if r.ok and r.result and not r.result.duplicate)

    @property
    def duplicates(self) -> int:
        return sum(1 for r in self.receipts if r.ok and r.result and r.result.duplicate)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.receipts if not r.ok)


def _safe_filename(uid: str, filename: str) -> str:
    """A collision-resistant, path-safe name: `<uid>_<sanitized filename>`."""
    base = _UNSAFE_FILENAME.sub("_", filename).strip("_") or "receipt.pdf"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return f"{_UNSAFE_FILENAME.sub('_', uid)}_{base}"


def _save_pdf(receipts_dir: Path, uid: str, filename: str, content: bytes) -> Path:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    path = receipts_dir / _safe_filename(uid, filename)
    path.write_bytes(content)
    return path


def poll_mailbox(
    conn: sqlite3.Connection,
    mailbox: Mailbox,
    llm: StructuredLLMClient,
    *,
    receipts_dir: Path | None = None,
    mark_seen: bool = True,
) -> PollSummary:
    """Fetch unseen mail, import PDF receipts, return a per-message summary.

    Args:
        conn: open nutriologist DB connection.
        mailbox: source of unseen messages (real IMAP or a fake).
        llm: required — normalization and unknown-layout parsing need it.
        receipts_dir: where to save fetched PDFs (default `data/receipts/`).
        mark_seen: when False, never flag messages (dry-run / repeated testing).
    """
    receipts_dir = receipts_dir or default_receipts_dir()
    summary = PollSummary()

    for uid, raw in mailbox.fetch_unseen():
        summary.messages_seen += 1
        attachments = pdf_attachments(raw)

        message_had_error = False
        for filename, content in attachments:
            path = _save_pdf(receipts_dir, uid, filename, content)
            polled = PolledReceipt(uid=uid, filename=filename, saved_path=path)
            try:
                polled.result = import_receipt_pdf(conn, path, llm)
            except (UnsupportedReceiptFormat, PdfExtractionError) as exc:
                polled.error = str(exc)
                message_had_error = True
            summary.receipts.append(polled)

        if mark_seen and not message_had_error:
            mailbox.mark_seen(uid)

    return summary
