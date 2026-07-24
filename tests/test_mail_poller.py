"""The mail poller: message → PDF on disk → fridge stock, with a fake mailbox."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

import nutriologist.receipts.pipeline as pipeline
from nutriologist.db import get_connection
from nutriologist.mail.poller import poll_mailbox
from nutriologist.receipts import ofdru
from nutriologist.receipts.parse import UnsupportedReceiptFormat

from product_fakes import RoutingFakeLLM, normalize_response, nutrition_response
from receipt_fixtures import LENTA_LIKE_TEXT


def _fake_llm() -> RoutingFakeLLM:
    return RoutingFakeLLM(
        normalize=normalize_response(canonical_name="товар", category="прочее"),
        nutrition=nutrition_response(),
    )


def _email_with_pdf(content: bytes = b"%PDF-1.4 fake") -> bytes:
    msg = EmailMessage()
    msg["From"] = "noreply@ofd.ru"
    msg["Subject"] = "Ваш чек"
    msg.set_content("чек во вложении")
    msg.add_attachment(content, maintype="application", subtype="pdf", filename="cheque.pdf")
    return msg.as_bytes()


def _email_plain() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "реклама"
    msg.set_content("никаких чеков")
    return msg.as_bytes()


class FakeMailbox:
    """In-memory Mailbox: yields unseen messages, records mark_seen calls."""

    def __init__(self, messages: list[tuple[str, bytes]]):
        self._messages = list(messages)
        self.seen: list[str] = []

    def fetch_unseen(self):
        for uid, raw in self._messages:
            if uid not in self.seen:
                yield uid, raw

    def mark_seen(self, uid: str) -> None:
        self.seen.append(uid)


@pytest.fixture
def _lenta_parse(monkeypatch):
    monkeypatch.setattr(
        pipeline, "parse_receipt_pdf", lambda path, llm=None: ofdru.parse(LENTA_LIKE_TEXT)
    )


def test_poll_imports_receipt_and_marks_seen(tmp_path, _lenta_parse) -> None:
    conn = get_connection(":memory:")
    box = FakeMailbox([("1", _email_with_pdf())])

    summary = poll_mailbox(conn, box, _fake_llm(), receipts_dir=tmp_path)

    assert summary.messages_seen == 1
    assert summary.imported == 1
    assert summary.duplicates == 0
    assert summary.errors == 0
    r = summary.receipts[0]
    assert r.ok and r.result is not None
    assert r.result.items_posted > 0
    assert r.saved_path.exists()  # PDF was persisted to disk
    assert box.seen == ["1"]


def test_repoll_same_receipt_is_idempotent(tmp_path, _lenta_parse) -> None:
    conn = get_connection(":memory:")
    box = FakeMailbox([("1", _email_with_pdf())])

    # mark_seen=False keeps the message unseen so the second poll re-fetches it,
    # exercising the fingerprint dedup rather than the fetch-side filter.
    first = poll_mailbox(conn, box, _fake_llm(), receipts_dir=tmp_path, mark_seen=False)
    second = poll_mailbox(conn, box, _fake_llm(), receipts_dir=tmp_path, mark_seen=False)

    assert first.imported == 1
    assert second.imported == 0
    assert second.duplicates == 1
    assert box.seen == []  # never flagged


def test_non_receipt_mail_is_marked_seen_without_import(tmp_path, _lenta_parse) -> None:
    conn = get_connection(":memory:")
    box = FakeMailbox([("7", _email_plain())])

    summary = poll_mailbox(conn, box, _fake_llm(), receipts_dir=tmp_path)

    assert summary.messages_seen == 1
    assert summary.receipts == []
    assert box.seen == ["7"]  # nothing to retry → flag it


def test_parse_failure_is_recorded_and_left_unseen(tmp_path, monkeypatch) -> None:
    conn = get_connection(":memory:")

    def _boom(path, llm=None):
        raise UnsupportedReceiptFormat("текст")

    monkeypatch.setattr(pipeline, "parse_receipt_pdf", _boom)
    box = FakeMailbox([("3", _email_with_pdf())])

    summary = poll_mailbox(conn, box, _fake_llm(), receipts_dir=tmp_path)

    assert summary.errors == 1
    assert summary.imported == 0
    assert summary.receipts[0].ok is False
    assert box.seen == []  # left unseen so a later poll can retry


def test_fetch_side_filter_skips_already_seen(tmp_path, _lenta_parse) -> None:
    conn = get_connection(":memory:")
    box = FakeMailbox([("1", _email_with_pdf())])

    poll_mailbox(conn, box, _fake_llm(), receipts_dir=tmp_path)
    second = poll_mailbox(conn, box, _fake_llm(), receipts_dir=tmp_path)

    assert second.messages_seen == 0  # already flagged, not re-fetched
