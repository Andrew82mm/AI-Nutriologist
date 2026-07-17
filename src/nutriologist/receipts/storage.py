"""Persist a ParsedReceipt to SQLite, deduplicating by (fd_number, fpd).

fd_number/fpd uniquely identify a fiscal receipt, so re-importing the same
receipt (e.g. a duplicate ОФД email) must not create a second row. Receipts
where the parser couldn't extract both fields (no fiscal fingerprint to
dedup against) are always saved — see `save_receipt`'s docstring.
"""

from __future__ import annotations

import sqlite3

from .models import ParsedReceipt


def save_receipt(conn: sqlite3.Connection, receipt: ParsedReceipt) -> int:
    """Insert `receipt` and its items, deduplicating on (fd_number, fpd).

    - If both `fd_number` and `fpd` are present and a receipt with that pair
      already exists, the existing receipt's id is returned and nothing new
      is written (idempotent re-import).
    - If either is missing, there is no reliable key to dedup on, so the
      receipt is always inserted (with NULL in whichever field is absent).
    """
    if receipt.fd_number is not None and receipt.fpd is not None:
        existing = conn.execute(
            "SELECT id FROM receipts WHERE fd_number = ? AND fpd = ?",
            (receipt.fd_number, receipt.fpd),
        ).fetchone()
        if existing is not None:
            return existing["id"]

    cursor = conn.execute(
        """
        INSERT INTO receipts
            (fd_number, fpd, store_name, purchased_at, total, raw_text, source_format)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt.fd_number,
            receipt.fpd,
            receipt.store_name,
            receipt.purchased_at.isoformat() if receipt.purchased_at else None,
            receipt.total,
            receipt.raw_text,
            receipt.source_format,
        ),
    )
    receipt_id = cursor.lastrowid

    conn.executemany(
        """
        INSERT INTO receipt_items
            (receipt_id, raw_name, qty, unit, unit_price, total, vat_rate, vat_amount)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                receipt_id,
                item.raw_name,
                item.quantity,
                item.unit,
                item.unit_price,
                item.total,
                item.vat_rate,
                item.vat_amount,
            )
            for item in receipt.items
        ],
    )

    conn.commit()
    return receipt_id
