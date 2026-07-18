"""Shared test doubles for the products module."""

from __future__ import annotations

from typing import Any


class RoutingFakeLLM:
    """A StructuredLLMClient stub that answers by which schema it's called with.

    normalize_product and estimate_nutrition are different LLM calls; this
    routes each to a canned response based on a marker field in the schema, so
    one fake can serve both. Records every call for assertions.
    """

    def __init__(
        self,
        *,
        normalize: dict[str, Any] | None = None,
        nutrition: dict[str, Any] | None = None,
    ):
        self._normalize = normalize
        self._nutrition = nutrition
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self, *, system: str, user: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "json_schema": json_schema})
        props = json_schema.get("properties", {})
        if "canonical_name" in props:
            if self._normalize is None:
                raise AssertionError("unexpected normalize call")
            return self._normalize
        if "kcal" in props:
            if self._nutrition is None:
                raise AssertionError("unexpected nutrition call")
            return self._nutrition
        raise AssertionError(f"unroutable schema: {sorted(props)}")


def normalize_response(
    *,
    canonical_name: str,
    category: str = "прочее",
    is_food: bool = True,
    canonical_unit: str | None = "g",
    net_amount: float | None = None,
    net_unit: str | None = None,
) -> dict[str, Any]:
    return {
        "canonical_name": canonical_name,
        "category": category,
        "is_food": is_food,
        "canonical_unit": canonical_unit,
        "net_amount": net_amount,
        "net_unit": net_unit,
    }
