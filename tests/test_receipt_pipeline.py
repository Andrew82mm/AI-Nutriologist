"""The shared receipt import pipeline (parse → save → normalize → income)."""

from __future__ import annotations

import nutriologist.receipts.pipeline as pipeline
from nutriologist.db import get_connection
from nutriologist.receipts import ofdru
from nutriologist.receipts.pipeline import already_imported, import_receipt_pdf

from product_fakes import RoutingFakeLLM, normalize_response, nutrition_response
from receipt_fixtures import LENTA_LIKE_TEXT


def _fake_llm() -> RoutingFakeLLM:
    return RoutingFakeLLM(
        normalize=normalize_response(canonical_name="товар", category="прочее"),
        nutrition=nutrition_response(),
    )


def test_import_stocks_fridge_and_is_idempotent(tmp_path, monkeypatch) -> None:
    conn = get_connection(":memory:")
    monkeypatch.setattr(
        pipeline, "parse_receipt_pdf", lambda path, llm=None: ofdru.parse(LENTA_LIKE_TEXT)
    )
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF fake")

    first = import_receipt_pdf(conn, pdf, _fake_llm())
    assert first.duplicate is False
    assert first.items_parsed == 3
    assert first.items_posted > 0

    second = import_receipt_pdf(conn, pdf, _fake_llm())
    assert second.duplicate is True
    assert second.receipt_id == first.receipt_id
    assert second.items_posted == 0


def test_already_imported_ignores_partial_fingerprint() -> None:
    conn = get_connection(":memory:")
    # No receipts yet, and a NULL half means no reliable dedup key.
    assert already_imported(conn, None, "fpd") is False
    assert already_imported(conn, "fd", None) is False
    assert already_imported(conn, "fd", "fpd") is False
