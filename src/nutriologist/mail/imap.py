"""IMAP-backed `Mailbox` over the stdlib `imaplib` (no third-party deps).

Used as a context manager so the connection is always logged out:

    with ImapMailbox(config) as box:
        for uid, raw in box.fetch_unseen():
            ...
            box.mark_seen(uid)

Messages are fetched with BODY.PEEK[] so reading them doesn't set the \\Seen
flag — the poller owns that decision (see `Mailbox.fetch_unseen`). uids here are
IMAP sequence numbers, valid within the open session, which is all the poller
needs (fetch and mark happen in one session).
"""

from __future__ import annotations

import imaplib
from collections.abc import Iterator

from .config import MailConfig


class ImapMailbox:
    def __init__(self, config: MailConfig):
        self._config = config
        self._conn: imaplib.IMAP4 | None = None

    def __enter__(self) -> "ImapMailbox":
        cfg = self._config
        if cfg.use_ssl:
            conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(cfg.host, cfg.port)
        else:
            conn = imaplib.IMAP4(cfg.host, cfg.port)
        conn.login(cfg.username, cfg.password)
        conn.select(cfg.folder)
        self._conn = conn
        return self

    def __exit__(self, *exc_info) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    def _require_conn(self) -> imaplib.IMAP4:
        if self._conn is None:
            raise RuntimeError("ImapMailbox used outside its `with` block.")
        return self._conn

    def fetch_unseen(self) -> Iterator[tuple[str, bytes]]:
        conn = self._require_conn()
        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK" or not data or data[0] is None:
            return
        for num in data[0].split():
            typ, msg_data = conn.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data:
                continue
            raw = _first_message_body(msg_data)
            if raw is None:
                continue
            yield num.decode(), raw

    def mark_seen(self, uid: str) -> None:
        conn = self._require_conn()
        conn.store(uid.encode(), "+FLAGS", "\\Seen")


def _first_message_body(msg_data) -> bytes | None:
    """Extract the RFC822 bytes from an imaplib FETCH response.

    imaplib returns a list where message bodies arrive as `(header, body)`
    tuples interleaved with bare flag strings; we want the first body blob.
    """
    for item in msg_data:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None
