"""Build a MailConfig (IMAP settings) from environment variables / .env.

Mirrors the LLM config's philosophy: which mailbox to poll is a deployment
choice, not a code choice. See .env.example for the supported variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from ..llm.config import _load_dotenv_once


class MailConfigError(RuntimeError):
    """Raised when environment-based mail configuration is missing or invalid."""


@dataclass(frozen=True)
class MailConfig:
    host: str
    username: str
    password: str
    port: int = 993
    folder: str = "INBOX"
    use_ssl: bool = True


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_mail_config_from_env(*, env: Mapping[str, str] | None = None) -> MailConfig:
    """Construct a MailConfig from MAIL_IMAP_HOST and friends.

    Args:
        env: Use these values instead of `os.environ` (mainly for tests).
             When None, loads `.env` (if `python-dotenv` is installed) and then
             reads `os.environ`.

    Required: MAIL_IMAP_HOST, MAIL_USERNAME, MAIL_PASSWORD.
    Optional: MAIL_IMAP_PORT (default 993), MAIL_FOLDER (default INBOX),
              MAIL_USE_SSL (default true).
    """
    if env is None:
        _load_dotenv_once()
        env = os.environ

    host = (env.get("MAIL_IMAP_HOST") or "").strip()
    username = (env.get("MAIL_USERNAME") or "").strip()
    password = env.get("MAIL_PASSWORD") or ""

    missing = [
        name
        for name, value in (
            ("MAIL_IMAP_HOST", host),
            ("MAIL_USERNAME", username),
            ("MAIL_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise MailConfigError(
            "Missing mail configuration: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in the MAIL_* section."
        )

    use_ssl = _as_bool(env.get("MAIL_USE_SSL"), default=True)

    port_raw = (env.get("MAIL_IMAP_PORT") or "").strip()
    if port_raw:
        try:
            port = int(port_raw)
        except ValueError:
            raise MailConfigError(f"MAIL_IMAP_PORT must be an integer, got {port_raw!r}.")
    else:
        port = 993 if use_ssl else 143

    folder = (env.get("MAIL_FOLDER") or "INBOX").strip() or "INBOX"

    return MailConfig(
        host=host,
        username=username,
        password=password,
        port=port,
        folder=folder,
        use_ssl=use_ssl,
    )
