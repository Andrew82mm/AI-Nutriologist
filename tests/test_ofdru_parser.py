from pathlib import Path

import pytest

from nutriologist.receipts.ofdru import looks_like_ofdru, parse
from nutriologist.receipts.pdf_text import extract_text

FIXTURES_DIR = Path(__file__).parent.parent / "чеки для парса"

LENTA_PDF = FIXTURES_DIR / "Gmail - Кассовый чек + (1) подарок. ООО _Лента_ 2307,53 руб.pdf"
OKEY_PDF = FIXTURES_DIR / "Gmail - Кассовый чек + (1) подарок. ООО _О'КЕЙ_ 2943,59 руб.pdf"
YANDEX_PDF = FIXTURES_DIR / "Gmail - Кассовый чек.pdf"


@pytest.fixture(scope="module")
def lenta_text() -> str:
    return extract_text(LENTA_PDF)


@pytest.fixture(scope="module")
def okey_text() -> str:
    return extract_text(OKEY_PDF)


@pytest.fixture(scope="module")
def yandex_text() -> str:
    return extract_text(YANDEX_PDF)


def test_looks_like_ofdru_detects_lenta_and_okey(lenta_text: str, okey_text: str) -> None:
    assert looks_like_ofdru(lenta_text)
    assert looks_like_ofdru(okey_text)


def test_looks_like_ofdru_rejects_yandex(yandex_text: str) -> None:
    assert not looks_like_ofdru(yandex_text)


def test_lenta_header_fields(lenta_text: str) -> None:
    receipt = parse(lenta_text)

    assert receipt.store_name == 'ООО "Лента"'
    assert receipt.fd_number == "195404"
    assert receipt.fpd == "2992761570"
    assert receipt.purchased_at is not None
    assert receipt.purchased_at.isoformat() == "2026-01-17T21:09:00"
    assert receipt.total == 2307.53


def test_lenta_items_total_matches_receipt_total(lenta_text: str) -> None:
    receipt = parse(lenta_text)

    assert len(receipt.items) == 16
    assert receipt.items_total == receipt.total


def test_lenta_first_item(lenta_text: str) -> None:
    receipt = parse(lenta_text)
    item = receipt.items[0]

    assert item.raw_name == "Яйцо куриное ЛЕНТА СО, 10шт"
    assert item.quantity == 1.0
    assert item.unit_price == 117.87
    assert item.total == 117.87
    assert item.unit == "шт."
    assert item.vat_rate == 10
    assert item.vat_amount == 10.72


def test_lenta_weighed_item_has_kg_quantity(lenta_text: str) -> None:
    receipt = parse(lenta_text)
    weighed = next(i for i in receipt.items if "Филе куриное" in i.raw_name)

    assert weighed.quantity == 0.914
    assert weighed.unit_price == 531.00
    assert weighed.total == 485.33
    assert weighed.unit == "кг"


def test_lenta_includes_service_line_item(lenta_text: str) -> None:
    receipt = parse(lenta_text)
    service_items = [i for i in receipt.items if i.raw_name == "Сборка заказа"]

    assert len(service_items) == 1
    assert service_items[0].total == 74.00
    assert service_items[0].unit == "ед."


def test_okey_header_fields(okey_text: str) -> None:
    receipt = parse(okey_text)

    assert receipt.store_name == 'ООО "О\'КЕЙ"'
    assert receipt.fd_number == "12789"
    assert receipt.fpd == "3742448762"
    assert receipt.total == 2943.59


def test_okey_items_total_matches_receipt_total(okey_text: str) -> None:
    receipt = parse(okey_text)

    assert len(receipt.items) == 20
    assert receipt.items_total == receipt.total


def test_okey_handles_multiline_vat_split_across_lines(okey_text: str) -> None:
    receipt = parse(okey_text)
    cheese = next(i for i in receipt.items if "Hochland" in i.raw_name)

    # This item's "в т.ч. СУММА НДС 10% =\n13.64" is split across two lines
    # in the PDF text layer — regression test for that specific layout quirk.
    assert cheese.vat_rate == 10
    assert cheese.vat_amount == 13.64
    assert cheese.total == 149.99


def test_okey_duplicate_named_weighed_items_both_captured(okey_text: str) -> None:
    receipt = parse(okey_text)
    chicken = [i for i in receipt.items if "Филе цыпленка" in i.raw_name]

    assert len(chicken) == 2
    assert {round(i.quantity, 3) for i in chicken} == {0.888, 1.068}


def test_yandex_receipt_is_unsupported_by_ofdru_parser(yandex_text: str) -> None:
    receipt = parse(yandex_text)

    # Different ОФД (Яндекс.ОФД), different layout — this parser should not
    # confidently extract items from it; that's the job of the LLM fallback.
    assert receipt.items == []
    assert receipt.total is None
