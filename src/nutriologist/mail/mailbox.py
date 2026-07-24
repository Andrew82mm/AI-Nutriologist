"""The mailbox interface the poller depends on.

A tiny Protocol so `poll_mailbox` can be exercised with an in-memory fake in
tests and driven by real IMAP in production (`imap.ImapMailbox`), the same way
the receipt code depends on `StructuredLLMClient` rather than a concrete vendor.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class Mailbox(Protocol):
    """Read access to unprocessed messages, plus a way to mark them handled."""

    def fetch_unseen(self) -> Iterator[tuple[str, bytes]]:
        """Yield `(uid, raw_rfc822_bytes)` for each unseen message.

        Fetching must NOT itself mark messages as seen — the poller decides that
        via `mark_seen` once a message has been successfully handled, so a
        transient failure leaves the message to be retried on the next poll.
        """
        ...

    def mark_seen(self, uid: str) -> None:
        """Flag the message with this uid as seen so it isn't fetched again."""
        ...
