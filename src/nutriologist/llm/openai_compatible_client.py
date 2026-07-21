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

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None):
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "OpenAICompatibleStructuredClient requires the 'openai' package. "
                'Install it with: pip install -e ".[llm-openai-compatible]"'
            ) from exc

        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def generate_json(
        self, *, system: str, user: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "schema": json_schema,
                    "strict": True,
                },
            },
        )

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(
                f"OpenAI-compatible response had empty content "
                f"(finish_reason={response.choices[0].finish_reason})"
            )
        return _loads_lenient(content)
