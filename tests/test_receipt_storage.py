from __future__ import annotations

import sqlite3

import pytest

from nutriologist.db import get_connection
from nutriologist.receipts.models import ParsedReceipt, ReceiptItem
from nutriologist.receipts.storage import save_receipt


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = get_connection(":memory:")
    yield connection
    connection.close()


def _make_receipt(**overrides: object) -> ParsedReceipt:
    defaults: dict[str, object] = dict(
        store_name='ООО "Тест"',
        fd_number="1001",
        fpd="555000111",
        purchased_at=None,
        total=117.87,
        items=[
            ReceiptItem(
                raw_name="Яйцо куриное",
                quantity=1.0,
                unit_price=117.87,
                total=117.87,
                unit="шт.",
                vat_rate=10,
                vat_amount=10.72,
            )
        ],
        source_format="ofd_ru",
        raw_text="raw text",
    )
    defaults.update(overrides)
    return ParsedReceipt(**defaults)


def test_save_receipt_inserts_receipt_and_items(conn: sqlite3.Connection) -> None:
    receipt_id = save_receipt(conn, _make_receipt())

    row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    assert row["fd_number"] == "1001"
    assert row["fpd"] == "555000111"
    assert row["store_name"] == 'ООО "Тест"'
    assert row["total"] == 117.87

    items = conn.execute(
        "SELECT * FROM receipt_items WHERE receipt_id = ?", (receipt_id,)
    ).fetchall()
    assert len(items) == 1
    assert items[0]["raw_name"] == "Яйцо куриное"
    assert items[0]["qty"] == 1.0


def test_save_receipt_deduplicates_by_fd_and_fpd(conn: sqlite3.Connection) -> None:
    first_id = save_receipt(conn, _make_receipt())
    second_id = save_receipt(conn, _make_receipt(store_name='ООО "Другое имя"'))

    assert first_id == second_id
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM receipt_items").fetchone()[0] == 1


def test_save_receipt_different_fd_fpd_creates_separate_rows(
    conn: sqlite3.Connection,
) -> None:
    first_id = save_receipt(conn, _make_receipt(fd_number="1001", fpd="555000111"))
    second_id = save_receipt(conn, _make_receipt(fd_number="1002", fpd="555000222"))

    assert first_id != second_id
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 2


def test_save_receipt_without_fd_or_fpd_always_inserts(conn: sqlite3.Connection) -> None:
    receipt = _make_receipt(fd_number=None, fpd=None)

    first_id = save_receipt(conn, receipt)
    second_id = save_receipt(conn, receipt)

    # No fiscal fingerprint to dedup on — both imports are kept.
    assert first_id != second_id
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 2


def test_save_receipt_with_only_fpd_missing_always_inserts(
    conn: sqlite3.Connection,
) -> None:
    receipt = _make_receipt(fd_number="2001", fpd=None)

    first_id = save_receipt(conn, receipt)
    second_id = save_receipt(conn, receipt)

    assert first_id != second_id
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 2
