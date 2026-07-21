"""Phase B: the /api/receipts/import endpoint wiring the receipt pipeline."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import nutriologist.api.receipts_import as ri
from nutriologist.db import get_connection
from nutriologist.receipts import ofdru

from product_fakes import RoutingFakeLLM, normalize_response, nutrition_response
from receipt_fixtures import LENTA_LIKE_TEXT


def _fake_llm() -> RoutingFakeLLM:
    return RoutingFakeLLM(
        normalize=normalize_response(canonical_name="товар", category="прочее"),
        nutrition=nutrition_response(),
    )


def _pdf(tmp_path):
    p = tmp_path / "receipt.pdf"
    p.write_bytes(b"%PDF-1.4 fake")  # content irrelevant — parse is monkeypatched
    return p


def _import(conn, path):
    return ri.import_receipt(ri.ReceiptImportIn(path=str(path)), conn)


def test_import_parses_normalizes_and_stocks(tmp_path, monkeypatch) -> None:
    conn = get_connection(":memory:")
    monkeypatch.setattr(ri, "get_optional_llm", _fake_llm)
    monkeypatch.setattr(ri, "parse_receipt_pdf", lambda path, llm=None: ofdru.parse(LENTA_LIKE_TEXT))

    out = _import(conn, _pdf(tmp_path))

    assert out.receipt_id > 0
    assert out.duplicate is False
    assert out.items_parsed == 3
    assert out.items_normalized == 3
    assert out.items_posted > 0


def test_reimport_same_receipt_is_idempotent(tmp_path, monkeypatch) -> None:
    conn = get_connection(":memory:")
    monkeypatch.setattr(ri, "get_optional_llm", _fake_llm)
    monkeypatch.setattr(ri, "parse_receipt_pdf", lambda path, llm=None: ofdru.parse(LENTA_LIKE_TEXT))
    pdf = _pdf(tmp_path)

    first = _import(conn, pdf)
    second = _import(conn, pdf)

    assert second.duplicate is True
    assert second.receipt_id == first.receipt_id
    assert second.items_normalized == 0
    assert second.items_posted == 0


def test_missing_file_is_404(tmp_path, monkeypatch) -> None:
    conn = get_connection(":memory:")
    monkeypatch.setattr(ri, "get_optional_llm", _fake_llm)

    with pytest.raises(HTTPException) as exc:
        _import(conn, tmp_path / "nope.pdf")
    assert exc.value.status_code == 404


def test_without_llm_is_422(tmp_path, monkeypatch) -> None:
    conn = get_connection(":memory:")
    monkeypatch.setattr(ri, "get_optional_llm", lambda: None)

    with pytest.raises(HTTPException) as exc:
        _import(conn, _pdf(tmp_path))
    assert exc.value.status_code == 422
