"""Lazy normalization pass over a saved receipt's items.

Kept separate from `receipts.save_receipt` on purpose: importing a receipt
stays cheap and offline (no LLM, no network), and normalization runs later on
demand. This fills in `receipt_items.product_id` for lines that don't have it
yet, using the owning receipt's store for the alias cache key.
"""

from __future__ import annotations

import sqlite3

from ..llm.client import StructuredLLMClient
from .normalize import normalize_product


def normalize_receipt_items(
    conn: sqlite3.Connection, receipt_id: int, llm: StructuredLLMClient
) -> int:
    """Normalize every not-yet-linked item of `receipt_id`. Returns the count.

    Idempotent: items that already have a product_id are skipped, so re-running
    only processes what's new.
    """
    receipt = conn.execute(
        "SELECT store_name FROM receipts WHERE id = ?", (receipt_id,)
    ).fetchone()
    if receipt is None:
        raise ValueError(f"receipt {receipt_id} not found")
    store_name = receipt["store_name"]

    items = conn.execute(
        "SELECT id, raw_name FROM receipt_items "
        "WHERE receipt_id = ? AND product_id IS NULL",
        (receipt_id,),
    ).fetchall()

    normalized = 0
    for item in items:
        result = normalize_product(
            conn, store_name=store_name, raw_name=item["raw_name"], llm=llm
        )
        conn.execute(
            "UPDATE receipt_items SET product_id = ? WHERE id = ?",
            (result.product.id, item["id"]),
        )
        normalized += 1

    conn.commit()
    return normalized
