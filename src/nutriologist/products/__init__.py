"""Product normalization + nutrition (итерация 2).

Turns raw receipt line names into canonical products (cached in
`product_aliases`), extracts packaging net content, and resolves per-100
nutrition through a source cascade.
"""

from __future__ import annotations

from .models import (
    CANONICAL_UNITS,
    CATEGORIES,
    NormalizedItem,
    NutritionFacts,
    Packaging,
    Product,
)
from .normalize import normalize_product
from .nutrition import resolve_nutrition
from .packaging import extract_packaging
from .receipt_link import normalize_receipt_items

__all__ = [
    "CANONICAL_UNITS",
    "CATEGORIES",
    "NormalizedItem",
    "NutritionFacts",
    "Packaging",
    "Product",
    "extract_packaging",
    "normalize_product",
    "normalize_receipt_items",
    "resolve_nutrition",
]
