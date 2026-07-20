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
from ..inventory.cooking import cook_dish
from ..products.models import Product
from ..products.nutrition import resolve_nutrition
from . import foods
from .app import db_conn
from .diary import Macros, diary_today

router = APIRouter(prefix="/api", tags=["chat"])

_UNIT_LABELS = {"g": "г", "ml": "мл", "piece": "шт"}


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
    # 'user' when the macros were hand-entered/overridden in the form — then they
    # overwrite the product's stored nutrition (the app "learns" the product).
    # Anything else is treated as trusted dataset data ('db'), which never
    # downgrades an existing row.
    per100_source: str = "db"


class MealCreate(BaseModel):
    items: list[FoodItem]
    raw_text: str = ""
    title: str | None = None


def _clean_title(title: str | None) -> str | None:
    """Empty/whitespace title → None, so the diary falls back to time-of-day."""
    return title.strip() if title and title.strip() else None


class InventoryAdd(BaseModel):
    items: list[FoodItem]


class ChatIn(BaseModel):
    text: str


# --- write helper: one canonical path for logging a meal -------------------
def _write_meal_items(conn: sqlite3.Connection, meal_id: int, items: list[FoodItem]) -> None:
    """Store each position and draw its product down from the fridge if stocked.

    Two effects per item:
    - a `meal_items` row storing grams (weight, for macros) plus the amount in the
      product's canonical unit; the diary derives БЖУ from grams via `nutrition`;
    - a `meal (−)` ledger transaction **only when the product is currently in the
      fridge** (positive balance). Food eaten out (шаурма) matches nothing on hand,
      so it never touches stock — the diary and the fridge stay independent, linked
      only when you eat something you actually have.

    Nutrition: hand-entered macros (`per100_source == 'user'`) overwrite the
    product's stored per-100 profile — so the app learns e.g. «Вафли голландские с
    яблоком». Trusted/dataset macros only backfill (never downgrade). Positions
    with no known macros (the «?» case) write no nutrition row at all.
    """
    for it in items:
        name = it.name.strip()
        if not name:
            continue
        pid = ensure_product(conn, name, it.category, it.canonical_unit)
        per100 = tuple(it.per100) if it.per100 else (0, 0, 0, 0)
        if any(per100):
            if it.per100_source == "user":
                set_user_nutrition(conn, pid, per100)
            else:
                ensure_nutrition(conn, pid, per100)
        amount = it.amount_canonical if it.amount_canonical is not None else it.grams
        conn.execute(
            "INSERT INTO meal_items (meal_id, product_id, grams, amount_canonical, grams_source) "
            "VALUES (?, ?, ?, ?, 'user')",
            (meal_id, pid, it.grams, amount),
        )
        if ledger.balance(conn, pid) > 0:
            ledger.record(
                conn, product_id=pid, change_amount=-abs(amount),
                source_type="meal", source_id=meal_id,
            )


def _clear_meal(conn: sqlite3.Connection, meal_id: int) -> None:
    """Remove a meal's items and any inventory decrements it posted."""
    conn.execute("DELETE FROM meal_items WHERE meal_id = ?", (meal_id,))
    conn.execute(
        "DELETE FROM inventory_ledger WHERE source_type = 'meal' AND source_id = ?",
        (meal_id,),
    )


