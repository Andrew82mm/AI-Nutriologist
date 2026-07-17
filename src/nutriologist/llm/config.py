"""Build a StructuredLLMClient from environment variables / .env.

This is the layer that makes the LLM provider a deployment/config choice
instead of a code choice — see .env.example for the supported variables and
example configurations (Anthropic, OpenAI, Google Gemini, local models, ...).
"""

from __future__ import annotations

import os
from typing import Mapping

from .client import StructuredLLMClient

_dotenv_loaded = False


def _load_dotenv_once() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


class LLMConfigError(RuntimeError):
    """Raised when environment-based LLM configuration is missing or invalid."""


def load_llm_client_from_env(*, env: Mapping[str, str] | None = None) -> StructuredLLMClient:
    """Construct a StructuredLLMClient based on LLM_PROVIDER and friends.

    Args:
        env: Use these values instead of `os.environ` (mainly for tests).
             When None, loads `.env` (if `python-dotenv` is installed and a
             `.env` file exists) and then reads `os.environ`.

    Supported LLM_PROVIDER values (see .env.example for full details):
        - "anthropic": native Claude API. Needs LLM_API_KEY, optional LLM_MODEL.
        - "openai_compatible": any OpenAI-Chat-Completions-compatible API
          (OpenAI, Google Gemini's OpenAI-compat endpoint, Mistral, local
          servers, ...). Needs LLM_MODEL and LLM_API_KEY; optional LLM_BASE_URL.
    """
    if env is None:
        _load_dotenv_once()
        env = os.environ

    provider = (env.get("LLM_PROVIDER") or "").strip().lower()
    if not provider:
        raise LLMConfigError(
            "LLM_PROVIDER is not set. Copy .env.example to .env and fill it in."
        )

    api_key = env.get("LLM_API_KEY") or None
    model = env.get("LLM_MODEL") or None

    if provider == "anthropic":
        from .anthropic_client import AnthropicStructuredClient

        kwargs: dict[str, str] = {}
        if model:
            kwargs["model"] = model
        if api_key:
            kwargs["api_key"] = api_key
        return AnthropicStructuredClient(**kwargs)

    if provider == "openai_compatible":
        from .openai_compatible_client import OpenAICompatibleStructuredClient

        if not model:
            raise LLMConfigError(
                "LLM_MODEL is required when LLM_PROVIDER=openai_compatible. "
                "See .env.example."
            )
        return OpenAICompatibleStructuredClient(
            model=model,
            api_key=api_key,
            base_url=env.get("LLM_BASE_URL") or None,
        )

    raise LLMConfigError(
        f"Unknown LLM_PROVIDER '{provider}'. Supported: anthropic, openai_compatible. "
        "See .env.example."
    )
