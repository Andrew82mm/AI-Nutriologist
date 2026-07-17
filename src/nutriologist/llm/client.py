"""Provider-agnostic LLM abstraction.

Every place in this project that needs an LLM (receipt fallback parsing,
product normalization, meal-log parsing, ...) should depend only on
`StructuredLLMClient`, never on a specific vendor SDK. Swapping providers —
Anthropic, OpenAI, a local model, whatever — means writing one adapter class
that implements this Protocol; nothing else in the codebase changes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StructuredLLMClient(Protocol):
    """A model call that returns JSON validated against a given schema.

    Implementations are responsible for whatever it takes on their provider
    to guarantee the response is valid JSON matching `json_schema` (native
    structured-output support, function/tool calling, or manual
    prompting + validation) and for raising on failure — callers should be
    able to trust the returned dict without re-validating it.
    """

    def generate_json(
        self, *, system: str, user: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one model call and return its output as a parsed dict.

        Args:
            system: System prompt / instructions.
            user: The user-turn content (e.g. receipt text to extract from).
            json_schema: JSON Schema the response must conform to.

        Returns:
            The response content, decoded from JSON into a dict.
        """
        ...
