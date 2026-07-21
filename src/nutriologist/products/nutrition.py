"""Resolve per-100 nutrition for a product through a source cascade.

Design (PLAN.md итерация 2): the resolver is a cascade of `NutritionSource`s
tried in priority order — a small curated static stub, then the Скурихин RF
dataset (`SkurikhinSource`), then an LLM estimate as a last resort. New sources
(e.g. Open Food Facts) plug in as extra `NutritionSource`s without changing the
resolver.

Once resolved, facts are cached in the `nutrition` table so a repeat lookup
costs nothing. `save_nutrition` is rank-aware: an 'llm_estimate' never
overwrites hand-entered ('user') or dataset ('db') data.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol

from ..llm.client import StructuredLLMClient
from .models import NUTRITION_SOURCE_RANK, NutritionFacts, Product
from .skurikhin import SkurikhinSource


class NutritionSource(Protocol):
    """A single lookup strategy. Returns None if it has nothing for `product`."""

    def lookup(self, product: Product) -> NutritionFacts | None: ...


# --- MVP static stub -------------------------------------------------------
# Hand-entered per-100 g macros for a handful of staples, so the pipeline runs
# end-to-end (and tests pass) before real lookup is wired. Keyed by canonical
# product name. Marked source='db' — treated as trusted, not an estimate.
_STATIC_TABLE: dict[str, tuple[float, float, float, float]] = {
    # name: (kcal, protein, fat, carbs)
    "молоко": (60.0, 3.0, 3.2, 4.7),
    "яйцо куриное": (157.0, 12.7, 11.5, 0.7),
    "хлеб": (250.0, 8.0, 3.0, 48.0),
}


class StaticStubSource:
    """Looks a product up in the built-in `_STATIC_TABLE`."""

    def lookup(self, product: Product) -> NutritionFacts | None:
        macros = _STATIC_TABLE.get(product.canonical_name)
        if macros is None:
            return None
        kcal, protein, fat, carbs = macros
        return NutritionFacts(
            kcal=kcal,
            protein=protein,
            fat=fat,
            carbs=carbs,
            source="db",
            source_ref="static_stub",
        )


# --- LLM estimate ----------------------------------------------------------
_ESTIMATE_SYSTEM_PROMPT = """\
Ты оцениваешь пищевую ценность продукта на 100 грамм (для жидкостей — на \
100 мл). Верни kcal, protein, fat, carbs (в граммах) как числа. Это оценка — \
давай реалистичные усреднённые значения для обычного продукта такого рода.
"""

_ESTIMATE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "kcal": {"type": "number"},
        "protein": {"type": "number"},
        "fat": {"type": "number"},
        "carbs": {"type": "number"},
    },
    "required": ["kcal", "protein", "fat", "carbs"],
    "additionalProperties": False,
}


class LLMEstimateSource:
    """Last-resort estimate from the LLM; always marked 'llm_estimate'."""

    def __init__(self, llm: StructuredLLMClient):
        self._llm = llm

    def lookup(self, product: Product) -> NutritionFacts | None:
        data = self._llm.generate_json(
            system=_ESTIMATE_SYSTEM_PROMPT,
            user=product.canonical_name,
            json_schema=_ESTIMATE_JSON_SCHEMA,
        )
        return NutritionFacts(
            kcal=data["kcal"],
            protein=data["protein"],
            fat=data["fat"],
            carbs=data["carbs"],
            source="llm_estimate",
        )


# --- persistence -----------------------------------------------------------
def get_cached_nutrition(conn: sqlite3.Connection, product_id: int) -> NutritionFacts | None:
    row = conn.execute(
        "SELECT kcal, protein, fat, carbs, source, source_ref FROM nutrition "
        "WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    if row is None:
        return None
    return NutritionFacts(
        kcal=row["kcal"],
        protein=row["protein"],
        fat=row["fat"],
        carbs=row["carbs"],
        source=row["source"],
        source_ref=row["source_ref"],
    )


def save_nutrition(conn: sqlite3.Connection, product_id: int, facts: NutritionFacts) -> bool:
    """Upsert nutrition for a product, refusing to downgrade the source.

    Returns True if the row was written, False if an equal-or-higher-ranked
    source already exists (e.g. keeping 'user' over an incoming 'llm_estimate').
    """
    existing = conn.execute(
        "SELECT source FROM nutrition WHERE product_id = ?", (product_id,)
    ).fetchone()
    if existing is not None:
        if NUTRITION_SOURCE_RANK[facts.source] < NUTRITION_SOURCE_RANK[existing["source"]]:
            return False

    conn.execute(
        "INSERT INTO nutrition (product_id, kcal, protein, fat, carbs, source, source_ref, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(product_id) DO UPDATE SET "
        "kcal=excluded.kcal, protein=excluded.protein, fat=excluded.fat, "
        "carbs=excluded.carbs, source=excluded.source, source_ref=excluded.source_ref, "
        "updated_at=excluded.updated_at",
        (
            product_id,
            facts.kcal,
            facts.protein,
            facts.fat,
            facts.carbs,
            facts.source,
            facts.source_ref,
        ),
    )
    conn.commit()
    return True


def resolve_nutrition(
    conn: sqlite3.Connection,
    product: Product,
    *,
    llm: StructuredLLMClient | None = None,
) -> NutritionFacts | None:
    """Return per-100 nutrition for `product`, resolving and caching on a miss.

    A cached row (any source) short-circuits — no recompute. Otherwise the
    source cascade runs (static stub, then LLM estimate if `llm` is given), and
    the first hit is persisted. Returns None only if nothing could resolve it.
    """
    if product.id is not None:
        cached = get_cached_nutrition(conn, product.id)
        if cached is not None:
            return cached

    sources: list[NutritionSource] = [StaticStubSource(), SkurikhinSource()]
    if llm is not None:
        sources.append(LLMEstimateSource(llm))

    for source in sources:
        # A flaky source must not crash the caller: the LLM tier can time out,
        # rate-limit, or return unparseable JSON, and nutrition is best-effort —
        # a failure just means "unknown" (contribute 0), not a 500. This keeps
        # multi-ingredient flows (cook_dish) and meal logging resilient.
        try:
            facts = source.lookup(product)
        except Exception:
            continue
        if facts is not None:
            if product.id is not None:
                save_nutrition(conn, product.id, facts)
            return facts

    return None
