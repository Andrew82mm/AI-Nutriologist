"""Profile (Профиль) endpoint: daily goals, restrictions and body metrics.

The `user_profile` table is single-row (personal tool — no user scoping). Goals
and restrictions map to real columns; body metrics (sex/age/height/weight/
activity) and goal-type have no dedicated columns, so they ride in the free-form
`preferences` column as JSON. Reads return a fully-populated object with sane
defaults; writes upsert the single row.
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .app import db_conn
from .diary import Macros

router = APIRouter(prefix="/api", tags=["profile"])


class Body(BaseModel):
    sex: str = "М"
    age: int = 30
    height: int = 175
    weight: int = 75
    activity: str = "средняя"


class Profile(BaseModel):
    goal: Macros = Field(default_factory=lambda: Macros(kcal=2200, protein=150, fat=70, carbs=250))
    goal_type: str = "Поддержание"
    restrictions: list[str] = Field(default_factory=list)
    body: Body = Field(default_factory=Body)


def _load(conn: sqlite3.Connection) -> Profile:
    row = conn.execute(
        "SELECT daily_kcal_goal, daily_protein_goal, daily_fat_goal, daily_carbs_goal, "
        "restrictions, preferences FROM user_profile ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return Profile()

    prefs = {}
    if row["preferences"]:
        try:
            prefs = json.loads(row["preferences"])
        except (json.JSONDecodeError, TypeError):
            prefs = {}

    restrictions: list[str] = []
    if row["restrictions"]:
        try:
            restrictions = json.loads(row["restrictions"])
        except (json.JSONDecodeError, TypeError):
            # Legacy free text — split on commas rather than lose it.
            restrictions = [s.strip() for s in row["restrictions"].split(",") if s.strip()]

    return Profile(
        goal=Macros(
            kcal=row["daily_kcal_goal"] or 2200,
            protein=row["daily_protein_goal"] or 150,
            fat=row["daily_fat_goal"] or 70,
            carbs=row["daily_carbs_goal"] or 250,
        ),
        goal_type=prefs.get("goal_type", "Поддержание"),
        restrictions=restrictions,
        body=Body(**prefs.get("body", {})),
    )


@router.get("/profile", response_model=Profile)
def get_profile(conn: sqlite3.Connection = Depends(db_conn)) -> Profile:
    return _load(conn)


@router.put("/profile", response_model=Profile)
def put_profile(profile: Profile, conn: sqlite3.Connection = Depends(db_conn)) -> Profile:
    prefs = json.dumps(
        {"goal_type": profile.goal_type, "body": profile.body.model_dump()},
        ensure_ascii=False,
    )
    restrictions = json.dumps(profile.restrictions, ensure_ascii=False)

    row = conn.execute("SELECT id FROM user_profile ORDER BY id LIMIT 1").fetchone()
    params = (
        profile.goal.kcal, profile.goal.protein, profile.goal.fat, profile.goal.carbs,
        restrictions, prefs,
    )
    if row is None:
        conn.execute(
            "INSERT INTO user_profile (daily_kcal_goal, daily_protein_goal, "
            "daily_fat_goal, daily_carbs_goal, restrictions, preferences) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            params,
        )
    else:
        conn.execute(
            "UPDATE user_profile SET daily_kcal_goal=?, daily_protein_goal=?, "
            "daily_fat_goal=?, daily_carbs_goal=?, restrictions=?, preferences=? WHERE id=?",
            (*params, row["id"]),
        )
    conn.commit()
    return _load(conn)
