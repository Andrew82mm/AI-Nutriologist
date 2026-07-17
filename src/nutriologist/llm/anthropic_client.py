"""Reference implementation of StructuredLLMClient backed by the Claude API.

Optional dependency: requires `anthropic` (`pip install -e ".[llm-anthropic]"`).
Nothing else in this package imports the `anthropic` SDK — only this module —
so the rest of the codebase works fine without it installed.
"""

from __future__ import annotations

import json
from typing import Any


class AnthropicStructuredClient:
    """Implements StructuredLLMClient using client.messages.create with
    output_config.format (structured outputs)."""

    def __init__(self, model: str = "claude-opus-4-8", api_key: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicStructuredClient requires the 'anthropic' package. "
                'Install it with: pip install -e ".[llm-anthropic]"'
            ) from exc

        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._model = model

    def generate_json(
        self, *, system: str, user: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": json_schema}},
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("Anthropic model refused the request (stop_reason=refusal)")

        text_block = next((b for b in response.content if b.type == "text"), None)
        if text_block is None:
            raise RuntimeError(
                f"Anthropic response had no text content (stop_reason={response.stop_reason})"
            )

        return json.loads(text_block.text)
