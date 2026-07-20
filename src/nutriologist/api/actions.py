"""Chat parsing + write actions (log a meal, add bought goods).

The chat endpoint is intentionally two-step: `/api/chat` only *parses* a phrase
and returns a preview (what it understood), and the frontend commits it with an
explicit call to `/api/meals` or `/api/inventory`. That mirrors the prototype's
editable confirmation card and keeps side effects behind a deliberate user
action.

Product resolution here is name-based get-or-create (no LLM): the rule-based
parser already yields canonical names, categories and per-100 macros for the
staples it knows, which is enough to log meals and stock the fridge offline.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..inventory import ledger
from . import foods
from .app import db_conn
from .diary import Macros, diary_today

router = APIRouter(prefix="/api", tags=["chat"])


# --- shared write helpers --------------------------------------------------
def ensure_product(
    conn: sqlite3.Connection, name: str, category: str | None, canonical_unit: str | None
) -> int:
    """Get-or-create a product by canonical name; backfill missing classification."""
    row = conn.execute(
        "SELECT id, category, canonical_unit FROM products WHERE canonical_name = ?", (name,)
    ).fetchone()
    if row is not None:
        if (row["category"] is None and category) or (row["canonical_unit"] is None and canonical_unit):
            conn.execute(
                "UPDATE products SET category = COALESCE(category, ?), "
                "canonical_unit = COALESCE(canonical_unit, ?) WHERE id = ?",
                (category, canonical_unit, row["id"]),
            )
        return row["id"]
    return conn.execute(
        "INSERT INTO products (canonical_name, category, is_food, canonical_unit) "
        "VALUES (?, ?, 1, ?)",
        (name, category, canonical_unit),
    ).lastrowid


def ensure_nutrition(conn: sqlite3.Connection, product_id: int, per100: tuple) -> None:
    """Upsert per-100 macros as a trusted ('db') source, if none exists yet."""
    kcal, protein, fat, carbs = per100
    conn.execute(
        "INSERT INTO nutrition (product_id, kcal, protein, fat, carbs, source, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'db', datetime('now')) "
        "ON CONFLICT(product_id) DO NOTHING",
        (product_id, kcal, protein, fat, carbs),
    )


def set_user_nutrition(conn: sqlite3.Connection, product_id: int, macros: tuple) -> None:
    """Overwrite a product's nutrition with hand-entered ('user') macros.

    Used by the manual meal form, where the user types macros per position. We
    store them as this product's per-100 profile and log the item at grams=100,
    so the diary recomputes exactly the typed numbers. 'user' is the top-ranked
    source, so this is the user deliberately defining the product's nutrition.
    """
    kcal, protein, fat, carbs = macros
    conn.execute(
        "INSERT INTO nutrition (product_id, kcal, protein, fat, carbs, source, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'user', datetime('now')) "
        "ON CONFLICT(product_id) DO UPDATE SET "
        "kcal=excluded.kcal, protein=excluded.protein, fat=excluded.fat, "
        "carbs=excluded.carbs, source='user', updated_at=datetime('now')",
        (product_id, kcal, protein, fat, carbs),
    )


# --- request models --------------------------------------------------------
class FoodItem(BaseModel):
    name: str
    grams: float                 # weight, for macros
    amount_canonical: float | None = None  # ledger amount (pieces for шт), defaults to grams
    unit: str | None = None
    canonical_unit: str | None = "g"
    category: str | None = None
    per100: list[float] = [0, 0, 0, 0]


class MealCreate(BaseModel):
    items: list[FoodItem]
    raw_text: str = ""


class InventoryAdd(BaseModel):
    items: list[FoodItem]


class ChatIn(BaseModel):
    text: str


# --- endpoints -------------------------------------------------------------
@router.post("/meals")
def create_meal(payload: MealCreate, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Log one eaten meal and decrement each eaten product from the fridge.

    Two effects per item:
    - a `meal_items` row storing grams (weight) — the diary derives БЖУ from it
      via the nutrition table;
    - a `meal (−)` ledger transaction in the product's canonical unit (pieces
      for шт, grams/ml otherwise), so eating draws the stock down. Balances may
      go negative if you eat more than the tracked stock — that's the ledger's
      nature, and `ledger.current` simply stops showing a product at ≤ 0.
    """
    meal_id = conn.execute(
        "INSERT INTO meals (ts, raw_text) VALUES (datetime('now'), ?)", (payload.raw_text,)
    ).lastrowid
    for it in payload.items:
        pid = ensure_product(conn, it.name, it.category, it.canonical_unit)
        ensure_nutrition(conn, pid, tuple(it.per100))
        conn.execute(
            "INSERT INTO meal_items (meal_id, product_id, grams, grams_source) "
            "VALUES (?, ?, ?, 'user')",
            (meal_id, pid, it.grams),
        )
        amount = it.amount_canonical if it.amount_canonical is not None else it.grams
        ledger.record(
            conn, product_id=pid, change_amount=-abs(amount),
            source_type="meal", source_id=meal_id,
        )
    conn.commit()
    return {"meal_id": meal_id}


# --- manual meal add / edit / delete (the meal form) -----------------------
class ManualItem(BaseModel):
    name: str
    kcal: float = 0
    protein: float = 0
    fat: float = 0
    carbs: float = 0


