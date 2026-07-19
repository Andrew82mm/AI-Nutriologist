from __future__ import annotations

import sqlite3

from nutriologist.db import get_connection
from nutriologist.inventory import (
    add_manual,
    balance,
    cook_dish,
    current,
    eat,
    income_from_receipt,
    record,
    remove,
)
from nutriologist.products.models import Product


def _product(
    conn: sqlite3.Connection,
    name: str,
    *,
    is_food: bool = True,
    unit: str = "g",
    category: str = "прочее",
) -> Product:
    cursor = conn.execute(
        "INSERT INTO products (canonical_name, is_food, canonical_unit, category) "
        "VALUES (?, ?, ?, ?)",
        (name, 1 if is_food else 0, unit, category),
    )
    conn.commit()
    return Product(
        id=cursor.lastrowid,
        canonical_name=name,
        is_food=is_food,
        canonical_unit=unit,
        category=category,
    )


# --- ledger primitives -----------------------------------------------------
def test_record_and_balance() -> None:
    conn = get_connection(":memory:")
    milk = _product(conn, "молоко")
    record(conn, product_id=milk.id, change_amount=1000, source_type="manual")
    record(conn, product_id=milk.id, change_amount=-250, source_type="meal")
    assert balance(conn, milk.id) == 750.0


def test_current_hides_nonpositive() -> None:
    conn = get_connection(":memory:")
    a = _product(conn, "яблоко")
    b = _product(conn, "банан")
    record(conn, product_id=a.id, change_amount=500, source_type="manual")
    record(conn, product_id=b.id, change_amount=100, source_type="manual")
    record(conn, product_id=b.id, change_amount=-100, source_type="meal")  # nets to 0
    names = [r["canonical_name"] for r in current(conn)]
    assert names == ["яблоко"]  # банан at 0 is hidden


# --- receipt income --------------------------------------------------------
def _receipt_with_items(conn: sqlite3.Connection) -> int:
    receipt_id = conn.execute(
        "INSERT INTO receipts (raw_text, source_format, store_name) "
        "VALUES ('x', 'test', 'ЛЕНТА')"
    ).lastrowid
    # packaged good: qty counts packages, net_amount is per-package content
    milk = _product(conn, "молоко", unit="ml")
    conn.execute(
        "INSERT INTO product_aliases (store_name, raw_name, product_id, net_amount, net_unit) "
        "VALUES ('ЛЕНТА', 'Молоко 950мл', ?, 950, 'ml')",
        (milk.id,),
    )
    conn.execute(
        "INSERT INTO receipt_items (receipt_id, raw_name, qty, unit, unit_price, total, product_id) "
        "VALUES (?, 'Молоко 950мл', 2, 'шт', 80, 160, ?)",
        (receipt_id, milk.id),
    )
    # weight good: no net_amount, the receipt unit (кг) is the measure
    cuc = _product(conn, "огурец", unit="g")
    conn.execute(
        "INSERT INTO receipt_items (receipt_id, raw_name, qty, unit, unit_price, total, product_id) "
        "VALUES (?, 'Огурцы', 0.5, 'кг', 100, 50, ?)",
        (receipt_id, cuc.id),
    )
    # non-food: must be skipped
    bag = _product(conn, "пакет", is_food=False)
    conn.execute(
        "INSERT INTO receipt_items (receipt_id, raw_name, qty, unit, unit_price, total, product_id) "
        "VALUES (?, 'Пакет-майка', 1, 'шт', 5, 5, ?)",
        (receipt_id, bag.id),
    )
    conn.commit()
    return receipt_id


def test_income_from_receipt_grams_and_skips_nonfood() -> None:
    conn = get_connection(":memory:")
    receipt_id = _receipt_with_items(conn)

    posted = income_from_receipt(conn, receipt_id)
    assert posted == 2  # milk + cucumber; bag skipped

    milk_id = conn.execute(
        "SELECT id FROM products WHERE canonical_name = 'молоко'"
    ).fetchone()["id"]
    cuc_id = conn.execute(
        "SELECT id FROM products WHERE canonical_name = 'огурец'"
    ).fetchone()["id"]
    assert balance(conn, milk_id) == 1900.0  # 2 × 950 ml
    assert balance(conn, cuc_id) == 500.0  # 0.5 kg → 500 g


