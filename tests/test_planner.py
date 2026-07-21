"""Phase C: day planner (deterministic recompute + shopping list) and recipes."""

from __future__ import annotations

from typing import Any

from nutriologist.db import get_connection
from nutriologist.inventory import ledger
from nutriologist.planner import generate_day_plan, suggest_recipes


class PlanFakeLLM:
    """Routes by schema: the plan schema (has 'meals') vs nutrition ('kcal').

    `plan_responses` is a queue so a correction pass can return a different menu.
    Nutrition is answered per product name from `nutrition_by_name` (default 0s).
    """

    def __init__(self, *, plan_responses=None, recipes=None, nutrition_by_name=None):
        self._plans = list(plan_responses or [])
        self._recipes = recipes
        self._nutrition = nutrition_by_name or {}
        self.plan_calls = 0

    def generate_json(self, *, system: str, user: str, json_schema: dict[str, Any]):
        props = json_schema.get("properties", {})
        if "meals" in props:
            self.plan_calls += 1
            return self._plans.pop(0) if self._plans else {"meals": []}
        if "recipes" in props:
            return self._recipes or {"recipes": []}
        if "kcal" in props:  # nutrition estimate for a product name
            macros = self._nutrition.get(user, (0, 0, 0, 0))
            return {"kcal": macros[0], "protein": macros[1], "fat": macros[2], "carbs": macros[3]}
        raise AssertionError(f"unroutable schema: {sorted(props)}")


def _add_stock(conn, name, grams, unit="g"):
    pid = conn.execute(
        "INSERT INTO products (canonical_name, is_food, canonical_unit) VALUES (?, 1, ?)",
        (name, unit),
    ).lastrowid
    ledger.record(conn, product_id=pid, change_amount=grams, source_type="manual")
    conn.commit()
    return pid


def _set_goal(conn, kcal):
    conn.execute("INSERT INTO user_profile (daily_kcal_goal) VALUES (?)", (kcal,))
    conn.commit()


# Made-up product names, so the nutrition cascade misses the real РФ dataset
# (Скурихин/curated) and falls through to the LLM tier — letting these tests
# assert against controlled per-100 macros rather than dataset values.
def test_day_plan_recomputes_macros_and_shopping_list() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn, 350)  # goal matches the menu, so no correction pass fires
    _add_stock(conn, "зорпаль", 500)  # on hand

    menu = {
        "meals": [
            {"title": "Обед", "items": [
                {"name": "зорпаль", "grams": 200},
                {"name": "квамбилат", "grams": 100},
            ]},
        ]
    }
    llm = PlanFakeLLM(
        plan_responses=[menu],
        nutrition_by_name={
            "зорпаль": (110, 23, 1, 0),
            "квамбилат": (130, 2.7, 0.3, 28),
        },
    )

    plan = generate_day_plan(conn, llm)

    # Deterministic recompute: 200 g зорпаль → 220 kcal, 100 g квамбилат → 130 kcal.
    assert plan.totals["kcal"] == 350
    # Shopping list: квамбилат (100 g, none on hand) needed; зорпаль fully covered.
    names = {s.name for s in plan.shopping_list}
    assert "квамбилат" in names
    assert "зорпаль" not in names


def test_day_plan_runs_one_correction_pass_when_far_from_goal() -> None:
    conn = get_connection(":memory:")
    # First menu is tiny (way under the 2200 goal) → triggers a correction pass
    # that returns a bigger menu.
    small = {"meals": [{"title": "Завтрак", "items": [{"name": "флюмо", "grams": 100}]}]}
    big = {"meals": [{"title": "Обед", "items": [{"name": "зибуль", "grams": 1000}]}]}
    llm = PlanFakeLLM(
        plan_responses=[small, big],
        nutrition_by_name={"флюмо": (50, 0, 0, 13), "зибуль": (350, 12, 2, 70)},
    )

    plan = generate_day_plan(conn, llm)

    assert plan.adjusted is True
    assert llm.plan_calls == 2
    assert plan.totals["kcal"] == 3500  # from the corrected (big) menu


def test_suggest_recipes_from_inventory() -> None:
    conn = get_connection(":memory:")
    _add_stock(conn, "яйцо куриное", 6, unit="piece")
    _add_stock(conn, "мука", 1000)
    llm = PlanFakeLLM(
        recipes={"recipes": [
            {"name": "омлет", "uses": ["яйцо куриное"], "missing": []},
            {"name": "блины", "uses": ["мука", "яйцо куриное"], "missing": ["молоко"]},
        ]}
    )

    ideas = suggest_recipes(conn, llm)

    assert [i.name for i in ideas] == ["омлет", "блины"]
    assert ideas[1].missing == ["молоко"]


def test_suggest_recipes_empty_fridge_no_llm_call() -> None:
    conn = get_connection(":memory:")
    llm = PlanFakeLLM(recipes={"recipes": [{"name": "x", "uses": [], "missing": []}]})

    assert suggest_recipes(conn, llm) == []
