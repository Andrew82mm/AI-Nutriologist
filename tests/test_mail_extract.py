"""Extracting PDF attachments from raw email messages (offline, no server)."""

from __future__ import annotations

from email.message import EmailMessage

from nutriologist.mail.extract import pdf_attachments


def _message(*, attachments: list[tuple[str, bytes, str]]) -> bytes:
    """Build an RFC822 message with a text body and the given attachments.

    Each attachment is (filename, content, mime_subtype), e.g. "pdf" or
    "octet-stream" to simulate servers that mislabel PDFs.
    """
    msg = EmailMessage()
    msg["From"] = "noreply@ofd.ru"
    msg["To"] = "receipts@example.com"
    msg["Subject"] = "Ваш чек"
    msg.set_content("Электронный чек во вложении.")
    for filename, content, subtype in attachments:
        msg.add_attachment(
            content, maintype="application", subtype=subtype, filename=filename
        )
    return msg.as_bytes()


def test_extracts_pdf_by_content_type() -> None:
    raw = _message(attachments=[("cheque.pdf", b"%PDF-1.4 data", "pdf")])

    got = pdf_attachments(raw)

    assert got == [("cheque.pdf", b"%PDF-1.4 data")]


def test_extracts_pdf_by_filename_when_mislabeled() -> None:
    # Some senders attach the PDF as application/octet-stream.
    raw = _message(attachments=[("cheque.pdf", b"%PDF octet", "octet-stream")])

    got = pdf_attachments(raw)

    assert got == [("cheque.pdf", b"%PDF octet")]


def test_ignores_non_pdf_attachments() -> None:
    raw = _message(
        attachments=[
            ("logo.png", b"\x89PNG data", "octet-stream"),
            ("cheque.pdf", b"%PDF real", "pdf"),
        ]
    )

    got = pdf_attachments(raw)

    assert got == [("cheque.pdf", b"%PDF real")]


def test_no_attachments_returns_empty() -> None:
    msg = EmailMessage()
    msg["Subject"] = "just text"
    msg.set_content("no receipt here")

    assert pdf_attachments(msg.as_bytes()) == []


def test_multiple_pdfs_all_returned() -> None:
    raw = _message(
        attachments=[
            ("a.pdf", b"%PDF a", "pdf"),
            ("b.pdf", b"%PDF b", "pdf"),
        ]
    )

    got = pdf_attachments(raw)

    assert got == [("a.pdf", b"%PDF a"), ("b.pdf", b"%PDF b")]
