"""Inventory income and simple consumption flows.

Built on `ledger.record`. Covers three of the user-facing operations: automatic
income from a normalized receipt, manual add ("bought without a receipt"), plain
removal ("threw it out / added too much"), and eating ("съел"). Cooking a dish
lives in `cooking.py`.
"""

from __future__ import annotations

import sqlite3

from ..llm.client import StructuredLLMClient
from ..products.models import Product
from ..products.normalize import normalize_product
from ..products.packaging import _UNIT_MAP
from . import ledger


def _item_grams(
    qty: float,
    unit: str | None,
    net_amount: float | None,
    canonical_unit: str | None,
) -> float | None:
    """Amount of product a receipt line puts into inventory, in canonical units.

    Priority: packaged goods carry a per-package `net_amount` (already canonical,
    e.g. "5х80г" -> 400 g) — the receipt `qty` counts packages, so total is
    `qty × net_amount`. Weight/volume goods have no net_amount; the receipt `unit`
    (кг/г/мл/л) is itself the measure, converted via `_UNIT_MAP`. Piece goods
    without a net_amount fall back to `qty` pieces. None -> can't tell, skip.
    """
    if net_amount is not None:
        return qty * net_amount
    mapped = _UNIT_MAP.get((unit or "").strip().lower())
    if mapped is not None:
        _canonical, factor = mapped
        return qty * factor
    if canonical_unit == "piece":
        return qty
    return None


def income_from_receipt(conn: sqlite3.Connection, receipt_id: int) -> int:
    """Post every edible, normalized line of a receipt into inventory (+).

    Idempotent: if this receipt already has `receipt` ledger rows, does nothing
    (a re-imported/re-run receipt must not double-count). Returns the number of
    lines posted. Requires `normalize_receipt_items` to have run first (needs
    `product_id`); lines still unlinked or non-food are skipped.
    """
    already = conn.execute(
        "SELECT 1 FROM inventory_ledger "
        "WHERE source_type = 'receipt' AND source_id = ? LIMIT 1",
        (receipt_id,),
    ).fetchone()
    if already is not None:
        return 0

    receipt = conn.execute(
        "SELECT store_name FROM receipts WHERE id = ?", (receipt_id,)
    ).fetchone()
    if receipt is None:
        raise ValueError(f"receipt {receipt_id} not found")
    store_name = receipt["store_name"]

    rows = conn.execute(
        """
        SELECT ri.qty, ri.unit, ri.product_id,
               p.canonical_unit,
               pa.net_amount
        FROM receipt_items ri
        JOIN products p ON p.id = ri.product_id
        LEFT JOIN product_aliases pa
               ON pa.store_name = ? AND pa.raw_name = ri.raw_name
        WHERE ri.receipt_id = ? AND ri.product_id IS NOT NULL AND p.is_food = 1
        """,
        (store_name, receipt_id),
    ).fetchall()

    posted = 0
    for row in rows:
        grams = _item_grams(
            row["qty"], row["unit"], row["net_amount"], row["canonical_unit"]
        )
        if grams is None or grams <= 0:
            continue
        ledger.record(
            conn,
            product_id=row["product_id"],
            change_amount=grams,
            source_type="receipt",
            source_id=receipt_id,
        )
        posted += 1

    conn.commit()
    return posted


def resolve_by_name(
    conn: sqlite3.Connection, name: str, llm: StructuredLLMClient
) -> Product:
    """Get-or-create a product from a free-form name (manual flows).

    Thin wrapper over `normalize_product` with no store (not cached — a manual
    name isn't a store's receipt line), reusing the same LLM classification so
    manual entries share canonical names with receipt-derived ones.
    """
    return normalize_product(conn, store_name=None, raw_name=name, llm=llm).product


def add_manual(
    conn: sqlite3.Connection,
    *,
    product: Product,
    grams: float,
    note: str | None = None,
) -> int:
    """Manual income (+): bought without a receipt, gift, market for cash."""
    if product.id is None:
        raise ValueError("product must be persisted (has id)")
    row_id = ledger.record(
        conn,
        product_id=product.id,
        change_amount=grams,
        source_type="manual",
        note=note,
    )
    conn.commit()
    return row_id


def remove(
    conn: sqlite3.Connection,
    *,
    product: Product,
    amount: float | str,
    note: str | None = None,
) -> int:
    """Manual removal (−): spoiled/thrown out, or an over-add correction.

    `amount="all"` removes exactly the current balance (zeroes the product).
    """
    if product.id is None:
        raise ValueError("product must be persisted (has id)")
    if amount == "all":
        qty = ledger.balance(conn, product.id)
    else:
        qty = float(amount)
    row_id = ledger.record(
        conn,
        product_id=product.id,
        change_amount=-abs(qty),
        source_type="manual",
        note=note,
    )
    conn.commit()
    return row_id


def eat(
    conn: sqlite3.Connection,
    *,
    items: list[tuple[Product, float]],
    raw_text: str,
    grams_source: str = "user",
) -> int:
    """Log a meal ("съел") and decrement each eaten product from inventory.

    Records one `meals` row + a `meal_items` row per item, and a `meal (−grams)`
    ledger transaction per item. `items` are already-parsed (product, grams)
    pairs — the natural-language parsing and bot UI are итерация 5, layered on
    top of this primitive. Returns the meal id.
    """
    meal_id = conn.execute(
        "INSERT INTO meals (ts, raw_text) VALUES (datetime('now'), ?)",
        (raw_text,),
    ).lastrowid

    for product, grams in items:
        if product.id is None:
            raise ValueError("product must be persisted (has id)")
        conn.execute(
            "INSERT INTO meal_items (meal_id, product_id, grams, grams_source) "
            "VALUES (?, ?, ?, ?)",
            (meal_id, product.id, grams, grams_source),
        )
        ledger.record(
            conn,
            product_id=product.id,
            change_amount=-abs(grams),
            source_type="meal",
            source_id=meal_id,
        )

    conn.commit()
    return meal_id
