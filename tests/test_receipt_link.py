from __future__ import annotations

from nutriologist.db import get_connection
from nutriologist.products import normalize_receipt_items
from nutriologist.receipts.models import ParsedReceipt, ReceiptItem
from nutriologist.receipts.storage import save_receipt

from product_fakes import RoutingFakeLLM, normalize_response


def _save_two_item_receipt(conn) -> int:
    receipt = ParsedReceipt(
        store_name="ЛЕНТА",
        fd_number="123",
        fpd="456",
        purchased_at=None,
        total=100.0,
        items=[
            ReceiptItem(raw_name="Молоко 950мл", quantity=1, unit_price=80.0, total=80.0),
            ReceiptItem(raw_name="Огурцы", quantity=0.5, unit_price=40.0, total=20.0, unit="кг"),
        ],
        source_format="ofd_ru",
        raw_text="...",
    )
    return save_receipt(conn, receipt)


def test_normalize_receipt_items_links_products() -> None:
    conn = get_connection(":memory:")
    receipt_id = _save_two_item_receipt(conn)
    llm = RoutingFakeLLM(normalize=normalize_response(canonical_name="товар"))

    count = normalize_receipt_items(conn, receipt_id, llm)
    assert count == 2

    rows = conn.execute(
        "SELECT product_id FROM receipt_items WHERE receipt_id = ?", (receipt_id,)
    ).fetchall()
    assert all(r["product_id"] is not None for r in rows)


def test_normalize_receipt_items_is_idempotent() -> None:
    conn = get_connection(":memory:")
    receipt_id = _save_two_item_receipt(conn)
    llm = RoutingFakeLLM(normalize=normalize_response(canonical_name="товар"))

    assert normalize_receipt_items(conn, receipt_id, llm) == 2
    # second run: everything already linked -> nothing to do, no LLM calls
    calls_after_first = len(llm.calls)
    assert normalize_receipt_items(conn, receipt_id, llm) == 0
    assert len(llm.calls) == calls_after_first


def test_normalize_receipt_items_uses_receipt_store_for_alias() -> None:
    conn = get_connection(":memory:")
    receipt_id = _save_two_item_receipt(conn)
    llm = RoutingFakeLLM(normalize=normalize_response(canonical_name="товар"))

    normalize_receipt_items(conn, receipt_id, llm)
    stores = {
        row["store_name"]
        for row in conn.execute("SELECT store_name FROM product_aliases").fetchall()
    }
    assert stores == {"ЛЕНТА"}
