"""Chat parsing + write actions (log a meal, add bought goods).

The chat endpoint is intentionally two-step: `/api/chat` only *parses* a phrase
and returns a preview (what it understood), and the frontend commits it with an
explicit call to `/api/meals` or `/api/inventory`. That mirrors the prototype's
editable confirmation card and keeps side effects behind a deliberate user
action.

Product resolution is name-based get-or-create. Chat parsing is hybrid: the
rule-based parser yields canonical names, categories and per-100 macros for the
staples it knows (offline, free), and an LLM fallback covers unknown foods when
one is configured — see `chat()`.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..inventory import ledger
from ..inventory.cooking import cook_dish
from ..planner import suggest_recipes
from ..products.meal_parse import parse_cook_text, parse_meal_text
from ..products.models import Product
from ..products.product_match import (
    find_exact_or_normalized,
    head_stem,
    resolve_product,
    token_count,
)
from ..products.nutrition import resolve_nutrition
from . import foods
from .app import db_conn, get_optional_llm
from .diary import Macros, diary_today

router = APIRouter(prefix="/api", tags=["chat"])

_UNIT_LABELS = {"g": "г", "ml": "мл", "piece": "шт"}


# --- shared write helpers --------------------------------------------------
def ensure_product(
    conn: sqlite3.Connection,
    name: str,
    category: str | None,
    canonical_unit: str | None,
    *,
    resolver=find_exact_or_normalized,
) -> int:
    """Get-or-create a product by canonical name; backfill missing classification.

    By default the lookup is case/ё-insensitive (layers 1–2 of `product_match`)
    so «Салат» and «салат» don't spawn duplicate products, but no synonym/fuzzy
    matching — creation stays conservative to avoid merging distinct products.
    The meal-write path passes `resolver=resolve_product` so an eaten dish is
    attributed to (and drawn down from) a fuzzily-matched fridge product.
    """
    row = resolver(conn, name)
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

    Used by the manual meal form and chat, where the user types macros per 100 g
    (like a food label). We store them as this product's per-100 profile; the
    meal item is logged at its actual grams and the diary scales the portion from
    that. 'user' is the top-ranked source, so this is the user deliberately
    defining the product's nutrition.
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
        # Fuzzy-resolve so «капустный салат» is logged under (and draws down)
        # the existing «Салат из капусты» product instead of forking a new one.
        pid = ensure_product(
            conn, name, it.category, it.canonical_unit, resolver=resolve_product
        )
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

    # Fuzzy-resolve to an existing product so the preview reflects stored
    # nutrition + fridge stock even when the typed name is a case/synonym
    # variant («капустный салат» → «Салат из капусты», «бёдра» → «бедра»).
    prod = resolve_product(conn, name)
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
    # A staple's macros are only trusted on an *exact* name match: «творог 5%»
    # gets the staple, but «творог обезжиренный» must not be coerced onto it —
    # its variant is resolved through the cascade (dataset → LLM) on the full name.
    if per100 is None and exact:
        per100 = tuple(staple.per100)
    if per100 is None:
        facts = resolve_nutrition(
            conn, Product(canonical_name=name, is_food=True, canonical_unit=unit), llm=llm
        )
        if facts is not None:
            per100 = (facts.kcal or 0, facts.protein or 0, facts.fat or 0, facts.carbs or 0)
    # Last resort (offline, nothing in the dataset): a coarse non-exact staple
    # beats showing «?».
    if per100 is None and staple is not None:
        per100 = tuple(staple.per100)

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
    llm = get_optional_llm()
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


def _estimate_to_payload(est: dict) -> dict:
    """Reshape an `estimate_position` result into the chat item payload shape.

    Same keys as `_item_payload`, so LLM-resolved positions render and commit
    through exactly the same frontend cards and `POST /api/meals`/`inventory`
    paths as rule-based ones. Unknown macros (`known` is False) become zeros —
    the confirmation card still lets the user edit them.
    """
    return {
        "name": est["name"],
        "grams": est["grams"],
        "amount_canonical": est["amount_canonical"],
        "unit": est["unit_label"],
        "canonical_unit": est["canonical_unit"],
        "category": est["category"],
        "per100": est["per100"] or [0, 0, 0, 0],
        "kcal": est["kcal"] or 0,
        "protein": est["protein"] or 0,
        "fat": est["fat"] or 0,
        "carbs": est["carbs"] or 0,
    }


def _resolve_llm_item(conn: sqlite3.Connection, it, llm) -> dict:
    """Resolve one LLM-parsed meal position to a chat item payload.

    `it` is a `ParsedMealItem`. Its name/amount go through `estimate_position`
    (unit + portion КБЖУ + fridge presence via the nutrition cascade). When the
    phrase stated macros explicitly («хлеб с бжу 8,5 2,5 54»), those per-100 g
    numbers win: they override the resolved nutrition and are tagged
    `per100_source='user'`, so committing the meal teaches the product its macros.
    """
    payload = _estimate_to_payload(estimate_position(conn, it.name, it.amount, llm))
    user = it.user_macros
    if user is not None:
        p, f, c = user
        kcal100 = round(p * 4 + f * 9 + c * 4, 1)
        grams = payload["grams"] or 0
        k = grams / 100
        payload["per100"] = [kcal100, p, f, c]
        payload["per100_source"] = "user"
        payload["kcal"] = round(kcal100 * k)
        payload["protein"] = round(p * k, 1)
        payload["fat"] = round(f * k, 1)
        payload["carbs"] = round(c * k, 1)
    return payload


def _cook_response(conn: sqlite3.Connection, text: str) -> dict:
    """«Приготовил <блюдо> из …» — preview a cooked dish (no commit).

    Parses the dish + ingredient grams via the LLM and returns a preview card;
    the frontend commits with POST /api/cook/from-chat, which consumes the
    ingredients and stocks the dish. Read-only here (no products written).
    """
    llm = get_optional_llm()
    if llm is None:
        return {
            "intent": "cook",
            "text": "Чтобы записать готовку, настройте LLM в .env "
            "(LLM_PROVIDER, LLM_API_KEY, ...).",
        }
    try:
        parsed = parse_cook_text(text, llm)
    except Exception:
        parsed = None
    if parsed is None or not parsed.name or not parsed.ingredients:
        return {
            "intent": "cook",
            "text": "Не понял состав блюда. Напишите, например: «приготовил борщ: "
            "свёкла 300г, картофель 200г, говядина 250г».",
        }
    total = sum(i.grams for i in parsed.ingredients)
    return {
        "intent": "cook",
        "name": parsed.name,
        "yield_grams": parsed.yield_grams if parsed.yield_grams else total,
        "ingredients": [{"name": i.name, "grams": round(i.grams)} for i in parsed.ingredients],
    }


def _recipes_response(conn: sqlite3.Connection) -> dict:
    """«Что приготовить?» — real inventory-based suggestions when an LLM is set.

    Falls back to a plain hint (no hardcoded fake menu) when no LLM is configured
    or the fridge is empty, so the chat degrades gracefully offline.
    """
    llm = get_optional_llm()
    if llm is None:
        return {
            "intent": "recipes",
            "text": "Чтобы подобрать рецепты из ваших продуктов, настройте LLM в .env "
            "(LLM_PROVIDER, LLM_API_KEY, ...).",
        }
    try:
        ideas = suggest_recipes(conn, llm)
    except Exception:
        ideas = []
    if not ideas:
        return {
            "intent": "recipes",
            "text": "Пока нечего предложить — добавьте продукты в холодильник.",
        }
    lines = []
    for i in ideas:
        line = f"• {i.name}"
        if i.missing:
            line += f" (нужно докупить: {', '.join(i.missing)})"
        lines.append(line)
    return {"intent": "recipes", "text": "Можно приготовить:\n" + "\n".join(lines)}


def _offline_positions(conn: sqlite3.Connection, text: str, llm) -> list[dict]:
    """Resolve arbitrary products offline by splitting the phrase into positions.

    Each chunk (from `foods.split_positions`) is cleaned to a name + amount and
    run through `estimate_position` — the same DB + Скурихин-dataset cascade the
    online path uses, which needs no LLM. Only chunks that resolve to known
    macros become items; filler chunks («обед», a stray verb) drop out. This is
    what lets the offline chat recognize products stored in the DB or the dataset,
    not just the 11 staples `foods.parse_foods` hardcodes.
    """
    items: list[dict] = []
    for chunk in foods.split_positions(text):
        name, amount = foods.extract_quantity(chunk)
        if not name:
            continue
        est = estimate_position(conn, name, amount, llm)
        if est["known"]:
            items.append(_estimate_to_payload(est))
    return items


def _merge_positions(staple_items: list[dict], split_items: list[dict]) -> list[dict]:
    """Combine the staple and chunk-resolved passes into one item per food.

    An exact-name dedup is too weak: the staple pass emits «творог 5%» while the
    user may have typed «творог обезжиренный», so they collide only on the head
    noun. Group by `head_stem` and keep the more specific name (more identity
    tokens); on a tie the staple wins (its canonical name is cleaner). Staples are
    listed first so ties resolve to them, and first-seen order is preserved.
    """
    by_head: dict[str, dict] = {}
    order: list[str] = []
    for it in staple_items + split_items:
        key = head_stem(it["name"]) or it["name"].lower()
        if key not in by_head:
            by_head[key] = it
            order.append(key)
        elif token_count(it["name"]) > token_count(by_head[key]["name"]):
            by_head[key] = it
    return [by_head[key] for key in order]


def _eat_response(items: list[dict], title: str | None) -> dict:
    total = Macros(
        kcal=round(sum(i.get("kcal") or 0 for i in items)),
        protein=round(sum(i.get("protein") or 0 for i in items)),
        fat=round(sum(i.get("fat") or 0 for i in items)),
        carbs=round(sum(i.get("carbs") or 0 for i in items)),
    )
    return {"intent": "eat", "items": items, "total": total.model_dump(), "title": title}


@router.post("/chat")
def chat(payload: ChatIn, conn: sqlite3.Connection = Depends(db_conn)) -> dict:
    """Parse a phrase and return a preview of the understood action (no commit).

    Hybrid parsing, LLM-primary: when a model is configured it extracts *every*
    position from the phrase — so mixed known+unknown foods and inline macros
    («150г творог обезжиренный … 32г хлеба с бжу 8,5 2,5 54 …») are all captured.
    The deterministic rule table (`foods`) is the offline fallback used only when
    no LLM is set (or it returned nothing). The verb-based intent wins when it's
    confident; otherwise we trust the LLM's eat/buy call.
    """
    text = payload.text.strip()
    intent = foods.detect_intent(text)

    if intent == "report":
        day = diary_today(conn)
        return {"intent": "report", "report": day.model_dump()}

    if intent == "cook":
        return _cook_response(conn, text)

    if intent == "recipes":
        return _recipes_response(conn)

    # LLM-primary path: one call extracts the whole item list + intent.
    llm = get_optional_llm()
    if llm is not None:
        try:
            res = parse_meal_text(text, llm)
        except Exception:
            res = None
        if res is not None and res.items:
            # Verb-based intent wins when it decided; else trust the LLM's.
            final_intent = intent if intent in ("buy", "eat") else res.intent
            items = [_resolve_llm_item(conn, it, llm) for it in res.items]
            if final_intent == "buy":
                return {"intent": "buy", "items": items}
            return _eat_response(items, foods.detect_meal_title(text))

    # Offline (no LLM) or the model found no food → deterministic resolution:
    # the rule-table staples merged with chunk-resolved arbitrary products
    # (DB + bundled Скурихин dataset), one item per food.
    staple_items = [_item_payload(p) for p in foods.parse_foods(text)]
    extra_items = _offline_positions(conn, text, llm)
    items = _merge_positions(staple_items, extra_items)
    if items:
        if intent == "buy":
            return {"intent": "buy", "items": items}
        return _eat_response(items, foods.detect_meal_title(text))

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
        yield_grams=payload.yield_grams, llm=get_optional_llm(),
    )
    return {"dish_id": dish.id, "name": dish.canonical_name}


class CookByNameIngredient(BaseModel):
    name: str
    grams: float


class CookFromChatRequest(BaseModel):
    name: str
    ingredients: list[CookByNameIngredient]
    yield_grams: float | None = None
    steps: list[str] | None = None  # optional cooking instructions (from the planner)


@router.post("/cook/from-chat")
def cook_from_chat(
    payload: CookFromChatRequest, conn: sqlite3.Connection = Depends(db_conn)
) -> dict:
    """Commit a dish parsed from chat: resolve ingredients by name, then cook.

    Unlike POST /api/cook (which takes product ids from the fridge form), this
    resolves each ingredient name to a product get-or-create, so a dish can be
    logged from free text even for products not yet on hand (they're consumed
    into a negative balance, mirroring the manual cook form)."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="нужно название блюда")
    if not payload.ingredients:
        raise HTTPException(status_code=400, detail="нужен хотя бы один ингредиент")

    ingredients = []
    for ing in payload.ingredients:
        ing_name = ing.name.strip()
        if not ing_name:
            continue
        pid = ensure_product(conn, ing_name, None, "g")
        ingredients.append((_load_product(conn, pid), ing.grams))
    if not ingredients:
        raise HTTPException(status_code=400, detail="нужен хотя бы один ингредиент")

    dish = cook_dish(
        conn, name=name, ingredients=ingredients,
        yield_grams=payload.yield_grams, steps=payload.steps, llm=get_optional_llm(),
    )
    return {"dish_id": dish.id, "name": dish.canonical_name}
