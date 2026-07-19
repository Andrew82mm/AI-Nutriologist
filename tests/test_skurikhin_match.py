from __future__ import annotations

from nutriologist.db import get_connection
from nutriologist.products import Product, resolve_nutrition
from nutriologist.products.skurikhin import (
    SkurikhinSource,
    load_dataset,
    normalize_name,
    retrieve,
)


def test_normalize_name_extracts_fat_and_tokens() -> None:
    tokens, fat = normalize_name("Молоко пастеризованное, 2,5% жирности")
    assert fat == 2.5
    assert tokens[0] == "молоко"  # head noun first
    assert "жирности" not in tokens  # stopword dropped
    assert all(t.isalpha() for t in tokens)  # no digits/punctuation leak through


def test_fat_percent_disambiguates_variant() -> None:
    # The dataset has сметана at 10/15/20/25/30% — the query fat must pick 15.
    row, _ = retrieve("сметана 15%", "молочное")
    assert row.fat_percent == 15.0
    assert "сметана" in row.name.lower()


def test_head_noun_match_without_extra_qualifier() -> None:
    # "яйцо куриное": dataset only has "Яйцо целое" — head noun still matches.
    row, _ = retrieve("яйцо куриное", "прочее")
    assert row.name.lower().startswith("яйцо")


def test_unknown_product_returns_none() -> None:
    assert retrieve("сервисный сбор", "непищевое") is None
    assert retrieve("стиральный порошок", "непищевое") is None


def test_source_returns_db_facts_with_code_ref() -> None:
    product = Product(canonical_name="треска", is_food=True, category="рыба")
    facts = SkurikhinSource().lookup(product)
    assert facts is not None
    assert facts.source == "db"
    assert facts.source_ref.startswith("skurikhin:")
    assert facts.protein and facts.protein > 0


def test_dataset_loads_once_and_is_nonempty() -> None:
    ds = load_dataset()
    assert len(ds) > 900
    assert load_dataset() is ds  # cached


def test_resolve_nutrition_uses_skurikhin_for_known_product() -> None:
    conn = get_connection(":memory:")
    cursor = conn.execute(
        "INSERT INTO products (canonical_name, is_food, canonical_unit, category) "
        "VALUES ('сметана 15%', 1, 'g', 'молочное')"
    )
    conn.commit()
    product = Product(
        id=cursor.lastrowid,
        canonical_name="сметана 15%",
        is_food=True,
        category="молочное",
    )

    facts = resolve_nutrition(conn, product)  # no LLM needed — dataset resolves it
    assert facts is not None
    assert facts.source == "db"
    assert facts.source_ref.startswith("skurikhin:")

    cached = conn.execute(
        "SELECT source, source_ref FROM nutrition WHERE product_id = ?",
        (product.id,),
    ).fetchone()
    assert cached["source"] == "db"
