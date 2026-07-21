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
from ..products.models import Product
from ..products.nutrition import resolve_nutrition

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
    title: str
    items: list[PlanItem] = field(default_factory=list)


@dataclass
class ShoppingItem:
    name: str
    grams: float


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
                    "title": {"type": "string"},
                    "items": {
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
                },
                "required": ["title", "items"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["meals"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
Ты составляешь план питания на один день. Тебе даны дневная цель по КБЖУ и \
список продуктов, которые уже есть дома. Составь 3–4 приёма пищи (завтрак, \
обед, ужин, при желании перекус). Для каждой позиции укажи name (обобщённый \
продукт или блюдо в единственном числе) и grams (граммы). По возможности \
используй продукты из холодильника. Ориентируйся на цель по калориям и белку.
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
        for it in m.get("items") or []:
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
        meals.append(PlanMeal(title=(m.get("title") or "Приём пищи").strip(), items=items))
    totals = {kk: round(vv) for kk, vv in totals.items()}
    return meals, totals


def _shopping_list(
    conn: sqlite3.Connection, meals: list[PlanMeal], inventory: dict[str, sqlite3.Row]
) -> list[ShoppingItem]:
    """Plan need minus on-hand stock, per product (mass/volume units only)."""
    needed: dict[str, float] = {}
    for m in meals:
        for it in m.items:
            needed[it.name] = needed.get(it.name, 0.0) + it.grams

    out: list[ShoppingItem] = []
    for name, grams in needed.items():
        row = inventory.get(name)
        on_hand = 0.0
        if row is not None and (row["canonical_unit"] in ("g", "ml") or row["canonical_unit"] is None):
            on_hand = float(row["qty_estimate"])
        deficit = grams - on_hand
        if deficit > 0:
            out.append(ShoppingItem(name=name, grams=round(deficit)))
    out.sort(key=lambda s: s.name)
    return out


def generate_day_plan(conn: sqlite3.Connection, llm: StructuredLLMClient) -> DayPlan:
    """Build a one-day plan: menu, our-recomputed БЖУ, and a shopping list."""
    goal_t = _load_goal(conn)
    goal = {"kcal": goal_t[0], "protein": goal_t[1], "fat": goal_t[2], "carbs": goal_t[3]}
    inventory = _inventory_names(conn)

    fridge = ", ".join(inventory.keys()) or "(пусто)"
    user = (
        f"Цель на день: {goal['kcal']:g} ккал, белки {goal['protein']:g} г, "
        f"жиры {goal['fat']:g} г, углеводы {goal['carbs']:g} г.\n"
        f"Есть дома: {fridge}."
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

    shopping = _shopping_list(conn, meals, inventory)
    return DayPlan(
        goal={k: round(v) for k, v in goal.items()},
        totals=totals,
        meals=meals,
        shopping_list=shopping,
        adjusted=adjusted,
    )