# --- endpoints -------------------------------------------------------------
@router.post("/meals")
def create_meal(payload: MealCreate, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Log one eaten meal (the single canonical write path for chat and the form)."""
    # 'localtime' so the meal lands on the user's calendar day — the diary filters
    # "today" by the local date, and the time-of-day title reads the local hour.
    meal_id = conn.execute(
        "INSERT INTO meals (ts, raw_text, title) VALUES (datetime('now', 'localtime'), ?, ?)",
        (payload.raw_text, _clean_title(payload.title)),
    ).lastrowid
    _write_meal_items(conn, meal_id, payload.items)
    conn.commit()
    return {"meal_id": meal_id}


@router.put("/meals/{meal_id}")
def update_meal(meal_id: int, payload: MealCreate, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Replace a meal's positions from the edit form."""
    if conn.execute("SELECT 1 FROM meals WHERE id = ?", (meal_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="приём не найден")
    _clear_meal(conn, meal_id)
    conn.execute(
        "UPDATE meals SET title = ? WHERE id = ?", (_clean_title(payload.title), meal_id)
    )
    _write_meal_items(conn, meal_id, payload.items)
    conn.commit()
    return {"meal_id": meal_id}


# --- live macro estimate for the meal form ---------------------------------
class EstimatePos(BaseModel):
    name: str
    amount: float | None = None  # in the product's canonical unit; None → default


class EstimateIn(BaseModel):
    items: list[EstimatePos]


def estimate_position(
    conn: sqlite3.Connection, name: str, amount: float | None, llm
) -> dict:
    """Resolve one meal position to unit, portion КБЖУ, and fridge presence.

    Cascade for the per-100 profile: an existing product's stored nutrition →
    the rule-based staple table → the nutrition resolver (dataset, then LLM if
    configured). If nothing resolves, `known` is False and macros are None — the
    form shows «?» and lets the user type them. Does not create products or write
    anything; commit happens later via POST /api/meals.
    """
    name = (name or "").strip()
    out = {
        "name": name, "canonical_unit": "g", "unit_label": "г",
        "amount": amount, "grams": 0.0, "amount_canonical": 0.0,
        "per100": None, "kcal": None, "protein": None, "fat": None, "carbs": None,
        "known": False, "in_fridge": False, "fridge_balance": 0.0, "category": None,
    }
    if not name:
        return out

    prod = conn.execute(
        "SELECT id, category, canonical_unit, piece_weight_grams "
        "FROM products WHERE canonical_name = ?",
        (name,),
    ).fetchone()
    # A staple gives us unit + per-100 for a known food. Prefer an exact
    # canonical-name hit (so «яйцо куриное» wins over the «куриное филе» keyword
    # it also brushes); otherwise accept an unambiguous single match.
    parsed = foods.parse_foods(name)
    exact = [p for p in parsed if p.name.lower() == name.lower()]
    staple = exact[0] if exact else (parsed[0] if len(parsed) == 1 else None)

    unit = (
        (prod["canonical_unit"] if prod and prod["canonical_unit"] else None)
        or (staple.canonical_unit if staple else None)
        or "g"
    )
    out["canonical_unit"] = unit
    out["unit_label"] = _UNIT_LABELS.get(unit, unit)
    out["category"] = (
        (prod["category"] if prod and prod["category"] else None)
        or (staple.cat if staple else None)
    )

    per100 = None
    if prod:
        nrow = conn.execute(
            "SELECT kcal, protein, fat, carbs FROM nutrition WHERE product_id = ?",
            (prod["id"],),
        ).fetchone()
        if nrow:
            per100 = (nrow["kcal"] or 0, nrow["protein"] or 0, nrow["fat"] or 0, nrow["carbs"] or 0)
    if per100 is None and staple:
        per100 = tuple(staple.per100)
    if per100 is None:
        facts = resolve_nutrition(
            conn, Product(canonical_name=name, is_food=True, canonical_unit=unit), llm=llm
        )
        if facts is not None:
            per100 = (facts.kcal or 0, facts.protein or 0, facts.fat or 0, facts.carbs or 0)

    if unit == "piece":
        gpu = None
        if staple and staple.amount_canonical:
            gpu = staple.grams / staple.amount_canonical
        elif prod and prod["piece_weight_grams"]:
            gpu = prod["piece_weight_grams"]
        gpu = gpu or 100.0
        count = amount if amount is not None else (staple.amount_canonical if staple else 1)
        count = max(0, round(count))
        macro_grams = count * gpu
        amount_canonical = count
    else:
        default_g = staple.grams if staple else 100
        macro_grams = amount if amount is not None else default_g
        macro_grams = max(0.0, round(macro_grams))
        amount_canonical = macro_grams

    out["grams"] = macro_grams
    out["amount_canonical"] = amount_canonical
    out["amount"] = amount_canonical

    if per100 is not None and any(per100):
        k = macro_grams / 100
        out["per100"] = [round(x, 1) for x in per100]
        out["kcal"] = round(per100[0] * k)
        out["protein"] = round(per100[1] * k, 1)
        out["fat"] = round(per100[2] * k, 1)
        out["carbs"] = round(per100[3] * k, 1)
        out["known"] = True

    if prod:
        bal = ledger.balance(conn, prod["id"])
        out["fridge_balance"] = round(bal, 2)
        out["in_fridge"] = bal > 0

    return out


@router.post("/meals/estimate")
def estimate_meal(payload: EstimateIn, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Preview unit + portion КБЖУ + fridge presence for each typed position."""
    llm = _optional_llm()
    return {"items": [estimate_position(conn, it.name, it.amount, llm) for it in payload.items]}


@router.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int, conn: sqlite3.Connection = Depends(db_conn)) -> None:
    """Delete a meal, its items, and any inventory decrements it posted."""
    _clear_meal(conn, meal_id)
    conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    conn.commit()


@router.post("/inventory")
def add_inventory(payload: InventoryAdd, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Add bought goods to the fridge (manual ledger income).

    An explicit add is authoritative about the product's classification, so a
    provided category/unit overwrites what the product had (e.g. re-adding a
    previously miscategorized item corrects it) — unlike the get-or-create
    default, which only backfills nulls.
    """
    added = 0
    for it in payload.items:
        pid = ensure_product(conn, it.name, it.category, it.canonical_unit)
        if it.category or it.canonical_unit:
            conn.execute(
                "UPDATE products SET category = COALESCE(?, category), "
                "canonical_unit = COALESCE(?, canonical_unit) WHERE id = ?",
                (it.category, it.canonical_unit, pid),
            )
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
            "title": foods.detect_meal_title(text),
        }

    return {
        "intent": "unknown",
        "text": "Не совсем понял. Попробуйте: «съел творог 5% 200 г», "
        "«купил кило абрикосов», «отчёт за день» или «что приготовить?».",
    }


# --- cooking (Приготовил) --------------------------------------------------
class CookIngredient(BaseModel):
    product_id: int
    grams: float


class CookRequest(BaseModel):
    name: str
    ingredients: list[CookIngredient]
    yield_grams: float | None = None  # cooked weight; defaults to Σ ingredient grams


def _load_product(conn: sqlite3.Connection, product_id: int) -> Product:
    row = conn.execute(
        "SELECT id, canonical_name, category, is_food, canonical_unit, piece_weight_grams "
        "FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"продукт {product_id} не найден")
    return Product(
        id=row["id"], canonical_name=row["canonical_name"], category=row["category"],
        is_food=bool(row["is_food"]), canonical_unit=row["canonical_unit"],
        piece_weight_grams=row["piece_weight_grams"],
    )


def _optional_llm():
    """An LLM client if one is configured, else None (cooking works without it)."""
    try:
        from ..llm.config import load_llm_client_from_env

        return load_llm_client_from_env()
    except Exception:
        return None


@router.post("/cook")
def cook(payload: CookRequest, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Cook a dish: consume the chosen ingredients, stock the finished dish.

    Ingredients (product + grams) leave inventory; a dish product with the given
    name enters it. Its per-100 БЖУ is summed from the ingredients' nutrition and
    scaled by the cooked yield (LLM fills gaps for ingredients with no known
    nutrition, if one is configured — otherwise it's pure arithmetic).
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="нужно название блюда")
    if not payload.ingredients:
        raise HTTPException(status_code=400, detail="нужен хотя бы один ингредиент")

    ingredients = [
        (_load_product(conn, ing.product_id), ing.grams) for ing in payload.ingredients
    ]
    dish = cook_dish(
        conn, name=name, ingredients=ingredients,
        yield_grams=payload.yield_grams, llm=_optional_llm(),
    )
    return {"dish_id": dish.id, "name": dish.canonical_name}
