"""Planner (План) endpoints: a day's menu + shopping list, and recipe ideas.

Both require an LLM (they generate); without one configured they return 422 so
the frontend can prompt the user to fill in .env. The heavy lifting lives in the
provider-agnostic `nutriologist.planner` core — these endpoints only marshal
request/response and reuse the shared `get_optional_llm` dependency.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..planner import (
    delete_recipe,
    generate_day_plan,
    list_saved_recipes,
    suggest_recipes,
)
from .app import db_conn, get_optional_llm

router = APIRouter(prefix="/api", tags=["planner"])


class PlanItemOut(BaseModel):
    name: str
    grams: float
    kcal: float
    protein: float
    fat: float
    carbs: float
    known: bool


class PlanMealOut(BaseModel):
    title: str
    dish: str
    steps: list[str]
    saved: bool
    items: list[PlanItemOut]


class ShoppingItemOut(BaseModel):
    name: str
    amount: float
    unit: str
    category: str | None
    have: bool


class DayPlanOut(BaseModel):
    goal: dict[str, float]
    totals: dict[str, float]
    meals: list[PlanMealOut]
    shopping_list: list[ShoppingItemOut]
    adjusted: bool


class RecipeIdeaOut(BaseModel):
    name: str
    uses: list[str]
    missing: list[str]


class RecipesOut(BaseModel):
    recipes: list[RecipeIdeaOut]


class SavedRecipeItemOut(BaseModel):
    name: str
    grams: float


class SavedRecipeOut(BaseModel):
    id: int
    name: str
    yield_grams: float
    steps: list[str]
    ingredients: list[SavedRecipeItemOut]
    kcal: float
    protein: float
    fat: float
    carbs: float
    created_at: str


def _require_llm():
    llm = get_optional_llm()
    if llm is None:
        raise HTTPException(
            status_code=422,
            detail="Для генерации плана нужен настроенный LLM — заполните .env.",
        )
    return llm


@router.post("/plan/day", response_model=DayPlanOut)
def plan_day(conn: sqlite3.Connection = Depends(db_conn)) -> DayPlanOut:
    """Generate today's menu with recomputed БЖУ and a shopping list."""
    plan = generate_day_plan(conn, _require_llm())
    return DayPlanOut(**asdict(plan))


@router.post("/recipes/suggest", response_model=RecipesOut)
def recipes_suggest(conn: sqlite3.Connection = Depends(db_conn)) -> RecipesOut:
    """Suggest a few dishes cookable from current inventory."""
    ideas = suggest_recipes(conn, _require_llm())
    return RecipesOut(recipes=[RecipeIdeaOut(**asdict(i)) for i in ideas])


@router.get("/recipes", response_model=list[SavedRecipeOut])
def recipes_saved(conn: sqlite3.Connection = Depends(db_conn)) -> list[SavedRecipeOut]:
    """«Мои рецепты» — recipes saved to the base (created when dishes are cooked).

    No LLM needed: БЖУ comes from each cooked dish's stored nutrition.
    """
    return [SavedRecipeOut(**asdict(r)) for r in list_saved_recipes(conn)]


@router.delete("/recipes/{recipe_id}", status_code=204)
def recipes_delete(recipe_id: int, conn: sqlite3.Connection = Depends(db_conn)) -> None:
    """Delete a saved recipe. The cooked-dish product/stock is left intact."""
    status = delete_recipe(conn, recipe_id)
    if status == "missing":
        raise HTTPException(status_code=404, detail="Рецепт не найден.")
    if status == "referenced":
        raise HTTPException(
            status_code=409,
            detail="Рецепт используется в записях приёмов пищи — удалить нельзя.",
        )