def test_income_from_receipt_is_idempotent() -> None:
    conn = get_connection(":memory:")
    receipt_id = _receipt_with_items(conn)
    assert income_from_receipt(conn, receipt_id) == 2
    assert income_from_receipt(conn, receipt_id) == 0  # re-run posts nothing
    milk_id = conn.execute(
        "SELECT id FROM products WHERE canonical_name = 'молоко'"
    ).fetchone()["id"]
    assert balance(conn, milk_id) == 1900.0  # not doubled


# --- manual add / remove ---------------------------------------------------
def test_add_and_remove_all_zeroes_balance() -> None:
    conn = get_connection(":memory:")
    tvorog = _product(conn, "творог")
    add_manual(conn, product=tvorog, grams=400)
    add_manual(conn, product=tvorog, grams=200)
    assert balance(conn, tvorog.id) == 600.0
    remove(conn, product=tvorog, amount="all", note="испортился")
    assert balance(conn, tvorog.id) == 0.0


def test_remove_partial() -> None:
    conn = get_connection(":memory:")
    ric = _product(conn, "рис")
    add_manual(conn, product=ric, grams=1000)
    remove(conn, product=ric, amount=300)
    assert balance(conn, ric.id) == 700.0


# --- eat -------------------------------------------------------------------
def test_eat_logs_meal_and_decrements() -> None:
    conn = get_connection(":memory:")
    apple = _product(conn, "яблоко", category="фрукты")
    add_manual(conn, product=apple, grams=500)

    meal_id = eat(conn, items=[(apple, 150)], raw_text="съел яблоко")
    assert balance(conn, apple.id) == 350.0

    meal = conn.execute("SELECT raw_text FROM meals WHERE id = ?", (meal_id,)).fetchone()
    assert meal["raw_text"] == "съел яблоко"
    item = conn.execute(
        "SELECT product_id, grams, grams_source FROM meal_items WHERE meal_id = ?",
        (meal_id,),
    ).fetchone()
    assert item["product_id"] == apple.id and item["grams"] == 150.0


# --- cooking ---------------------------------------------------------------
def test_cook_dish_consumes_ingredients_and_stocks_dish() -> None:
    conn = get_connection(":memory:")
    potato = _product(conn, "картофель", category="овощи")
    beef = _product(conn, "говядина", category="мясо")
    add_manual(conn, product=potato, grams=800)
    add_manual(conn, product=beef, grams=500)

    dish = cook_dish(
        conn,
        name="жаркое",
        ingredients=[(potato, 300), (beef, 400)],
        yield_grams=600,
    )

    # ingredients consumed, dish stocked at yield
    assert balance(conn, potato.id) == 500.0
    assert balance(conn, beef.id) == 100.0
    assert balance(conn, dish.id) == 600.0
    assert dish.category == "блюда"

    # dish nutrition computed from ingredients, scaled by yield, marked 'user'
    nut = conn.execute(
        "SELECT kcal, source, source_ref FROM nutrition WHERE product_id = ?",
        (dish.id,),
    ).fetchone()
    assert nut["source"] == "user"
    assert nut["source_ref"].startswith("recipe:")
    assert nut["kcal"] > 0

    # recipe linked to its dish product
    recipe = conn.execute(
        "SELECT product_id, yield_grams FROM recipes WHERE name = 'жаркое'"
    ).fetchone()
    assert recipe["product_id"] == dish.id and recipe["yield_grams"] == 600.0

    # leftovers can be eaten down
    eat(conn, items=[(dish, 250)], raw_text="съел жаркое")
    assert balance(conn, dish.id) == 350.0


def test_cook_dish_yield_defaults_to_ingredient_sum() -> None:
    conn = get_connection(":memory:")
    a = _product(conn, "мука", category="крупы/макароны")
    b = _product(conn, "вода", category="напитки")
    add_manual(conn, product=a, grams=1000)
    add_manual(conn, product=b, grams=1000)

    dish = cook_dish(conn, name="тесто", ingredients=[(a, 200), (b, 100)])
    assert balance(conn, dish.id) == 300.0  # no yield given → sum of ingredients
