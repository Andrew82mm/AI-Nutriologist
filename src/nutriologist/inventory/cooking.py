"""Cook a dish from inventory ingredients.

The user's flow (decided earlier): type a dish name, list ingredients + weights;
the system consumes those ingredients from inventory, records the recipe, and —
crucially — stocks the finished dish as its own inventory product so leftovers
can be eaten down later ("съел 300г борща"). This avoids double-counting: the
ingredients leave stock and an equal dish enters it.

БЖУ of the dish per 100 g = Σ(ingredient per-100 × grams/100) / yield × 100,
where yield is the user-entered cooked weight (fallback: sum of raw weights).
"""

from __future__ import annotations

import json
import sqlite3

from ..llm.client import StructuredLLMClient
from ..products.models import NutritionFacts, Product
from ..products.nutrition import resolve_nutrition, save_nutrition
from . import ledger

_DISH_CATEGORY = "блюда"


def _get_or_create_dish_product(conn: sqlite3.Connection, name: str) -> Product:
    """Get-or-create the inventory product that represents a cooked dish."""
    row = conn.execute(
        "SELECT id, canonical_name, category, is_food, canonical_unit "
        "FROM products WHERE canonical_name = ?",
        (name,),
    ).fetchone()
    if row is not None:
        return Product(
            id=row["id"],
            canonical_name=row["canonical_name"],
            category=row["category"],
            is_food=bool(row["is_food"]),
            canonical_unit=row["canonical_unit"],
        )
    cursor = conn.execute(
        "INSERT INTO products (canonical_name, category, is_food, canonical_unit) "
        "VALUES (?, ?, 1, 'g')",
        (name, _DISH_CATEGORY),
    )
    return Product(
        id=cursor.lastrowid,
        canonical_name=name,
        category=_DISH_CATEGORY,
        is_food=True,
        canonical_unit="g",
    )


def _dish_nutrition(
    conn: sqlite3.Connection,
    ingredients: list[tuple[Product, float]],
    yield_grams: float,
    recipe_id: int,
    llm: StructuredLLMClient | None,
) -> NutritionFacts:
    """Per-100 g macros of the dish, summed from ingredients and scaled by yield.

    Ingredients whose nutrition can't be resolved contribute 0 (the dish estimate
    is best-effort). Marked source='user' — a cooked dish is authored, not an
    LLM guess about a generic product.
    """
    totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    for product, grams in ingredients:
        facts = resolve_nutrition(conn, product, llm=llm)
        if facts is None:
            continue
        fraction = grams / 100.0
        totals["kcal"] += (facts.kcal or 0.0) * fraction
        totals["protein"] += (facts.protein or 0.0) * fraction
        totals["fat"] += (facts.fat or 0.0) * fraction
        totals["carbs"] += (facts.carbs or 0.0) * fraction

    scale = 100.0 / yield_grams
    return NutritionFacts(
        kcal=round(totals["kcal"] * scale, 1),
        protein=round(totals["protein"] * scale, 1),
        fat=round(totals["fat"] * scale, 1),
        carbs=round(totals["carbs"] * scale, 1),
        source="user",
        source_ref=f"recipe:{recipe_id}",
    )


def cook_dish(
    conn: sqlite3.Connection,
    *,
    name: str,
    ingredients: list[tuple[Product, float]],
    yield_grams: float | None = None,
    steps: list[str] | None = None,
    llm: StructuredLLMClient | None = None,
) -> Product:
    """Cook `name` from `ingredients` (product, grams); stock it as a dish product.

    Consumes each ingredient from inventory (`cooked −`), records the recipe,
    computes the dish's per-100 g БЖУ, and stocks `yield` grams of the dish
    (`cooked +`). `yield_grams` defaults to the sum of ingredient weights.
    `steps` (optional cooking instructions) are stored on the recipe so a
    planned dish keeps its instructions in the base. Returns the dish product.
    Re-cooking the same name adds another batch and refreshes the recipe/БЖУ to
    the latest (MVP: no separate batches); steps are only overwritten when given.
    """
    steps_json = json.dumps([s for s in steps if s], ensure_ascii=False) if steps else None
    if not ingredients:
        raise ValueError("a dish needs at least one ingredient")
    for product, _grams in ingredients:
        if product.id is None:
            raise ValueError("every ingredient product must be persisted (has id)")

    effective_yield = (
        yield_grams if yield_grams is not None else sum(g for _p, g in ingredients)
    )
    if effective_yield <= 0:
        raise ValueError("dish yield must be positive")

    # Recipe: get-or-create by unique name; a re-cook refreshes the definition.
    existing = conn.execute(
        "SELECT id FROM recipes WHERE name = ?", (name,)
    ).fetchone()
    if existing is not None:
        recipe_id = existing["id"]
        # COALESCE keeps existing steps when this cook didn't supply new ones.
        conn.execute(
            "UPDATE recipes SET yield_grams = ?, steps = COALESCE(?, steps) WHERE id = ?",
            (effective_yield, steps_json, recipe_id),
        )
        conn.execute(
            "DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,)
        )
    else:
        recipe_id = conn.execute(
            "INSERT INTO recipes (name, yield_grams, source, steps) VALUES (?, ?, 'user', ?)",
            (name, effective_yield, steps_json),
        ).lastrowid

    for product, grams in ingredients:
        conn.execute(
            "INSERT INTO recipe_ingredients (recipe_id, product_id, grams) "
            "VALUES (?, ?, ?)",
            (recipe_id, product.id, grams),
        )
        # Consume the raw ingredient from stock.
        ledger.record(
            conn,
            product_id=product.id,
            change_amount=-abs(grams),
            source_type="cooked",
            source_id=recipe_id,
            note=f"приготовлено: {name}",
        )

    dish = _get_or_create_dish_product(conn, name)
    conn.execute(
        "UPDATE recipes SET product_id = ? WHERE id = ?", (dish.id, recipe_id)
    )

    facts = _dish_nutrition(conn, ingredients, effective_yield, recipe_id, llm)
    save_nutrition(conn, dish.id, facts)

    # Stock the finished dish.
    ledger.record(
        conn,
        product_id=dish.id,
        change_amount=effective_yield,
        source_type="cooked",
        source_id=recipe_id,
        note=f"готовка: {name}",
    )

    conn.commit()
    return dish
