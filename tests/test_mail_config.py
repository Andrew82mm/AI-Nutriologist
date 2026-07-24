"""Env-driven IMAP configuration."""

from __future__ import annotations

import pytest

from nutriologist.mail.config import MailConfigError, load_mail_config_from_env

_MINIMAL = {
    "MAIL_IMAP_HOST": "imap.example.com",
    "MAIL_USERNAME": "receipts@example.com",
    "MAIL_PASSWORD": "secret",
}


def test_minimal_config_uses_ssl_defaults() -> None:
    cfg = load_mail_config_from_env(env=_MINIMAL)

    assert cfg.host == "imap.example.com"
    assert cfg.username == "receipts@example.com"
    assert cfg.password == "secret"
    assert cfg.port == 993
    assert cfg.folder == "INBOX"
    assert cfg.use_ssl is True


def test_plain_connection_defaults_to_port_143() -> None:
    cfg = load_mail_config_from_env(env={**_MINIMAL, "MAIL_USE_SSL": "false"})

    assert cfg.use_ssl is False
    assert cfg.port == 143


def test_explicit_port_and_folder_win() -> None:
    cfg = load_mail_config_from_env(
        env={**_MINIMAL, "MAIL_IMAP_PORT": "1993", "MAIL_FOLDER": "Receipts"}
    )

    assert cfg.port == 1993
    assert cfg.folder == "Receipts"


@pytest.mark.parametrize("missing", ["MAIL_IMAP_HOST", "MAIL_USERNAME", "MAIL_PASSWORD"])
def test_missing_required_field_raises(missing: str) -> None:
    env = {k: v for k, v in _MINIMAL.items() if k != missing}

    with pytest.raises(MailConfigError) as exc:
        load_mail_config_from_env(env=env)
    assert missing in str(exc.value)


def test_non_integer_port_raises() -> None:
    with pytest.raises(MailConfigError):
        load_mail_config_from_env(env={**_MINIMAL, "MAIL_IMAP_PORT": "abc"})
