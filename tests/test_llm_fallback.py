from __future__ import annotations

from typing import Any

import pytest

from nutriologist.llm.client import StructuredLLMClient
from nutriologist.receipts.llm_fallback import extract_receipt
from nutriologist.receipts.parse import UnsupportedReceiptFormat, parse_receipt_text

from receipt_fixtures import LENTA_LIKE_TEXT, YANDEX_LIKE_TEXT


class FakeLLMClient:
    """Minimal StructuredLLMClient stub for tests — no network, no API key,
    no dependency on any particular provider SDK."""

    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self, *, system: str, user: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "json_schema": json_schema})
        return self.response


# Modeled on a Yandex.Food-style receipt (see YANDEX_LIKE_TEXT), which the
# deterministic OFD.RU parser correctly refuses to touch (different ОФД).
YANDEX_LIKE_RESPONSE: dict[str, Any] = {
    "store_name": 'ООО "ЯНДЕКС.ЕДА"',
    "fd_number": "90850",
    "fpd": "888106157",
    "purchased_at": "2022-06-21T19:25:00",
    "total": 605.00,
    "items": [
        {
            "raw_name": "8 Острых крылышек",
            "quantity": 1,
            "unit_price": 179.00,
            "total": 179.00,
            "unit": None,
        },
        {
            "raw_name": "Баскет Фри",
            "quantity": 1,
            "unit_price": 86.00,
            "total": 86.00,
            "unit": None,
        },
        {
            "raw_name": "Соус Барбекю",
            "quantity": 1,
            "unit_price": 24.00,
            "total": 24.00,
            "unit": None,
        },
        {
            "raw_name": "Соус Сырный",
            "quantity": 1,
            "unit_price": 24.00,
            "total": 24.00,
            "unit": None,
        },
        {
            "raw_name": "Шефбургер Де Люкс Оригинальный",
            "quantity": 1,
            "unit_price": 97.00,
            "total": 97.00,
            "unit": None,
        },
        {
            "raw_name": "Шефбургер Де Люкс Оригинальный",
            "quantity": 1,
            "unit_price": 98.00,
            "total": 98.00,
            "unit": None,
        },
        {
            "raw_name": "Шефбургер Де Люкс Острый",
            "quantity": 1,
            "unit_price": 97.00,
            "total": 97.00,
            "unit": None,
        },
    ],
}


def test_fake_llm_client_satisfies_protocol() -> None:
    llm = FakeLLMClient(YANDEX_LIKE_RESPONSE)
    assert isinstance(llm, StructuredLLMClient)


def test_extract_receipt_maps_llm_response_to_parsed_receipt() -> None:
    llm = FakeLLMClient(YANDEX_LIKE_RESPONSE)

    receipt = extract_receipt("some raw receipt text", llm)

    assert receipt.source_format == "llm_fallback"
    assert receipt.store_name == 'ООО "ЯНДЕКС.ЕДА"'
    assert receipt.fd_number == "90850"
    assert receipt.fpd == "888106157"
    assert receipt.purchased_at is not None
    assert receipt.purchased_at.isoformat() == "2022-06-21T19:25:00"
    assert receipt.total == 605.00
    assert len(receipt.items) == 7
    assert receipt.items_total == 605.00
    assert receipt.raw_text == "some raw receipt text"


def test_extract_receipt_passes_text_and_schema_to_llm() -> None:
    llm = FakeLLMClient(YANDEX_LIKE_RESPONSE)

    extract_receipt("receipt text goes here", llm)

    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["user"] == "receipt text goes here"
    assert call["json_schema"]["type"] == "object"
    assert "items" in call["json_schema"]["properties"]


def test_extract_receipt_handles_missing_date() -> None:
    response = {**YANDEX_LIKE_RESPONSE, "purchased_at": None}
    llm = FakeLLMClient(response)

    receipt = extract_receipt("text", llm)

    assert receipt.purchased_at is None


def test_extract_receipt_handles_unparseable_date() -> None:
    response = {**YANDEX_LIKE_RESPONSE, "purchased_at": "not a date"}
    llm = FakeLLMClient(response)

    receipt = extract_receipt("text", llm)

    assert receipt.purchased_at is None


def test_dispatcher_uses_llm_fallback_for_unsupported_format() -> None:
    llm = FakeLLMClient(YANDEX_LIKE_RESPONSE)

    receipt = parse_receipt_text(YANDEX_LIKE_TEXT, llm=llm)

    assert receipt.source_format == "llm_fallback"
    assert len(llm.calls) == 1
    assert llm.calls[0]["user"] == YANDEX_LIKE_TEXT


def test_dispatcher_raises_without_llm_client_for_unsupported_format() -> None:
    with pytest.raises(UnsupportedReceiptFormat):
        parse_receipt_text(YANDEX_LIKE_TEXT)


def test_dispatcher_prefers_deterministic_parser_over_llm() -> None:
    """When a deterministic parser matches, the LLM must not be called."""
    llm = FakeLLMClient(YANDEX_LIKE_RESPONSE)

    receipt = parse_receipt_text(LENTA_LIKE_TEXT, llm=llm)

    assert receipt.source_format == "ofd_ru"
    assert llm.calls == []
