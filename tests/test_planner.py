"""Phase C: day planner (deterministic recompute + shopping list) and recipes."""

from __future__ import annotations

import json
from typing import Any

from nutriologist.db import get_connection
from nutriologist.inventory import cook_dish, ledger
from nutriologist.planner import generate_day_plan, suggest_recipes
from nutriologist.products.models import Product


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
        self.plan_prompts: list[str] = []  # user prompts seen on the plan schema

    def generate_json(self, *, system: str, user: str, json_schema: dict[str, Any]):
        props = json_schema.get("properties", {})
        if "meals" in props:
            self.plan_calls += 1
            self.plan_prompts.append(user)
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


def _log_meal(conn, product_name, grams, title=None):
    """Record a meal eaten «now» (product created if missing) — for history tests."""
    row = conn.execute(
        "SELECT id FROM products WHERE canonical_name = ?", (product_name,)
    ).fetchone()
    pid = row["id"] if row else conn.execute(
        "INSERT INTO products (canonical_name, is_food, canonical_unit) VALUES (?, 1, 'g')",
        (product_name,),
    ).lastrowid
    mid = conn.execute(
        "INSERT INTO meals (ts, raw_text, title) VALUES (datetime('now', 'localtime'), ?, ?)",
        (product_name, title),
    ).lastrowid
    conn.execute(
        "INSERT INTO meal_items (meal_id, product_id, grams, grams_source) "
        "VALUES (?, ?, ?, 'user')",
        (mid, pid, grams),
    )
    conn.commit()
    return mid


# Made-up product names, so the nutrition cascade misses the real РФ dataset
# (Скурихин/curated) and falls through to the LLM tier — letting these tests
# assert against controlled per-100 macros rather than dataset values.
def test_day_plan_recomputes_macros_and_shopping_list() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn, 350)  # goal matches the menu, so no correction pass fires
    _add_stock(conn, "зорпаль", 500)  # on hand

    menu = {
        "meals": [
            {"title": "Обед", "dish": "Зорпаль с квамбилатом", "steps": ["смешать", "подать"],
             "ingredients": [
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
    # Meals are now recipes: dish name + steps carried through.
    assert plan.meals[0].dish == "Зорпаль с квамбилатом"
    assert plan.meals[0].steps == ["смешать", "подать"]
    assert plan.meals[0].saved is False  # nothing saved in the base yet
    # Shopping list now carries every ingredient, tagged by what's on hand:
    # зорпаль fully covered (have), квамбилат must be bought (100 g).
    by_name = {s.name: s for s in plan.shopping_list}
    assert by_name["зорпаль"].have is True
    assert by_name["квамбилат"].have is False
    assert by_name["квамбилат"].amount == 100
    assert by_name["квамбилат"].unit == "г"


def test_day_plan_runs_one_correction_pass_when_far_from_goal() -> None:
    conn = get_connection(":memory:")
    # First menu is tiny (way under the 2200 goal) → triggers a correction pass
    # that returns a bigger menu.
    small = {"meals": [{"title": "Завтрак", "dish": "Флюмо", "steps": [],
                        "ingredients": [{"name": "флюмо", "grams": 100}]}]}
    big = {"meals": [{"title": "Обед", "dish": "Зибуль", "steps": [],
                      "ingredients": [{"name": "зибуль", "grams": 1000}]}]}
    llm = PlanFakeLLM(
        plan_responses=[small, big],
        nutrition_by_name={"флюмо": (50, 0, 0, 13), "зибуль": (350, 12, 2, 70)},
    )

    plan = generate_day_plan(conn, llm)

    assert plan.adjusted is True
    assert llm.plan_calls == 2
    assert plan.totals["kcal"] == 3500  # from the corrected (big) menu


def test_day_plan_passes_restrictions_to_llm() -> None:
    conn = get_connection(":memory:")
    conn.execute(
        "INSERT INTO user_profile (daily_kcal_goal, restrictions) VALUES (?, ?)",
        (2000, json.dumps(["Без рыбы", "Без арахиса"], ensure_ascii=False)),
    )
    conn.commit()
    menu = {"meals": [{"title": "Обед", "dish": "Каша", "steps": [],
                       "ingredients": [{"name": "гречка", "grams": 100}]}]}
    # Two identical responses so a correction pass (goal 2000 vs tiny menu) still resolves.
    llm = PlanFakeLLM(plan_responses=[menu, menu], nutrition_by_name={"гречка": (330, 12, 3, 68)})

    generate_day_plan(conn, llm)

    assert llm.plan_prompts, "planner must call the LLM at least once"
    # Restrictions reach the prompt — including the correction pass.
    assert all("Без рыбы" in p and "Без арахиса" in p for p in llm.plan_prompts)


def test_day_plan_passes_recent_meals_to_llm() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn, 330)
    _log_meal(conn, "борщ", 400, title="Борщ")   # custom dish title → used as-is
    _log_meal(conn, "гречка", 150)               # slot title (None) → main ingredient

    menu = {"meals": [{"title": "Обед", "dish": "Салат", "steps": [],
                       "ingredients": [{"name": "огурец", "grams": 100}]}]}
    llm = PlanFakeLLM(plan_responses=[menu, menu], nutrition_by_name={"огурец": (15, 0.8, 0.1, 3)})

    generate_day_plan(conn, llm)

    prompt = llm.plan_prompts[0]
    assert "Уже ели" in prompt
    assert "Борщ" in prompt      # custom title of a recent meal
    assert "гречка" in prompt    # main ingredient stands in for a slot-titled meal


def test_cook_stores_steps_and_plan_reuses_saved_recipe() -> None:
    conn = get_connection(":memory:")
    pid = _add_stock(conn, "яйцо куриное", 500)
    egg = Product(id=pid, canonical_name="яйцо куриное", is_food=True, canonical_unit="g")

    # Cooking a dish records it in the recipe base together with its steps.
    cook_dish(conn, name="Омлет", ingredients=[(egg, 100)], steps=["взбить", "пожарить"])
    row = conn.execute("SELECT steps FROM recipes WHERE name = 'Омлет'").fetchone()
    assert json.loads(row["steps"]) == ["взбить", "пожарить"]

    # A later plan that names that dish is flagged as reusing the saved recipe.
    _set_goal(conn, 200)
    menu = {"meals": [{"title": "Завтрак", "dish": "Омлет", "steps": ["взбить"],
                       "ingredients": [{"name": "яйцо куриное", "grams": 100}]}]}
    # Two identical responses so a correction pass (if it fires) still yields it.
    llm = PlanFakeLLM(plan_responses=[menu, menu], nutrition_by_name={"яйцо куриное": (150, 12, 10, 1)})
    plan = generate_day_plan(conn, llm)
    assert plan.meals[0].saved is True


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
