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
        meal: dict[str, Any] | None = None,
        cook: dict[str, Any] | None = None,
    ):
        self._normalize = normalize
        self._nutrition = nutrition
        self._meal = meal
        self._cook = cook
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
        if "intent" in props:
            if self._meal is None:
                raise AssertionError("unexpected meal-parse call")
            return self._meal
        if "yield_grams" in props:
            if self._cook is None:
                raise AssertionError("unexpected cook-parse call")
            return self._cook
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


def meal_response(*, intent: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a parse_meal_text-shaped response.

    Each item dict may set name/amount/unit/category and optional inline macros
    protein_100/fat_100/carbs_100; sane defaults fill the rest.
    """
    return {
        "intent": intent,
        "items": [
            {
                "name": it["name"],
                "amount": it.get("amount"),
                "unit": it.get("unit", "g"),
                "category": it.get("category", "прочее"),
                "protein_100": it.get("protein_100"),
                "fat_100": it.get("fat_100"),
                "carbs_100": it.get("carbs_100"),
            }
            for it in items
        ],
    }


def nutrition_response(
    *, kcal: float = 200.0, protein: float = 10.0, fat: float = 8.0, carbs: float = 20.0
) -> dict[str, Any]:
    return {"kcal": kcal, "protein": protein, "fat": fat, "carbs": carbs}


def cook_response(
    *, name: str, ingredients: list[dict[str, Any]], yield_grams: float | None = None
) -> dict[str, Any]:
    """Build a parse_cook_text-shaped response (name + ingredients + yield)."""
    return {
        "name": name,
        "yield_grams": yield_grams,
        "ingredients": [{"name": i["name"], "grams": i["grams"]} for i in ingredients],
    }
