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
    grams: float             # macro weight (g); portion basis for БЖУ
    unit: str | None         # product's canonical unit: g | ml | piece
    amount_canonical: float | None = None  # amount in `unit` (pieces for шт) — for the edit form
    known: bool = True       # False → no nutrition on file; the form shows «?»
    # Per-item macros (for pre-filling the edit form).
    kcal: float = 0
    protein: float = 0
    fat: float = 0
    carbs: float = 0


class DiaryMeal(BaseModel):
    id: int
    ts: str
    title: str  # effective title (custom, else derived from time) — for display
    custom_title: str | None = None  # raw user-set title, or None — for the edit form
    items: list[DiaryItem]
    macros: Macros
    # Provenance of the meal's nutrition, for the card tag: 'база' (dataset),
    # 'введено' (hand-entered) or '≈ оценка' (LLM estimate).
    source: str = "введено"


def _source_label(sources: list[str | None]) -> str:
    """Lowest-confidence nutrition source across a meal's items wins the label."""
    present = [s for s in sources if s]
    if not present:
        return "введено"
    if "llm_estimate" in present:
        return "≈ оценка"
    if "user" in present:
        return "введено"
    return "база"


class DiaryDay(BaseModel):
    date: str
    goal: Macros
    consumed: Macros
    remaining_kcal: float
    meals: list[DiaryMeal]


def title_for_hour(hour: int) -> str:
    """Завтрак/Обед/Ужин/Перекус for a given hour of day."""
    if hour < 11:
        return "Завтрак"
    if hour < 16:
        return "Обед"
    if hour < 21:
        return "Ужин"
    return "Перекус"


def _meal_title(ts: str) -> str:
    """Meal title derived from the timestamp's hour (fallback when unnamed)."""
    try:
        return title_for_hour(int(ts[11:13]))
    except (ValueError, IndexError):
        return "Приём пищи"


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
        "SELECT id, ts, title FROM meals WHERE substr(ts, 1, 10) = ? ORDER BY ts", (today,)
    ).fetchall()

    meals: list[DiaryMeal] = []
    total = Macros()
    for mrow in meal_rows:
        item_rows = conn.execute(
            """
            SELECT p.canonical_name, p.canonical_unit, mi.grams, mi.amount_canonical,
                   n.kcal, n.protein, n.fat, n.carbs, n.source
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
            ik, ip, iff, ic = (
                (it["kcal"] or 0) * k, (it["protein"] or 0) * k,
                (it["fat"] or 0) * k, (it["carbs"] or 0) * k,
            )
            mm.kcal += ik
            mm.protein += ip
            mm.fat += iff
            mm.carbs += ic
            items.append(
                DiaryItem(
                    name=it["canonical_name"], grams=g, unit=it["canonical_unit"],
                    amount_canonical=it["amount_canonical"], known=it["source"] is not None,
                    kcal=round(ik), protein=round(ip), fat=round(iff), carbs=round(ic),
                )
            )

        mm = Macros(**{k: round(v) for k, v in mm.model_dump().items()})
        total.kcal += mm.kcal
        total.protein += mm.protein
        total.fat += mm.fat
        total.carbs += mm.carbs
        meals.append(
            DiaryMeal(
                id=mrow["id"], ts=mrow["ts"],
                title=(mrow["title"] or _meal_title(mrow["ts"])),
                custom_title=mrow["title"],
                items=items, macros=mm,
                source=_source_label([it["source"] for it in item_rows]),
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
