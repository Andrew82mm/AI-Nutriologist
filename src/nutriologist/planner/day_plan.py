"""Generate a day's meal plan from goals + current inventory (PLAN.md итерация 7).

Division of labour: the LLM proposes a menu (meals with gram amounts), but the
БЖУ numbers are always *our* deterministic recompute through the nutrition
resolver — never the model's arithmetic. If the recomputed totals stray far from
the daily goal, we ask the LLM once to adjust the gram amounts and recompute
again. The shopping list is then plan-need minus what's already in the fridge.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..inventory import ledger
from ..llm.client import StructuredLLMClient
from ..products.models import CATEGORIES, Product
from ..products.nutrition import resolve_nutrition
from ..products.product_match import normalize_key, resolve_product

_UNIT_LABEL = {"g": "г", "ml": "мл", "piece": "шт"}

# Recompute deviates from goal by more than this (on kcal) → one correction pass.
_TOLERANCE = 0.15

_DEFAULT_GOAL = (2200.0, 150.0, 70.0, 250.0)  # kcal, protein, fat, carbs


@dataclass
class PlanItem:
    name: str
    grams: float
    kcal: float
    protein: float
    fat: float
    carbs: float
    known: bool  # False → no nutrition resolved (counted as 0)


@dataclass
class PlanMeal:
    title: str                              # meal slot: Завтрак / Обед / Ужин / Перекус
    dish: str = ""                          # dish (recipe) name
    steps: list[str] = field(default_factory=list)   # cooking instructions
    saved: bool = False                     # dish already exists in the recipe base
    items: list[PlanItem] = field(default_factory=list)  # ingredients w/ recomputed БЖУ


@dataclass
class ShoppingItem:
    name: str
    amount: float        # to-buy amount in `unit` (0 when already on hand)
    unit: str            # display unit: «г» | «мл» | «шт»
    category: str | None # product category, for grouping the list
    have: bool           # True → already in the fridge (shown struck through)


@dataclass
class DayPlan:
    goal: dict[str, float]
    totals: dict[str, float]
    meals: list[PlanMeal]
    shopping_list: list[ShoppingItem]
    adjusted: bool  # whether a correction pass was needed


_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},  # приём: Завтрак/Обед/Ужин/Перекус
                    "dish": {"type": "string"},    # название блюда (рецепта)
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "grams": {"type": "number"},
                            },
                            "required": ["name", "grams"],
                            "additionalProperties": False,
                        },
                    },
                    "steps": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "dish", "ingredients", "steps"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["meals"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
Ты составляешь план питания на один день из РЕЦЕПТОВ. Тебе даны дневная цель по \
КБЖУ, список продуктов дома и (возможно) сохранённые рецепты пользователя.

Составь 3–4 приёма пищи (завтрак, обед, ужин, при желании перекус). Каждый приём \
— это одно блюдо-рецепт. Для каждого укажи:
- title — приём пищи («Завтрак», «Обед», «Ужин», «Перекус»);
- dish — название блюда в единственном числе («Овсянка с бананом», «Куриное \
филе с гречкой»);
- ingredients — список ингредиентов, каждый: name (обобщённый продукт в ед. \
числе) и grams (граммы сырого продукта);
- steps — 2–5 коротких шагов приготовления.

По возможности используй продукты из холодильника и ориентируйся на цель по \
калориям и белку. Если среди сохранённых рецептов есть подходящий под приём и \
цель — используй его: верни то же название (dish), те же ингредиенты и шаги.
"""


