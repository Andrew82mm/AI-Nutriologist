"""Map a raw receipt line to a canonical product, with an alias cache.

Flow for one line:
  1. cache hit on (store_name, raw_name) in `product_aliases` -> no LLM;
  2. else classify with the LLM (canonical_name, category, is_food,
     canonical_unit) and extract packaging (regex first, LLM as fallback);
  3. get-or-create the product (deduped by canonical_name) and, if the store
     is known, cache the alias so the next identical purchase is free.

Lines with an unknown store (store_name is None — rare LLM-fallback receipts)
are never cached: a NULL store key can't distinguish two different unknown
stores, so they're re-normalized each time instead of poisoning the cache.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..llm.client import StructuredLLMClient
from .models import CANONICAL_UNITS, CATEGORIES, NormalizedItem, Product
from .packaging import _UNIT_MAP, extract_packaging

SYSTEM_PROMPT = """\
Ты нормализуешь позицию российского кассового чека в канонический продукт.

По названию позиции верни:
- canonical_name — обобщённое название продукта в единственном числе, без \
бренда, магазина, фасовки и процентов жирности (например «Молоко \
Простоквашино 2,5% 950мл» → «молоко», «Яйцо куриное ЛЕНТА СО, 10шт» → \
«яйцо куриное»).
- category — одна из заданного списка категорий. Если не подходит ничего — \
«прочее».
- is_food — true для съедобного, false для бытовой химии, посуды, пакетов и \
услуг/сборов («Сборка заказа», «Сервисный сбор»).
- canonical_unit — базовая единица учёта продукта: «g» для твёрдых/весовых, \
«ml» для жидкостей, «piece» для штучных (яйца и т.п.).
- net_amount / net_unit — содержимое одной упаковки, если его видно в \
названии (например «5х80г» → 400 и «g»). Единицы: «g», «ml», «piece». Если \
определить нельзя — null.
"""

NORMALIZE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "canonical_name": {"type": "string"},
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "is_food": {"type": "boolean"},
        "canonical_unit": {"type": ["string", "null"], "enum": ["g", "ml", "piece", None]},
        "net_amount": {"type": ["number", "null"]},
        "net_unit": {"type": ["string", "null"], "enum": ["g", "ml", "piece", None]},
    },
    "required": ["canonical_name", "category", "is_food", "canonical_unit", "net_amount", "net_unit"],
    "additionalProperties": False,
}


def _coerce_category(value: Any) -> str:
    return value if value in CATEGORIES else "прочее"


def _coerce_unit(value: Any) -> str | None:
    if value in CANONICAL_UNITS:
        return value
    # Tolerate a Russian token slipping through (е.g. "г") and map it.
    mapped = _UNIT_MAP.get(str(value).lower())
    return mapped[0] if mapped else None


def _load_product(conn: sqlite3.Connection, product_id: int) -> Product:
    row = conn.execute(
        "SELECT id, canonical_name, category, is_food, canonical_unit, piece_weight_grams "
        "FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    return Product(
        id=row["id"],
        canonical_name=row["canonical_name"],
        category=row["category"],
        is_food=bool(row["is_food"]),
        canonical_unit=row["canonical_unit"],
        piece_weight_grams=row["piece_weight_grams"],
    )


def _get_or_create_product(
    conn: sqlite3.Connection,
    *,
    canonical_name: str,
    category: str | None,
    is_food: bool,
    canonical_unit: str | None,
) -> Product:
    existing = conn.execute(
        "SELECT id FROM products WHERE canonical_name = ?", (canonical_name,)
    ).fetchone()
    if existing is not None:
        # An existing product wins: don't overwrite its classification from a
        # later (possibly noisier) purchase of the same canonical name.
        return _load_product(conn, existing["id"])

    cursor = conn.execute(
        "INSERT INTO products (canonical_name, category, is_food, canonical_unit) "
        "VALUES (?, ?, ?, ?)",
        (canonical_name, category, 1 if is_food else 0, canonical_unit),
    )
    return Product(
        id=cursor.lastrowid,
        canonical_name=canonical_name,
        category=category,
        is_food=is_food,
        canonical_unit=canonical_unit,
    )


def _cache_lookup(
    conn: sqlite3.Connection, store_name: str, raw_name: str
) -> NormalizedItem | None:
    row = conn.execute(
        "SELECT product_id, net_amount, net_unit FROM product_aliases "
        "WHERE store_name = ? AND raw_name = ?",
        (store_name, raw_name),
    ).fetchone()
    if row is None:
        return None
    return NormalizedItem(
        product=_load_product(conn, row["product_id"]),
        net_amount=row["net_amount"],
        net_unit=row["net_unit"],
    )


def normalize_product(
    conn: sqlite3.Connection,
    *,
    store_name: str | None,
    raw_name: str,
    llm: StructuredLLMClient,
) -> NormalizedItem:
    """Return the canonical product + packaging for one receipt line.

    Hits the `product_aliases` cache first (keyed by store + raw name); only on
    a miss does it call the LLM. Commits any new product/alias rows it writes.
    """
    if store_name is not None:
        cached = _cache_lookup(conn, store_name, raw_name)
        if cached is not None:
            return cached

    data = llm.generate_json(system=SYSTEM_PROMPT, user=raw_name, json_schema=NORMALIZE_JSON_SCHEMA)

    product = _get_or_create_product(
        conn,
        canonical_name=data["canonical_name"],
        category=_coerce_category(data.get("category")),
        is_food=bool(data["is_food"]),
        canonical_unit=_coerce_unit(data.get("canonical_unit")),
    )

    # Packaging: cheap regex on the raw name first, LLM's guess as fallback.
    packaging = extract_packaging(raw_name)
    if packaging is not None:
        net_amount, net_unit = packaging.net_amount, packaging.net_unit
    else:
        net_amount = data.get("net_amount")
        net_unit = _coerce_unit(data.get("net_unit")) if data.get("net_unit") else None

    if store_name is not None:
        conn.execute(
            "INSERT OR IGNORE INTO product_aliases "
            "(store_name, raw_name, product_id, net_amount, net_unit) "
            "VALUES (?, ?, ?, ?, ?)",
            (store_name, raw_name, product.id, net_amount, net_unit),
        )

    conn.commit()
    return NormalizedItem(product=product, net_amount=net_amount, net_unit=net_unit)
