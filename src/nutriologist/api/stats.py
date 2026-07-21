"""Statistics (Статистика) endpoint: aggregates over a trailing window.

Powers the first screen's stats section: a per-day calorie series (trend +
goal-adherence heatmap), goal adherence numbers, the period's macro balance,
and spending by category from receipts. Everything is recomputed from stored
grams × per-100 nutrition (БЖУ is never snapshotted), mirroring the diary.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from .app import db_conn
from .diary import Macros, load_goal

router = APIRouter(prefix="/api", tags=["stats"])

# A day counts as "on goal" when its calories are within ±10% of the goal.
_GOAL_BAND = 0.10


def _macro_pcts(protein: float, fat: float, carbs: float) -> tuple[int, int, int]:
    """Energy shares (%) of protein/fat/carbs; 4/9/4 kcal per gram."""
    energy = protein * 4 + fat * 9 + carbs * 4
    if energy <= 0:
        return (0, 0, 0)
    return (
        round(protein * 4 / energy * 100),
        round(fat * 9 / energy * 100),
        round(carbs * 4 / energy * 100),
    )


def _daily_macros(conn: sqlite3.Connection, start: str) -> dict[str, dict[str, float]]:
    """Per-day summed БЖУ from `start` (YYYY-MM-DD) to today, keyed by date."""
    rows = conn.execute(
        """
        SELECT substr(m.ts, 1, 10) AS d,
               SUM(mi.grams * COALESCE(n.kcal, 0) / 100.0)    AS kcal,
               SUM(mi.grams * COALESCE(n.protein, 0) / 100.0) AS protein,
               SUM(mi.grams * COALESCE(n.fat, 0) / 100.0)     AS fat,
               SUM(mi.grams * COALESCE(n.carbs, 0) / 100.0)   AS carbs
        FROM meals m
        JOIN meal_items mi ON mi.meal_id = m.id
        JOIN products p ON p.id = mi.product_id
        LEFT JOIN nutrition n ON n.product_id = mi.product_id
        WHERE substr(m.ts, 1, 10) >= ?
        GROUP BY d
        """,
        (start,),
    ).fetchall()
    return {
        r["d"]: {
            "kcal": r["kcal"] or 0.0, "protein": r["protein"] or 0.0,
            "fat": r["fat"] or 0.0, "carbs": r["carbs"] or 0.0,
        }
        for r in rows
    }


def _spending(conn: sqlite3.Connection, start: str) -> dict:
    """Total spend and per-category breakdown from receipt lines since `start`."""
    rows = conn.execute(
        """
        SELECT COALESCE(p.category, 'не распознано') AS category,
               SUM(ri.total) AS amount
        FROM receipt_items ri
        JOIN receipts r ON r.id = ri.receipt_id
        LEFT JOIN products p ON p.id = ri.product_id
        WHERE substr(COALESCE(r.purchased_at, r.created_at), 1, 10) >= ?
        GROUP BY category
        ORDER BY amount DESC
        """,
        (start,),
    ).fetchall()
    by_category = [{"category": r["category"], "amount": round(r["amount"] or 0, 2)} for r in rows]
    total = round(sum(c["amount"] for c in by_category), 2)
    return {"total": total, "by_category": by_category}


@router.get("/stats")
def stats(
    days: int = Query(7, ge=1, le=366), conn: sqlite3.Connection = Depends(db_conn)
) -> dict:
    """Trailing-window statistics for the first screen (default: 7 days)."""
    goal = load_goal(conn)
    today = date.today()
    start_date = today - timedelta(days=days - 1)
    start = start_date.isoformat()

    daily = _daily_macros(conn, start)

    # Build a dense day-by-day series (missing days → zero, logged=False).
    series: list[dict] = []
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        m = daily.get(d)
        logged = m is not None
        kcal = round(m["kcal"]) if m else 0
        ratio = (kcal / goal.kcal) if goal.kcal else 0.0
        series.append({
            "date": d,
            "kcal": kcal,
            "protein": round(m["protein"], 1) if m else 0,
            "fat": round(m["fat"], 1) if m else 0,
            "carbs": round(m["carbs"], 1) if m else 0,
            "logged": logged,
            "ratio": round(ratio, 2),
        })

    logged_days = [s for s in series if s["logged"]]
    within = [s for s in logged_days if abs(s["kcal"] - goal.kcal) <= goal.kcal * _GOAL_BAND]
    avg_kcal = round(sum(s["kcal"] for s in logged_days) / len(logged_days)) if logged_days else 0

    # Logging streak: consecutive logged days counting back from today.
    streak = 0
    for s in reversed(series):
        if s["logged"]:
            streak += 1
        else:
            break

    adherence = {
        "days_logged": len(logged_days),
        "days_within": len(within),
        "pct_within": round(len(within) / len(logged_days) * 100) if logged_days else 0,
        "avg_kcal": avg_kcal,
        "streak": streak,
    }

    # Macro balance over the whole window (sum of logged days).
    sp = sum(s["protein"] for s in logged_days)
    sf = sum(s["fat"] for s in logged_days)
    sc = sum(s["carbs"] for s in logged_days)
    pp, fp, cp = _macro_pcts(sp, sf, sc)
    gp, gf, gc = _macro_pcts(goal.protein, goal.fat, goal.carbs)
    macros = {
        "protein": round(sp, 1), "fat": round(sf, 1), "carbs": round(sc, 1),
        "protein_pct": pp, "fat_pct": fp, "carbs_pct": cp,
        "goal_protein_pct": gp, "goal_fat_pct": gf, "goal_carbs_pct": gc,
    }

    return {
        "days": days,
        "goal": goal.model_dump(),
        "series": series,
        "adherence": adherence,
        "macros": macros,
        "spending": _spending(conn, start),
    }