def _load_goal(conn: sqlite3.Connection) -> tuple[float, float, float, float]:
    row = conn.execute(
        "SELECT daily_kcal_goal, daily_protein_goal, daily_fat_goal, daily_carbs_goal "
        "FROM user_profile ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return _DEFAULT_GOAL
    dk, dp, df, dc = _DEFAULT_GOAL
    return (
        row["daily_kcal_goal"] or dk,
        row["daily_protein_goal"] or dp,
        row["daily_fat_goal"] or df,
        row["daily_carbs_goal"] or dc,
    )


def _inventory_names(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """On-hand products keyed by canonical name (for menu context + shopping)."""
    return {row["canonical_name"]: row for row in ledger.current(conn)}


def _recompute(
    conn: sqlite3.Connection, raw_meals: list[dict], llm: StructuredLLMClient
) -> tuple[list[PlanMeal], dict[str, float]]:
    """Turn LLM meals into PlanMeals with our own resolved БЖУ, plus the totals."""
    meals: list[PlanMeal] = []
    totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    for m in raw_meals:
        items: list[PlanItem] = []
        for it in m.get("ingredients") or []:
            name = (it.get("name") or "").strip()
            grams = float(it.get("grams") or 0)
            if not name or grams <= 0:
                continue
            facts = resolve_nutrition(
                conn, Product(canonical_name=name, is_food=True, canonical_unit="g"), llm=llm
            )
            k = grams / 100
            if facts is not None:
                kcal, protein, fat, carbs = (
                    (facts.kcal or 0) * k, (facts.protein or 0) * k,
                    (facts.fat or 0) * k, (facts.carbs or 0) * k,
                )
                known = True
            else:
                kcal = protein = fat = carbs = 0.0
                known = False
            totals["kcal"] += kcal
            totals["protein"] += protein
            totals["fat"] += fat
            totals["carbs"] += carbs
            items.append(
                PlanItem(
                    name=name, grams=grams,
                    kcal=round(kcal, 1), protein=round(protein, 1),
                    fat=round(fat, 1), carbs=round(carbs, 1), known=known,
                )
            )
        steps = [str(s).strip() for s in (m.get("steps") or []) if str(s).strip()]
        meals.append(
            PlanMeal(
                title=(m.get("title") or "Приём пищи").strip(),
                dish=(m.get("dish") or "").strip(),
                steps=steps,
                items=items,
            )
        )
    totals = {kk: round(vv) for kk, vv in totals.items()}
    return meals, totals


def _shopping_list(conn: sqlite3.Connection, meals: list[PlanMeal]) -> list[ShoppingItem]:
    """All plan ingredients, each tagged with what's on hand vs. to buy.

    Returns every distinct ingredient (not just deficits) so the UI can group
    them by category and strike through the ones already in the fridge. The
    to-buy `amount` is plan-need minus on-hand stock, in the product's own unit
    (pieces for штучные products when a piece weight is known, else g/ml).
    """
    needed: dict[str, float] = {}
    order: list[str] = []
    for m in meals:
        for it in m.items:
            if it.name not in needed:
                order.append(it.name)
            needed[it.name] = needed.get(it.name, 0.0) + it.grams

    out: list[ShoppingItem] = []
    for name in order:
        grams = needed[name]
        prod = resolve_product(conn, name)
        category = prod["category"] if prod else None
        unit = (prod["canonical_unit"] if prod else None) or "g"
        piece_w = prod["piece_weight_grams"] if prod else None
        on_hand = ledger.balance(conn, prod["id"]) if prod else 0.0

        if unit == "piece" and piece_w:
            deficit = grams / piece_w - on_hand          # both in pieces
            have, dunit = deficit <= 0.5, "piece"
            amount = 0 if have else max(1, round(deficit))
        elif unit == "piece":
            # Штучный продукт без известного веса: судим «есть дома» по наличию
            # на складе, а к покупке показываем нужные граммы (в штуки не перевести).
            have, dunit = on_hand > 0.5, "g"
            amount = 0 if have else round(grams)
        elif unit in ("g", "ml"):
            deficit = grams - on_hand
            have, dunit = deficit <= 0.5, unit
            amount = 0 if have else round(deficit)
        else:  # продукт не распознан — остатка нет
            have, dunit, amount = False, "g", round(grams)
        out.append(
            ShoppingItem(
                name=name, amount=amount, unit=_UNIT_LABEL[dunit],
                category=category, have=have,
            )
        )

    cat_index = {c: i for i, c in enumerate(CATEGORIES)}
    out.sort(key=lambda s: (cat_index.get(s.category, len(CATEGORIES)), s.name))
    return out


def _saved_recipes(conn: sqlite3.Connection) -> list[dict]:
    """Recipes already in the base (name + ingredient names), newest first."""
    rows = conn.execute(
        "SELECT id, name FROM recipes ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        ings = conn.execute(
            "SELECT p.canonical_name AS name FROM recipe_ingredients ri "
            "JOIN products p ON p.id = ri.product_id WHERE ri.recipe_id = ?",
            (r["id"],),
        ).fetchall()
        out.append({"name": r["name"], "ingredients": [i["name"] for i in ings]})
    return out


def generate_day_plan(conn: sqlite3.Connection, llm: StructuredLLMClient) -> DayPlan:
    """Build a one-day plan of recipes: menu, our-recomputed БЖУ, shopping list."""
    goal_t = _load_goal(conn)
    goal = {"kcal": goal_t[0], "protein": goal_t[1], "fat": goal_t[2], "carbs": goal_t[3]}
    inventory = _inventory_names(conn)

    fridge = ", ".join(inventory.keys()) or "(пусто)"
    saved = _saved_recipes(conn)
    saved_block = ""
    if saved:
        lines = "\n".join(
            f"- {r['name']} (из: {', '.join(r['ingredients']) or '—'})" for r in saved
        )
        saved_block = f"\nСохранённые рецепты (переиспользуй подходящие):\n{lines}"
    user = (
        f"Цель на день: {goal['kcal']:g} ккал, белки {goal['protein']:g} г, "
        f"жиры {goal['fat']:g} г, углеводы {goal['carbs']:g} г.\n"
        f"Есть дома: {fridge}.{saved_block}"
    )
    data = llm.generate_json(system=_SYSTEM_PROMPT, user=user, json_schema=_PLAN_SCHEMA)
    meals, totals = _recompute(conn, data.get("meals") or [], llm)

    # One correction pass if recomputed calories drift too far from the goal.
    adjusted = False
    if goal["kcal"] > 0 and abs(totals["kcal"] - goal["kcal"]) / goal["kcal"] > _TOLERANCE:
        adjusted = True
        correction = (
            f"{user}\n\nТвой предыдущий план дал {totals['kcal']:g} ккал "
            f"(белки {totals['protein']:g} г). Это далеко от цели по калориям — "
            f"скорректируй граммовки/позиции, чтобы приблизиться к цели."
        )
        data2 = llm.generate_json(
            system=_SYSTEM_PROMPT, user=correction, json_schema=_PLAN_SCHEMA
        )
        meals, totals = _recompute(conn, data2.get("meals") or [], llm)

    # Flag dishes that reuse a recipe already in the base (badge in the UI).
    saved_keys = {normalize_key(r["name"]) for r in saved}
    for m in meals:
        m.saved = bool(m.dish) and normalize_key(m.dish) in saved_keys

    shopping = _shopping_list(conn, meals)
    return DayPlan(
        goal={k: round(v) for k, v in goal.items()},
        totals=totals,
        meals=meals,
        shopping_list=shopping,
        adjusted=adjusted,
    )
