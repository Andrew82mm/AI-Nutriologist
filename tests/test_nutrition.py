from __future__ import annotations

from nutriologist.db import get_connection
from nutriologist.products import Product, NutritionFacts, resolve_nutrition
from nutriologist.products.nutrition import get_cached_nutrition, save_nutrition

from product_fakes import RoutingFakeLLM


def _insert_product(conn, canonical_name: str) -> Product:
    cursor = conn.execute(
        "INSERT INTO products (canonical_name, is_food, canonical_unit) VALUES (?, 1, 'g')",
        (canonical_name,),
    )
    conn.commit()
    return Product(id=cursor.lastrowid, canonical_name=canonical_name, is_food=True)


def test_static_stub_resolves_and_caches() -> None:
    conn = get_connection(":memory:")
    product = _insert_product(conn, "молоко")

    facts = resolve_nutrition(conn, product)
    assert facts is not None
    assert facts.source == "db"
    assert facts.kcal == 60.0

    # persisted, so a re-resolve is a cache hit
    cached = get_cached_nutrition(conn, product.id)
    assert cached is not None and cached.kcal == 60.0


def test_llm_estimate_used_when_not_in_stub() -> None:
    conn = get_connection(":memory:")
    product = _insert_product(conn, "экзотика")
    llm = RoutingFakeLLM(
        nutrition={"kcal": 111.0, "protein": 1.0, "fat": 2.0, "carbs": 3.0}
    )

    facts = resolve_nutrition(conn, product, llm=llm)
    assert facts is not None
    assert facts.source == "llm_estimate"
    assert facts.kcal == 111.0
    assert len(llm.calls) == 1


def test_cache_short_circuits_before_llm() -> None:
    conn = get_connection(":memory:")
    product = _insert_product(conn, "экзотика")
    llm = RoutingFakeLLM(
        nutrition={"kcal": 111.0, "protein": 1.0, "fat": 2.0, "carbs": 3.0}
    )

    resolve_nutrition(conn, product, llm=llm)
    resolve_nutrition(conn, product, llm=llm)
    assert len(llm.calls) == 1  # second call hits the cache


def test_resolve_returns_none_when_unresolvable_without_llm() -> None:
    conn = get_connection(":memory:")
    product = _insert_product(conn, "неизвестное")
    assert resolve_nutrition(conn, product) is None


def test_llm_estimate_does_not_overwrite_user_data() -> None:
    conn = get_connection(":memory:")
    product = _insert_product(conn, "особый продукт")

    user_facts = NutritionFacts(
        kcal=200.0, protein=10.0, fat=5.0, carbs=20.0, source="user"
    )
    assert save_nutrition(conn, product.id, user_facts) is True

    estimate = NutritionFacts(kcal=1.0, protein=1.0, fat=1.0, carbs=1.0, source="llm_estimate")
    assert save_nutrition(conn, product.id, estimate) is False

    kept = get_cached_nutrition(conn, product.id)
    assert kept.source == "user" and kept.kcal == 200.0


def test_db_source_overwrites_prior_llm_estimate() -> None:
    conn = get_connection(":memory:")
    product = _insert_product(conn, "продукт")

    estimate = NutritionFacts(kcal=1.0, protein=1.0, fat=1.0, carbs=1.0, source="llm_estimate")
    save_nutrition(conn, product.id, estimate)

    db_facts = NutritionFacts(kcal=300.0, protein=9.0, fat=1.0, carbs=60.0, source="db")
    assert save_nutrition(conn, product.id, db_facts) is True

    kept = get_cached_nutrition(conn, product.id)
    assert kept.source == "db" and kept.kcal == 300.0
