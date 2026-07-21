"""Stats endpoint: trailing-window aggregates for the first screen."""

from __future__ import annotations

from datetime import date, timedelta

import nutriologist.api.stats as stats_api
from nutriologist.db import get_connection


def _product(conn, name, per100, category="прочее"):
    pid = conn.execute(
        "INSERT INTO products (canonical_name, is_food, canonical_unit, category) "
        "VALUES (?, 1, 'g', ?)",
        (name, category),
    ).lastrowid
    kcal, protein, fat, carbs = per100
    conn.execute(
        "INSERT INTO nutrition (product_id, kcal, protein, fat, carbs, source) "
        "VALUES (?, ?, ?, ?, ?, 'db')",
        (pid, kcal, protein, fat, carbs),
    )
    return pid


def _log_meal(conn, pid, grams, day: date):
    ts = f"{day.isoformat()} 12:00:00"
    mid = conn.execute("INSERT INTO meals (ts, raw_text) VALUES (?, '')", (ts,)).lastrowid
    conn.execute(
        "INSERT INTO meal_items (meal_id, product_id, grams, grams_source) "
        "VALUES (?, ?, ?, 'user')",
        (mid, pid, grams),
    )
    conn.commit()


def _set_goal(conn, kcal=2000, protein=150, fat=60, carbs=200):
    conn.execute(
        "INSERT INTO user_profile (daily_kcal_goal, daily_protein_goal, daily_fat_goal, "
        "daily_carbs_goal) VALUES (?, ?, ?, ?)",
        (kcal, protein, fat, carbs),
    )
    conn.commit()


def _get(conn, days=7):
    return stats_api.stats(days=days, conn=conn)


def test_series_is_dense_and_marks_logged_days() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn)
    pid = _product(conn, "каша", (100, 3, 2, 20))
    today = date.today()
    _log_meal(conn, pid, 200, today)               # 200 g → 200 kcal today
    _log_meal(conn, pid, 100, today - timedelta(days=3))

    out = _get(conn, days=7)

    assert out["days"] == 7
    assert len(out["series"]) == 7                 # one entry per calendar day
    assert out["series"][-1]["date"] == today.isoformat()
    assert out["series"][-1]["kcal"] == 200
    assert out["series"][-1]["logged"] is True
    assert out["series"][0]["logged"] is False     # 6 days ago: nothing logged
    assert out["adherence"]["days_logged"] == 2


def test_adherence_within_band_and_streak() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn, kcal=2000)
    pid = _product(conn, "рагу", (100, 5, 3, 10))
    today = date.today()
    _log_meal(conn, pid, 2000, today)          # 2000 kcal → exactly on goal
    _log_meal(conn, pid, 1000, today - timedelta(days=1))  # 1000 kcal → off goal

    out = _get(conn, days=7)

    assert out["adherence"]["days_logged"] == 2
    assert out["adherence"]["days_within"] == 1     # only the on-goal day
    assert out["adherence"]["pct_within"] == 50
    assert out["adherence"]["streak"] == 2          # today and yesterday, consecutive


def test_macro_balance_percentages() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn)
    # 100 g of a product that is pure protein: 25 g protein → 100 kcal.
    pid = _product(conn, "изолят", (100, 25, 0, 0))
    _log_meal(conn, pid, 100, date.today())

    out = _get(conn, days=7)

    assert out["macros"]["protein"] == 25
    assert out["macros"]["protein_pct"] == 100      # all energy from protein
    assert out["macros"]["fat_pct"] == 0


def test_spending_by_category() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn)
    pid = _product(conn, "молоко", (60, 3, 3, 5), category="молочное")
    rid = conn.execute(
        "INSERT INTO receipts (store_name, purchased_at, total, raw_text, source_format) "
        "VALUES ('Лента', ?, 200, '', 'ofd_ru')",
        (date.today().isoformat() + "T10:00:00",),
    ).lastrowid
    conn.execute(
        "INSERT INTO receipt_items (receipt_id, raw_name, qty, unit_price, total, product_id) "
        "VALUES (?, 'Молоко', 1, 80, 80, ?)",
        (rid, pid),
    )
    conn.execute(
        "INSERT INTO receipt_items (receipt_id, raw_name, qty, unit_price, total, product_id) "
        "VALUES (?, 'Пакет', 1, 5, 5, NULL)",
        (rid,),
    )
    conn.commit()

    out = _get(conn, days=7)

    assert out["spending"]["total"] == 85
    cats = {c["category"]: c["amount"] for c in out["spending"]["by_category"]}
    assert cats["молочное"] == 80
    assert cats["не распознано"] == 5


def test_old_data_outside_window_excluded() -> None:
    conn = get_connection(":memory:")
    _set_goal(conn)
    pid = _product(conn, "хлеб", (250, 8, 3, 48))
    _log_meal(conn, pid, 100, date.today() - timedelta(days=20))  # outside a 7-day window

    out = _get(conn, days=7)

    assert out["adherence"]["days_logged"] == 0
    assert all(s["kcal"] == 0 for s in out["series"])
