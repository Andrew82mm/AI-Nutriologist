"""Diary (Дневник) endpoint: today's meals with computed macros vs. the goal.

БЖУ is never stored on the meal — only grams are (see schema.sql). We recompute
it here by joining `meal_items` to the `nutrition` table (per-100 macros) so the
numbers always reflect the latest nutrition data.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .app import db_conn

router = APIRouter(prefix="/api", tags=["diary"])


class Macros(BaseModel):
    kcal: float = 0
    protein: float = 0
    fat: float = 0
    carbs: float = 0


class DiaryItem(BaseModel):
    name: str
    grams: float
    unit: str | None


class DiaryMeal(BaseModel):
    id: int
    ts: str
    title: str
    items: list[DiaryItem]
    macros: Macros


class DiaryDay(BaseModel):
    date: str
    goal: Macros
    consumed: Macros
    remaining_kcal: float
    meals: list[DiaryMeal]


def _meal_title(ts: str) -> str:
    """Завтрак/Обед/Ужин/Перекус from the meal timestamp's hour."""
    try:
        hour = int(ts[11:13])
    except (ValueError, IndexError):
        return "Приём пищи"
    if hour < 11:
        return "Завтрак"
    if hour < 16:
        return "Обед"
    if hour < 21:
        return "Ужин"
    return "Перекус"


def load_goal(conn: sqlite3.Connection) -> Macros:
    row = conn.execute(
        "SELECT daily_kcal_goal, daily_protein_goal, daily_fat_goal, daily_carbs_goal "
        "FROM user_profile ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return Macros(kcal=2200, protein=150, fat=70, carbs=250)
    return Macros(
        kcal=row["daily_kcal_goal"] or 2200,
        protein=row["daily_protein_goal"] or 150,
        fat=row["daily_fat_goal"] or 70,
        carbs=row["daily_carbs_goal"] or 250,
    )


@router.get("/diary/today", response_model=DiaryDay)
def diary_today(conn: sqlite3.Connection = Depends(db_conn)) -> DiaryDay:
    today = date.today().isoformat()

    meal_rows = conn.execute(
        "SELECT id, ts FROM meals WHERE substr(ts, 1, 10) = ? ORDER BY ts", (today,)
    ).fetchall()

    meals: list[DiaryMeal] = []
    total = Macros()
    for mrow in meal_rows:
        item_rows = conn.execute(
            """
            SELECT p.canonical_name, p.canonical_unit, mi.grams,
                   n.kcal, n.protein, n.fat, n.carbs
            FROM meal_items mi
            JOIN products p ON p.id = mi.product_id
            LEFT JOIN nutrition n ON n.product_id = mi.product_id
            WHERE mi.meal_id = ?
            """,
            (mrow["id"],),
        ).fetchall()

        items: list[DiaryItem] = []
        mm = Macros()
        for it in item_rows:
            g = it["grams"] or 0
            k = g / 100
            mm.kcal += (it["kcal"] or 0) * k
            mm.protein += (it["protein"] or 0) * k
            mm.fat += (it["fat"] or 0) * k
            mm.carbs += (it["carbs"] or 0) * k
            items.append(
                DiaryItem(name=it["canonical_name"], grams=g, unit=it["canonical_unit"])
            )

        mm = Macros(**{k: round(v) for k, v in mm.model_dump().items()})
        total.kcal += mm.kcal
        total.protein += mm.protein
        total.fat += mm.fat
        total.carbs += mm.carbs
        meals.append(
            DiaryMeal(
                id=mrow["id"], ts=mrow["ts"], title=_meal_title(mrow["ts"]),
                items=items, macros=mm,
            )
        )

    goal = load_goal(conn)
    total = Macros(**{k: round(v) for k, v in total.model_dump().items()})
    return DiaryDay(
        date=today,
        goal=goal,
        consumed=total,
        remaining_kcal=max(0, round(goal.kcal - total.kcal)),
        meals=meals,
    )
