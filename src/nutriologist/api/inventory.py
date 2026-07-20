"""Inventory (холодильник) endpoints.

Read side of the ledger (current stock, last receipt) plus the fridge card's
quick actions — Съел / Приготовил / Выкинул — which are proportional ledger
decrements. Adding a product goes through `actions.add_inventory` (POST
/api/inventory); manual meals and chat "eat" live in `actions` too.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..inventory import ledger
from .app import db_conn

router = APIRouter(prefix="/api", tags=["inventory"])


class InventoryItem(BaseModel):
    """One on-hand product, as the fridge screen needs it.

    `amount` is in `unit` — the product's canonical unit (``g`` | ``ml`` |
    ``piece``). Display formatting (г/мл/шт) is the frontend's job.
    """

    product_id: int
    name: str
    category: str | None
    amount: float
    unit: str | None


@router.get("/inventory", response_model=list[InventoryItem])
def get_inventory(conn: sqlite3.Connection = Depends(db_conn)) -> list[InventoryItem]:
    """Current fridge contents: every product with a positive balance."""
    rows = ledger.current(conn)
    return [
        InventoryItem(
            product_id=row["product_id"],
            name=row["canonical_name"],
            category=row["category"],
            amount=round(row["qty_estimate"], 2),
            unit=row["canonical_unit"],
        )
        for row in rows
    ]


# --- last parsed receipt (fridge banner) -----------------------------------
class LastReceipt(BaseModel):
    store_name: str | None
    date: str | None          # DD.MM.YY, from purchased_at
    items_added: int          # products this receipt posted into inventory


def _fmt_date(raw: str | None) -> str | None:
    """A receipt's purchased_at (ISO-ish) → DD.MM.YY, or None."""
    if not raw:
        return None
    d = raw[:10]  # YYYY-MM-DD
    parts = d.split("-")
    if len(parts) == 3:
        y, m, day = parts
        return f"{day}.{m}.{y[2:]}"
    return raw


@router.get("/receipts/last", response_model=LastReceipt | None)
def last_receipt(conn: sqlite3.Connection = Depends(db_conn)) -> LastReceipt | None:
    """The chronologically latest parsed receipt, or None if there are none."""
    r = conn.execute(
        "SELECT id, store_name, purchased_at, created_at FROM receipts "
        "ORDER BY COALESCE(purchased_at, created_at) DESC, id DESC LIMIT 1"
    ).fetchone()
    if r is None:
        return None
    count = conn.execute(
        "SELECT COUNT(*) FROM inventory_ledger WHERE source_type = 'receipt' AND source_id = ?",
        (r["id"],),
    ).fetchone()[0]
    return LastReceipt(
        store_name=r["store_name"],
        date=_fmt_date(r["purchased_at"] or r["created_at"]),
        items_added=count,
    )


# --- fridge card quick actions ---------------------------------------------
# «Выкинул» (throw out) writes off the whole remaining stock. It is inventory-only
# and never touches the diary — eating is logged there, drawing stock down as a
# side effect (POST /api/meals in `actions`). Cooking is its own flow (POST
# /api/cook), reached from the "add product or dish" form.
class InventoryAction(BaseModel):
    action: str  # 'trash'


@router.post("/inventory/{product_id}/action")
def inventory_action(
    product_id: int, payload: InventoryAction, conn: sqlite3.Connection = Depends(db_conn)
) -> dict:
    """Write a product off the fridge: Выкинул (all remaining stock).

    A signed 'manual' ledger transaction, so the drop is auditable and reversible
    like any other inventory change. Not a meal — no КБЖУ is recorded.
    """
    row = conn.execute(
        "SELECT canonical_unit FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="продукт не найден")

    if payload.action != "trash":
        raise HTTPException(status_code=400, detail=f"неизвестное действие: {payload.action}")

    balance = ledger.balance(conn, product_id)
    if balance <= 0:
        return {"balance": 0}

    ledger.record(
        conn, product_id=product_id, change_amount=-abs(balance),
        source_type="manual", note=payload.action,
    )
    conn.commit()
    return {"balance": 0}
