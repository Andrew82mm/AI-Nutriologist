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
