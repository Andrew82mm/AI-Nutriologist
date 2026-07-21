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

from ..planner import generate_day_plan, suggest_recipes
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
    items: list[PlanItemOut]


class ShoppingItemOut(BaseModel):
    name: str
    grams: float


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
