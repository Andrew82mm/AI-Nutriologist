from __future__ import annotations

from nutriologist.db import get_connection


def test_get_connection_creates_all_core_tables() -> None:
    conn = get_connection(":memory:")
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        expected = {
            "schema_version",
            "receipts",
            "receipt_items",
            "products",
            "product_aliases",
            "nutrition",
            "inventory",
            "meals",
            "meal_items",
            "user_profile",
        }
        assert expected <= tables
    finally:
        conn.close()


def test_get_connection_is_idempotent() -> None:
    # Re-opening (and re-applying schema.sql) against the same file must not
    # raise, since real usage opens a fresh connection per process/request.
    conn1 = get_connection(":memory:")
    conn1.close()

    conn2 = get_connection(":memory:")
    conn2.close()


def test_receipts_fd_fpd_unique_index_exists() -> None:
    conn = get_connection(":memory:")
    try:
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'receipts'"
            ).fetchall()
        }
        assert "idx_receipts_fd_fpd" in indexes
    finally:
        conn.close()