class ManualMeal(BaseModel):
    items: list[ManualItem]
    raw_text: str = ""


def _write_manual_items(conn: sqlite3.Connection, meal_id: int, items: list[ManualItem]) -> None:
    """Store each typed position as a product logged at grams=100 with its macros.

    Macros drive the diary. Inventory is drawn down separately: the free-text
    position name is run through the same phrase parser as chat's `eat`, and any
    recognized product + amount posts a `meal (−)` ledger transaction. Names that
    parse to nothing (e.g. «Овсянка с бананом») still count for calories but
    don't touch the fridge — there's nothing to match.
    """
    for it in items:
        name = it.name.strip()
        if not name:
            continue
        pid = ensure_product(conn, name, None, "g")
        set_user_nutrition(conn, pid, (it.kcal, it.protein, it.fat, it.carbs))
        conn.execute(
            "INSERT INTO meal_items (meal_id, product_id, grams, grams_source) "
            "VALUES (?, ?, 100, 'user')",
            (meal_id, pid),
        )
        for pf in foods.parse_foods(name):
            rpid = ensure_product(conn, pf.name, pf.cat, pf.canonical_unit)
            ledger.record(
                conn, product_id=rpid, change_amount=-abs(pf.amount_canonical),
                source_type="meal", source_id=meal_id,
            )


def _clear_meal(conn: sqlite3.Connection, meal_id: int) -> None:
    """Remove a meal's items and any inventory decrements it posted."""
    conn.execute("DELETE FROM meal_items WHERE meal_id = ?", (meal_id,))
    conn.execute(
        "DELETE FROM inventory_ledger WHERE source_type = 'meal' AND source_id = ?",
        (meal_id,),
    )


@router.post("/meals/manual")
def create_manual_meal(payload: ManualMeal, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Create a meal from hand-entered positions (name + kcal/Б/Ж/У each)."""
    meal_id = conn.execute(
        "INSERT INTO meals (ts, raw_text) VALUES (datetime('now'), ?)", (payload.raw_text,)
    ).lastrowid
    _write_manual_items(conn, meal_id, payload.items)
    conn.commit()
    return {"meal_id": meal_id}


@router.put("/meals/{meal_id}")
def update_meal(meal_id: int, payload: ManualMeal, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Replace a meal's positions from the edit form (redefines it as manual)."""
    if conn.execute("SELECT 1 FROM meals WHERE id = ?", (meal_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="приём не найден")
    _clear_meal(conn, meal_id)
    _write_manual_items(conn, meal_id, payload.items)
    conn.commit()
    return {"meal_id": meal_id}


@router.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int, conn: sqlite3.Connection = Depends(db_conn)) -> None:
    """Delete a meal, its items, and any inventory decrements it posted."""
    _clear_meal(conn, meal_id)
    conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    conn.commit()


@router.post("/inventory")
def add_inventory(payload: InventoryAdd, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Add bought goods to the fridge (manual ledger income)."""
    added = 0
    for it in payload.items:
        pid = ensure_product(conn, it.name, it.category, it.canonical_unit)
        ensure_nutrition(conn, pid, tuple(it.per100))
        amount = it.amount_canonical if it.amount_canonical is not None else it.grams
        ledger.record(conn, product_id=pid, change_amount=amount, source_type="manual", note="chat")
        added += 1
    conn.commit()
    return {"added": added}


def _item_payload(p: foods.ParsedFood) -> dict:
    return {
        "name": p.name,
        "grams": p.grams,
        "amount_canonical": p.amount_canonical,
        "unit": p.unit,
        "canonical_unit": p.canonical_unit,
        "category": p.cat,
        "per100": list(p.per100),
        "kcal": p.kcal,
        "protein": p.protein,
        "fat": p.fat,
        "carbs": p.carbs,
    }


@router.post("/chat")
def chat(payload: ChatIn, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Parse a phrase and return a preview of the understood action (no commit)."""
    text = payload.text.strip()
    intent = foods.detect_intent(text)

    if intent == "report":
        day = diary_today(conn)
        return {"intent": "report", "report": day.model_dump()}

    if intent == "recipes":
        return {
            "intent": "recipes",
            "text": "Судя по остаткам, можно приготовить: жаркое (картофель + говядина) "
            "или творожную запеканку (творог + яйцо). Полное меню — на вкладке «План».",
        }

    parsed = foods.parse_foods(text)

    if intent == "buy" and parsed:
        return {"intent": "buy", "items": [_item_payload(p) for p in parsed]}

    if (intent == "eat" or parsed) and parsed:
        total = Macros(
            kcal=round(sum(p.kcal for p in parsed)),
            protein=round(sum(p.protein for p in parsed)),
            fat=round(sum(p.fat for p in parsed)),
            carbs=round(sum(p.carbs for p in parsed)),
        )
        return {
            "intent": "eat",
            "items": [_item_payload(p) for p in parsed],
            "total": total.model_dump(),
        }

    return {
        "intent": "unknown",
        "text": "Не совсем понял. Попробуйте: «съел творог 5% 200 г», "
        "«купил кило абрикосов», «отчёт за день» или «что приготовить?».",
    }
