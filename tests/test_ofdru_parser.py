from nutriologist.receipts.ofdru import looks_like_ofdru, parse

from receipt_fixtures import LENTA_LIKE_TEXT, LENTA_LIKE_TOTAL, OKEY_LIKE_TEXT, YANDEX_LIKE_TEXT


def test_looks_like_ofdru_detects_lenta_and_okey() -> None:
    assert looks_like_ofdru(LENTA_LIKE_TEXT)
    assert looks_like_ofdru(OKEY_LIKE_TEXT)


def test_looks_like_ofdru_rejects_yandex() -> None:
    assert not looks_like_ofdru(YANDEX_LIKE_TEXT)


def test_lenta_header_fields() -> None:
    receipt = parse(LENTA_LIKE_TEXT)

    assert receipt.store_name == 'ООО "Лента"'
    assert receipt.fd_number == "195404"
    assert receipt.fpd == "2992761570"
    assert receipt.purchased_at is not None
    assert receipt.purchased_at.isoformat() == "2026-01-17T21:09:00"
    assert receipt.total == LENTA_LIKE_TOTAL


def test_lenta_items_total_matches_receipt_total() -> None:
    receipt = parse(LENTA_LIKE_TEXT)

    assert len(receipt.items) == 3
    assert receipt.items_total == receipt.total


def test_lenta_first_item() -> None:
    receipt = parse(LENTA_LIKE_TEXT)
    item = receipt.items[0]

    assert item.raw_name == "Яйцо куриное ЛЕНТА СО, 10шт"
    assert item.quantity == 1.0
    assert item.unit_price == 117.87
    assert item.total == 117.87
    assert item.unit == "шт."
    assert item.vat_rate == 10
    assert item.vat_amount == 10.72


def test_lenta_weighed_item_has_kg_quantity() -> None:
    receipt = parse(LENTA_LIKE_TEXT)
    weighed = next(i for i in receipt.items if "Филе куриное" in i.raw_name)

    assert weighed.quantity == 0.914
    assert weighed.unit_price == 531.00
    assert weighed.total == 485.33
    assert weighed.unit == "кг"


def test_lenta_includes_service_line_item() -> None:
    receipt = parse(LENTA_LIKE_TEXT)
    service_items = [i for i in receipt.items if i.raw_name == "Сборка заказа"]

    assert len(service_items) == 1
    assert service_items[0].total == 74.00
    assert service_items[0].unit == "ед."


def test_okey_header_fields() -> None:
    receipt = parse(OKEY_LIKE_TEXT)

    assert receipt.store_name == 'ООО "О\'КЕЙ"'
    assert receipt.fd_number == "12789"
    assert receipt.fpd == "3742448762"


def test_okey_items_total_matches_receipt_total() -> None:
    receipt = parse(OKEY_LIKE_TEXT)

    assert len(receipt.items) == 3
    assert receipt.items_total == receipt.total


def test_okey_handles_multiline_vat_split_across_lines() -> None:
    receipt = parse(OKEY_LIKE_TEXT)
    cheese = next(i for i in receipt.items if "Hochland" in i.raw_name)

    # This item's "в т.ч. СУММА НДС 10% =\n13.64" is split across two lines
    # in the PDF text layer — regression test for that specific layout quirk.
    assert cheese.vat_rate == 10
    assert cheese.vat_amount == 13.64
    assert cheese.total == 149.99


def test_okey_duplicate_named_weighed_items_both_captured() -> None:
    receipt = parse(OKEY_LIKE_TEXT)
    chicken = [i for i in receipt.items if "Филе цыпленка" in i.raw_name]

    assert len(chicken) == 2
    assert {round(i.quantity, 3) for i in chicken} == {0.888, 1.068}


def test_yandex_receipt_is_unsupported_by_ofdru_parser() -> None:
    receipt = parse(YANDEX_LIKE_TEXT)

    # Different ОФД (Яндекс.ОФД), different layout — this parser should not
    # confidently extract items from it; that's the job of the LLM fallback.
    assert receipt.items == []
    assert receipt.total is None
