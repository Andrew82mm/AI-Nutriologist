"""Low-level inventory ledger primitives.

Inventory is a ledger, not a mutable counter: every change
is a signed row in `inventory_ledger`, and the current stock of a product is the
SUM of its rows (`v_inventory_current`). Everything higher-level — receipt
income, manual add/remove, eating, cooking — is built on `record` below.
"""

from __future__ import annotations

import sqlite3

# Allowed source_type values (mirror of the schema CHECK). 'cooked' covers both
# consuming ingredients and stocking the finished dish during cook_dish.
SOURCE_TYPES = frozenset({"receipt", "meal", "manual", "cooked"})


def record(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    change_amount: float,
    source_type: str,
    source_id: int | None = None,
    note: str | None = None,
) -> int:
    """Append one signed transaction to the ledger. Returns its row id.

    `change_amount` is in the product's `canonical_unit` (g/ml/piece); negative
    for consumption. Does not commit — the calling operation owns the transaction
    boundary so multi-row flows (cooking) stay atomic.
    """
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"unknown source_type: {source_type!r}")
    cursor = conn.execute(
        "INSERT INTO inventory_ledger "
        "(product_id, change_amount, source_type, source_id, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (product_id, change_amount, source_type, source_id, note),
    )
    return cursor.lastrowid


def balance(conn: sqlite3.Connection, product_id: int) -> float:
    """Current stock of one product (SUM of its ledger rows; 0.0 if none)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(change_amount), 0.0) AS qty "
        "FROM inventory_ledger WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    return float(row["qty"])


def current(
    conn: sqlite3.Connection, *, include_zero: bool = False
) -> list[sqlite3.Row]:
    """Snapshot of on-hand products: qty + name/category/unit, joined to products.

    Zero/negative balances are hidden unless `include_zero=True` (a product can
    net to ≤0 after full consumption; it's not "in the fridge" anymore).
    """
    where = "" if include_zero else "WHERE v.qty_estimate > 0"
    return conn.execute(
        f"""
        SELECT p.id AS product_id,
               p.canonical_name,
               p.category,
               p.canonical_unit,
               v.qty_estimate
        FROM v_inventory_current v
        JOIN products p ON p.id = v.product_id
        {where}
        ORDER BY p.canonical_name
        """
    ).fetchall()
