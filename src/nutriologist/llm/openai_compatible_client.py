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
from typing import Any


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
        return json.loads(content)
