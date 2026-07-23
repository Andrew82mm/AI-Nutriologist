from __future__ import annotations

import sqlite3

from nutriologist.db import get_connection
from nutriologist.products.product_match import (
    find_exact_or_normalized,
    normalize_key,
    resolve_product,
)


def _add(conn: sqlite3.Connection, name: str, *, fat: bool = True) -> int:
    return conn.execute(
        "INSERT INTO products (canonical_name, is_food, canonical_unit) VALUES (?, 1, 'g')",
        (name,),
    ).lastrowid


def test_normalize_key_folds_case_yo_and_space():
    assert normalize_key("  Салат  из   Капусты ") == "салат из капусты"
    assert normalize_key("Бёдра") == normalize_key("бедра")


def test_exact_match():
    conn = get_connection(":memory:")
    pid = _add(conn, "Салат из капусты")
    assert resolve_product(conn, "Салат из капусты")["id"] == pid


def test_case_insensitive_match():
    conn = get_connection(":memory:")
    pid = _add(conn, "Салат из капусты")
    # The originally reported bug: lower-cased name didn't find the dish.
    assert resolve_product(conn, "салат из капусты")["id"] == pid
    assert find_exact_or_normalized(conn, "салат из капусты")["id"] == pid


def test_yo_vs_e_match():
    conn = get_connection(":memory:")
    pid = _add(conn, "куриные бёдра")
    assert resolve_product(conn, "куриные бедра")["id"] == pid


def test_word_order_synonym_match():
    conn = get_connection(":memory:")
    pid = _add(conn, "Салат из капусты")
    # Different word order + adjective form — fuzzy layer.
    assert resolve_product(conn, "капустный салат")["id"] == pid


def test_distinct_dishes_do_not_match():
    conn = get_connection(":memory:")
    _add(conn, "куриный суп")
    # A different dish must not be pulled in by a single shared word.
    assert resolve_product(conn, "гороховый суп") is None


def test_fat_percent_gates_fuzzy():
    conn = get_connection(":memory:")
    _add(conn, "молоко 2,5%")
    # Same base word but different fat % → not the same product.
    assert resolve_product(conn, "молоко 3,2%") is None


def test_unknown_name_returns_none():
    conn = get_connection(":memory:")
    _add(conn, "борщ")
    assert resolve_product(conn, "плов") is None


def test_find_exact_or_normalized_has_no_fuzzy():
    conn = get_connection(":memory:")
    _add(conn, "Салат из капусты")
    # Layers 1–2 only: a synonym must NOT resolve here (guards create dedup).
    assert find_exact_or_normalized(conn, "капустный салат") is None
