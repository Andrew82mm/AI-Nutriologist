from __future__ import annotations

from nutriologist.db import get_connection
from nutriologist.products import normalize_product

from product_fakes import RoutingFakeLLM, normalize_response


def test_normalize_creates_product_and_caches_alias() -> None:
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(
        normalize=normalize_response(
            canonical_name="яйцо куриное", category="прочее", canonical_unit="piece"
        )
    )

    result = normalize_product(
        conn, store_name="ЛЕНТА", raw_name="Яйцо куриное ЛЕНТА СО, 10шт", llm=llm
    )

    assert result.product.canonical_name == "яйцо куриное"
    assert result.product.id is not None
    # packaging comes from the regex on the raw name, not the LLM
    assert result.net_amount == 10.0
    assert result.net_unit == "piece"

    alias = conn.execute(
        "SELECT store_name, product_id, net_amount FROM product_aliases"
    ).fetchone()
    assert alias["store_name"] == "ЛЕНТА"
    assert alias["net_amount"] == 10.0


def test_normalize_cache_hit_skips_llm() -> None:
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(normalize=normalize_response(canonical_name="молоко"))

    normalize_product(conn, store_name="ЛЕНТА", raw_name="Молоко 950мл", llm=llm)
    assert len(llm.calls) == 1

    again = normalize_product(conn, store_name="ЛЕНТА", raw_name="Молоко 950мл", llm=llm)
    assert len(llm.calls) == 1  # no second LLM call
    assert again.product.canonical_name == "молоко"


def test_same_raw_name_different_store_is_separate_alias() -> None:
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(normalize=normalize_response(canonical_name="яблоко"))

    normalize_product(conn, store_name="Пятерочка", raw_name="Яблоки", llm=llm)
    normalize_product(conn, store_name="ВкусВилл", raw_name="Яблоки", llm=llm)

    assert len(llm.calls) == 2  # cache keyed by (store, raw_name)
    aliases = conn.execute("SELECT COUNT(*) AS n FROM product_aliases").fetchone()
    assert aliases["n"] == 2
    # ...but both map to the single deduped product
    products = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()
    assert products["n"] == 1


def test_normalize_without_store_is_not_cached() -> None:
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(normalize=normalize_response(canonical_name="соус"))

    normalize_product(conn, store_name=None, raw_name="Соус Барбекю", llm=llm)
    normalize_product(conn, store_name=None, raw_name="Соус Барбекю", llm=llm)

    assert len(llm.calls) == 2  # NULL store is never cached -> re-normalized
    aliases = conn.execute("SELECT COUNT(*) AS n FROM product_aliases").fetchone()
    assert aliases["n"] == 0


def test_unknown_category_coerced_to_prochee() -> None:
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(
        normalize=normalize_response(canonical_name="нечто", category="выдуманное")
    )

    result = normalize_product(conn, store_name="X", raw_name="Нечто", llm=llm)
    assert result.product.category == "прочее"


def test_packaging_falls_back_to_llm_when_regex_misses() -> None:
    conn = get_connection(":memory:")
    # raw name has no parseable packaging; LLM supplies net content
    llm = RoutingFakeLLM(
        normalize=normalize_response(
            canonical_name="печенье", net_amount=250.0, net_unit="g"
        )
    )

    result = normalize_product(conn, store_name="X", raw_name="Печенье юбилейное", llm=llm)
    assert result.net_amount == 250.0
    assert result.net_unit == "g"
