"""Lenient JSON parsing for OpenAI-compatible responses (weak-model robustness)."""

from __future__ import annotations

import pytest

from nutriologist.llm.openai_compatible_client import _loads_lenient


def test_plain_json() -> None:
    assert _loads_lenient('{"a": 1}') == {"a": 1}


def test_strips_markdown_fence() -> None:
    assert _loads_lenient('```json\n{"a": 1}\n```') == {"a": 1}
    assert _loads_lenient('```\n{"a": 1}\n```') == {"a": 1}


def test_ignores_trailing_prose() -> None:
    # The "Extra data" case: valid JSON followed by extra text.
    assert _loads_lenient('{"a": 1}\nНадеюсь, это помогло!') == {"a": 1}


def test_non_json_still_raises() -> None:
    with pytest.raises(ValueError):
        _loads_lenient("совсем не json")


# --- strict json_schema -> json_object fallback -----------------------------

openai = pytest.importorskip("openai")
import httpx  # noqa: E402  (openai depends on httpx, so it's always present here)

from nutriologist.llm.openai_compatible_client import (  # noqa: E402
    OpenAICompatibleStructuredClient,
)


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Msg(content)
        self.finish_reason = "stop"


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _FakeCompletions:
    """Records calls and simulates a provider that 422s on strict json_schema
    (like Mistral / some AI Studio models) but answers in json_object mode."""

    def __init__(self, reject_status: int | None) -> None:
        self.reject_status = reject_status
        self.formats: list[str] = []

    def create(self, *, model, messages, response_format):
        self.formats.append(response_format["type"])
        if response_format["type"] == "json_schema" and self.reject_status is not None:
            resp = httpx.Response(
                status_code=self.reject_status,
                request=httpx.Request("POST", "http://test/chat/completions"),
            )
            raise openai.APIStatusError("Unprocessable schema", response=resp, body=None)
        return _Resp('{"ok": true}')


def _client_with(fake: _FakeCompletions) -> OpenAICompatibleStructuredClient:
    c = object.__new__(OpenAICompatibleStructuredClient)
    c._model = "test-model"
    c._client = type("C", (), {"chat": type("Ch", (), {"completions": fake})()})()
    return c


def test_falls_back_to_json_object_on_422() -> None:
    fake = _FakeCompletions(reject_status=422)
    client = _client_with(fake)
    out = client.generate_json(system="s", user="u", json_schema={"type": "object"})
    assert out == {"ok": True}
    # Tried strict first, then degraded to json_object.
    assert fake.formats == ["json_schema", "json_object"]


def test_strict_path_used_when_provider_accepts_it() -> None:
    fake = _FakeCompletions(reject_status=None)
    client = _client_with(fake)
    out = client.generate_json(system="s", user="u", json_schema={"type": "object"})
    assert out == {"ok": True}
    assert fake.formats == ["json_schema"]  # no fallback needed


def test_non_schema_error_is_not_retried() -> None:
    # A 401 (bad key) must surface, not silently retry in a weaker mode.
    fake = _FakeCompletions(reject_status=401)
    client = _client_with(fake)
    with pytest.raises(openai.APIStatusError):
        client.generate_json(system="s", user="u", json_schema={"type": "object"})
    assert fake.formats == ["json_schema"]
