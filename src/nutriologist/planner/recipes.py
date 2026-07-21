"""Suggest dishes cookable from what's currently in the fridge (PLAN.md итерация 7).

A lighter companion to the day planner: no БЖУ math, just the LLM proposing a
few dishes given the on-hand product list, flagging what's missing for each.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..inventory import ledger
from ..llm.client import StructuredLLMClient


@dataclass
class RecipeIdea:
    name: str
    uses: list[str] = field(default_factory=list)     # on-hand products it uses
    missing: list[str] = field(default_factory=list)  # products you'd need to buy


_SCHEMA = {
    "type": "object",
    "properties": {
        "recipes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "uses": {"type": "array", "items": {"type": "string"}},
                    "missing": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "uses", "missing"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["recipes"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
Тебе дан список продуктов, которые есть дома. Предложи 2–4 блюда, которые можно \
из них приготовить. Для каждого блюда: name — название, uses — какие из \
имеющихся продуктов используются, missing — чего не хватает (пустой список, \
если хватает всего). Отдавай приоритет блюдам, для которых почти всё есть.
"""


def suggest_recipes(conn: sqlite3.Connection, llm: StructuredLLMClient) -> list[RecipeIdea]:
    """Return a few dish ideas based on current inventory."""
    on_hand = [row["canonical_name"] for row in ledger.current(conn)]
    if not on_hand:
        return []

    data = llm.generate_json(
        system=_SYSTEM_PROMPT,
        user="Есть дома: " + ", ".join(on_hand) + ".",
        json_schema=_SCHEMA,
    )
    ideas: list[RecipeIdea] = []
    for r in data.get("recipes") or []:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        ideas.append(
            RecipeIdea(
                name=name,
                uses=[str(x) for x in (r.get("uses") or [])],
                missing=[str(x) for x in (r.get("missing") or [])],
            )
        )
    return ideas
