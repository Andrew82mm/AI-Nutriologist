"""Inventory (холодильник) endpoints.

Read side of the ledger: what is currently on hand. Writes (manual add / remove)
are a later slice — they need product resolution (LLM) and are added once the
read path is proven end-to-end.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
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
