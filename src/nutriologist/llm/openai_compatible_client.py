"""StructuredLLMClient for any OpenAI-Chat-Completions-compatible API.

Point `base_url` at whichever provider exposes that surface — OpenAI itself,
Google's Gemini OpenAI-compatibility endpoint, Mistral, Groq, a local
Ollama/vLLM/LM Studio server, etc. This is what makes "any compatible API"
concrete instead of a slogan: one adapter, provider chosen entirely by
config (see .env.example), no per-vendor code in this project.

Optional dependency: requires `openai`
(`pip install -e ".[llm-openai-compatible]"`). Nothing else in this package
imports the `openai` SDK — only this module.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

try:  # openai is an optional dependency; the client __init__ enforces its presence.
    from openai import APIStatusError as _SCHEMA_REJECTED_ERRORS
except ImportError:  # pragma: no cover - never hit once the client is constructed.
    _SCHEMA_REJECTED_ERRORS = ()  # type: ignore[assignment]


def _is_schema_rejection(exc: Exception) -> bool:
    """True when the provider rejected the *request itself* (400/422), i.e. it
    didn't like the strict json_schema — as opposed to an auth (401/403), rate
    limit (429), or server (5xx) error, where retrying in a looser mode is
    pointless. 400 and 422 both show up in the wild for unsupported schema
    features (Mistral uses 422; some gateways use 400)."""
    return getattr(exc, "status_code", None) in (400, 422)


def _loads_lenient(content: str) -> dict[str, Any]:
    """Parse JSON from a model response, tolerating two common wrappers.

    Strict json_schema mode should return bare JSON, but weaker OpenAI-compatible
    models (small/local ones) sometimes fence it in ```json ... ``` or append
    trailing prose ("Extra data"). Strip the fences, then use `raw_decode` to take
    the first JSON value and ignore any trailing text — so one flaky model doesn't
    500 the whole request. A genuinely non-JSON response still raises.
    """
    text = _FENCE_RE.sub("", content.strip())
    obj, _end = json.JSONDecoder().raw_decode(text)
    return obj


class OpenAICompatibleStructuredClient:
    """Implements StructuredLLMClient via Chat Completions' response_format
    (json_schema mode)."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 45.0,
        max_retries: int = 1,
    ):
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "OpenAICompatibleStructuredClient requires the 'openai' package. "
                'Install it with: pip install -e ".[llm-openai-compatible]"'
            ) from exc

        # A bounded timeout matters: some models hang on strict structured-output
        # requests. Without it the default is 600 s, so one flaky call would tie
        # up the request for minutes (and callers silently fall back). Fail fast.
        self._client = openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries
        )
        self._model = model

    def generate_json(
        self, *, system: str, user: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        # Preferred path: strict json_schema, when the provider validates and
        # enforces the schema server-side. But providers disagree on which
        # JSON-Schema features they accept there — Mistral and some Google AI
        # Studio models reject nullable union types (`["string","null"]`) and
        # `null` inside `enum` with a 422 *before* generating anything, even
        # with a valid API key. When that happens, fall back to plain JSON mode
        # with the schema described in the prompt; the lenient parser below
        # copes with the looser output. This keeps "any OpenAI-compatible API"
        # true in practice instead of only for whichever provider we tested on.
        try:
            content = self._chat(system=system, user=user, json_schema=json_schema)
        except _SCHEMA_REJECTED_ERRORS as exc:
            if not _is_schema_rejection(exc):
                raise
            content = self._chat(system=system, user=user, json_schema=json_schema, strict=False)
        return _loads_lenient(content)

    def _chat(
        self, *, system: str, user: str, json_schema: dict[str, Any], strict: bool = True
    ) -> str:
        """One Chat Completions call. `strict=True` uses server-enforced
        json_schema; `strict=False` degrades to json_object mode and moves the
        schema into the system prompt (the portable, widely-supported path)."""
        if strict:
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "schema": json_schema,
                    "strict": True,
                },
            }
        else:
            # json_object mode enforces valid JSON but not the shape, so spell
            # the schema out in the prompt. Many providers also require the word
            # "json" to appear in the messages to enable this mode — the schema
            # text satisfies that.
            system = (
                f"{system}\n\n"
                "Ответь ТОЛЬКО валидным JSON-объектом, строго по этой JSON Schema "
                "(без markdown-обёртки, без пояснений):\n"
                f"{json.dumps(json_schema, ensure_ascii=False)}"
            )
            response_format = {"type": "json_object"}

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_format,
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(
                f"OpenAI-compatible response had empty content "
                f"(finish_reason={response.choices[0].finish_reason})"
            )
        return content
