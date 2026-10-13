"""Suggest dishes cookable from what's currently in the fridge.

A lighter companion to the day planner: no БЖУ math, just the LLM proposing a
few dishes given the on-hand product list, flagging what's missing for each.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from ..inventory import ledger
from ..llm.client import StructuredLLMClient


@dataclass
class RecipeIdea:
    name: str
    uses: list[str] = field(default_factory=list)     # on-hand products it uses
    missing: list[str] = field(default_factory=list)  # products you'd need to buy


@dataclass
class SavedRecipeItem:
    name: str
    grams: float


@dataclass
class SavedRecipe:
    """A recipe already saved to the base (created when a dish is cooked)."""
    id: int
    name: str
    yield_grams: float
    steps: list[str]
    ingredients: list[SavedRecipeItem]
    # Per-100 g macros of the finished dish (from the dish product's nutrition,
    # authored at cook time). May be zeros if nutrition couldn't be resolved.
    kcal: float
    protein: float
    fat: float
    carbs: float
    created_at: str


def list_saved_recipes(conn: sqlite3.Connection) -> list[SavedRecipe]:
    """All saved recipes, newest first, with ingredients + dish БЖУ per 100 g.

    БЖУ is read from the cooked-dish product's stored nutrition (no LLM calls) —
    the same numbers computed when the dish was cooked.
    """
    rows = conn.execute(
        """
        SELECT r.id, r.name, r.yield_grams, r.steps, r.created_at,
               n.kcal, n.protein, n.fat, n.carbs
        FROM recipes r
        LEFT JOIN nutrition n ON n.product_id = r.product_id
        ORDER BY r.created_at DESC, r.id DESC
        """
    ).fetchall()

    out: list[SavedRecipe] = []
    for r in rows:
        ing_rows = conn.execute(
            "SELECT p.canonical_name AS name, ri.grams AS grams "
            "FROM recipe_ingredients ri JOIN products p ON p.id = ri.product_id "
            "WHERE ri.recipe_id = ? ORDER BY ri.grams DESC",
            (r["id"],),
        ).fetchall()

        steps: list[str] = []
        if r["steps"]:
            try:
                steps = [str(s) for s in json.loads(r["steps"]) if str(s).strip()]
            except (json.JSONDecodeError, TypeError):
                steps = []

        ingredients = [SavedRecipeItem(name=i["name"], grams=i["grams"]) for i in ing_rows]
        out.append(
            SavedRecipe(
                id=r["id"],
                name=r["name"],
                yield_grams=r["yield_grams"] or sum(i.grams for i in ingredients),
                steps=steps,
                ingredients=ingredients,
                kcal=round(r["kcal"] or 0, 1),
                protein=round(r["protein"] or 0, 1),
                fat=round(r["fat"] or 0, 1),
                carbs=round(r["carbs"] or 0, 1),
                created_at=r["created_at"] or "",
            )
        )
    return out


def delete_recipe(conn: sqlite3.Connection, recipe_id: int) -> str:
    """Remove a saved recipe from the base. The cooked-dish product and its
    stock are intentionally left alone (leftovers you may still eat down).

    Returns: 'deleted' on success, 'missing' if no such recipe, or 'referenced'
    if a logged meal points at it (deleting would break diary history).
    """
    if conn.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone() is None:
        return "missing"
    if conn.execute(
        "SELECT 1 FROM meal_items WHERE recipe_id = ? LIMIT 1", (recipe_id,)
    ).fetchone() is not None:
        return "referenced"
    conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))
    conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    conn.commit()
    return "deleted"


_SCHEMA = {
    "type": "object",
    "properties": {
        "recipes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "uses": {"type": "array", "items": {"type": "string"}},
                    "missing": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "uses", "missing"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["recipes"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
Тебе дан список продуктов, которые есть дома. Предложи 2–4 блюда, которые можно \
из них приготовить. Для каждого блюда: name — название, uses — какие из \
имеющихся продуктов используются, missing — чего не хватает (пустой список, \
если хватает всего). Отдавай приоритет блюдам, для которых почти всё есть.
"""


def suggest_recipes(conn: sqlite3.Connection, llm: StructuredLLMClient) -> list[RecipeIdea]:
    """Return a few dish ideas based on current inventory."""
    on_hand = [row["canonical_name"] for row in ledger.current(conn)]
    if not on_hand:
        return []

    data = llm.generate_json(
        system=_SYSTEM_PROMPT,
        user="Есть дома: " + ", ".join(on_hand) + ".",
        json_schema=_SCHEMA,
    )
    ideas: list[RecipeIdea] = []
    for r in data.get("recipes") or []:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        ideas.append(
            RecipeIdea(
                name=name,
                uses=[str(x) for x in (r.get("uses") or [])],
                missing=[str(x) for x in (r.get("missing") or [])],
            )
        )
    return ideas
