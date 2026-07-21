from __future__ import annotations

import sys

import pytest

import nutriologist.llm.anthropic_client as anthropic_client_module
import nutriologist.llm.openai_compatible_client as openai_compatible_module
from nutriologist.llm.config import LLMConfigError, load_llm_client_from_env


def test_missing_provider_raises_config_error() -> None:
    with pytest.raises(LLMConfigError, match="LLM_PROVIDER"):
        load_llm_client_from_env(env={})


def test_unknown_provider_raises_config_error() -> None:
    with pytest.raises(LLMConfigError, match="Unknown LLM_PROVIDER"):
        load_llm_client_from_env(env={"LLM_PROVIDER": "watsonx"})


def test_openai_compatible_without_model_raises_config_error() -> None:
    with pytest.raises(LLMConfigError, match="LLM_MODEL"):
        load_llm_client_from_env(
            env={"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": "sk-test"}
        )


def test_provider_name_is_case_and_whitespace_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class FakeAnthropic:
        def __init__(self, **kwargs: str) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(anthropic_client_module, "AnthropicStructuredClient", FakeAnthropic)

    client = load_llm_client_from_env(env={"LLM_PROVIDER": "  Anthropic  "})

    assert isinstance(client, FakeAnthropic)


def test_anthropic_provider_forwards_api_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class FakeAnthropic:
        def __init__(self, **kwargs: str) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(anthropic_client_module, "AnthropicStructuredClient", FakeAnthropic)

    load_llm_client_from_env(
        env={
            "LLM_PROVIDER": "anthropic",
            "LLM_API_KEY": "sk-ant-test-123",
            "LLM_MODEL": "claude-haiku-4-5",
        }
    )

    assert captured == {"api_key": "sk-ant-test-123", "model": "claude-haiku-4-5"}


def test_anthropic_provider_omits_unset_optional_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class FakeAnthropic:
        def __init__(self, **kwargs: str) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(anthropic_client_module, "AnthropicStructuredClient", FakeAnthropic)

    load_llm_client_from_env(env={"LLM_PROVIDER": "anthropic"})

    assert captured == {}


def test_openai_compatible_provider_forwards_all_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeOpenAICompatible:
        def __init__(self, *, model: str, api_key: str | None, base_url: str | None) -> None:
            captured.update(model=model, api_key=api_key, base_url=base_url)

    monkeypatch.setattr(
        openai_compatible_module, "OpenAICompatibleStructuredClient", FakeOpenAICompatible
    )

    load_llm_client_from_env(
        env={
            "LLM_PROVIDER": "openai_compatible",
            "LLM_API_KEY": "google-key",
            "LLM_MODEL": "gemini-2.5-flash",
            "LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/",
        }
    )

    assert captured == {
        "model": "gemini-2.5-flash",
        "api_key": "google-key",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    }


def test_anthropic_not_installed_raises_actionable_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real assertion here: without the optional dep installed, the
    config layer's error tells you exactly what to do — it doesn't leak an
    unrelated traceback or silently pick a different provider.

    Force the missing-module condition deterministically (sys.modules[name]=None
    makes `import name` raise ImportError), so the test holds whether or not the
    optional SDK happens to be installed in the running environment."""
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError, match="llm-anthropic"):
        load_llm_client_from_env(env={"LLM_PROVIDER": "anthropic"})


def test_openai_compatible_not_installed_raises_actionable_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError, match="llm-openai-compatible"):
        load_llm_client_from_env(
            env={"LLM_PROVIDER": "openai_compatible", "LLM_MODEL": "gpt-4o"}
        )
