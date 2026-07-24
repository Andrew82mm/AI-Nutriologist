"""Poll the receipts mailbox and stock the fridge.

Usage:
    python -m nutriologist.mail.cli                 # one poll, then exit
    python -m nutriologist.mail.cli --watch         # poll forever
    python -m nutriologist.mail.cli --watch --interval 600
    python -m nutriologist.mail.cli --no-mark-seen  # dry-run (don't flag mail)

Mailbox settings come from `.env` (MAIL_* — see .env.example); the LLM provider
comes from `.env` too (LLM_* — normalization needs one). For unattended runs,
`--watch` loops in-process; alternatively schedule the one-shot form with cron.
"""

from __future__ import annotations

import argparse
import time

from ..db import get_connection
from ..llm.config import LLMConfigError, load_llm_client_from_env
from .config import MailConfigError, load_mail_config_from_env
from .imap import ImapMailbox
from .poller import PollSummary, poll_mailbox


def _print_summary(summary: PollSummary) -> None:
    print(
        f"писем: {summary.messages_seen} | импортировано: {summary.imported} | "
        f"дублей: {summary.duplicates} | ошибок: {summary.errors}"
    )
    for r in summary.receipts:
        if r.ok and r.result is not None:
            tag = "дубль" if r.result.duplicate else "новый"
            print(
                f"  [{tag}] {r.filename} → чек #{r.result.receipt_id} "
                f"({r.result.store_name or 'магазин ?'}), "
                f"позиций {r.result.items_parsed}, в инвентарь {r.result.items_posted}"
            )
        else:
            print(f"  [ошибка] {r.filename}: {r.error}")


def _run_once(mark_seen: bool) -> int:
    try:
        mail_config = load_mail_config_from_env()
    except MailConfigError as exc:
        print(f"Ошибка конфигурации почты: {exc}")
        return 1
    try:
        llm = load_llm_client_from_env()
    except (LLMConfigError, ImportError) as exc:
        print(f"Ошибка конфигурации LLM: {exc}")
        return 1

    conn = get_connection()
    try:
        with ImapMailbox(mail_config) as box:
            summary = poll_mailbox(conn, box, llm, mark_seen=mark_seen)
    finally:
        conn.close()

    _print_summary(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--watch", action="store_true", help="Poll on a loop instead of exiting."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Seconds between polls in --watch mode (default 300).",
    )
    parser.add_argument(
        "--no-mark-seen",
        dest="mark_seen",
        action="store_false",
        help="Don't flag processed messages (dry-run / repeated testing).",
    )
    args = parser.parse_args(argv)

    if not args.watch:
        return _run_once(args.mark_seen)

    print(f"Наблюдение за почтой, опрос каждые {args.interval}с. Ctrl+C для выхода.")
    while True:
        try:
            _run_once(args.mark_seen)
        except Exception as exc:  # keep the loop alive across transient failures
            print(f"Ошибка при опросе (продолжаю): {exc}")
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("Остановлено.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
