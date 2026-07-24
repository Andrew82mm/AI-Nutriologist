"""Pull PDF attachments out of a raw RFC822 email message.

Pure and side-effect-free (bytes in, list of (filename, bytes) out) so it's the
easy, deterministic part to unit-test without touching a mail server. OFD emails
deliver the fiscal receipt as a PDF attachment; that's all we need from a
message here.
"""

from __future__ import annotations

from email import message_from_bytes
from email.message import Message
from email.policy import default


def _is_pdf(part: Message, filename: str | None) -> bool:
    if part.get_content_type() == "application/pdf":
        return True
    return bool(filename) and filename.lower().endswith(".pdf")


def pdf_attachments(raw_message: bytes) -> list[tuple[str, bytes]]:
    """Return `(filename, content)` for every PDF part in `raw_message`.

    A part counts as a PDF if its content type is `application/pdf` or its
    filename ends in `.pdf`. Parts with no decodable payload are skipped. The
    filename falls back to `receipt.pdf` when the message doesn't give one.
    """
    msg = message_from_bytes(raw_message, policy=default)

    attachments: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if not _is_pdf(part, filename):
            continue
        content = part.get_payload(decode=True)
        if not content:
            continue
        attachments.append((filename or "receipt.pdf", content))
    return attachments
