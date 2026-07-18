from __future__ import annotations

from dataclasses import dataclass

# Canonical unit tokens used everywhere in the project. Receipt/packaging
# strings in Russian (г/кг/мл/л/шт) are always mapped onto these.
UNIT_GRAM = "g"
UNIT_ML = "ml"
UNIT_PIECE = "piece"
CANONICAL_UNITS = frozenset({UNIT_GRAM, UNIT_ML, UNIT_PIECE})

# Closed category enum (see PLAN.md итерация 2). Kept as a plain tuple rather
# than a SQL CHECK so it can evolve without a migration; the LLM is constrained
# to it via the JSON schema, and unknown values are coerced to "прочее".
CATEGORIES = (
    "молочное",
    "овощи",
    "фрукты",
    "мясо",
    "рыба",
    "крупы/макароны",
    "бакалея",
    "консервы",
    "заморозка",
    "напитки",
    "снеки",
    "непищевое",
    "прочее",
)

# Nutrition source ranking: a higher-ranked source may overwrite a lower one,
# never the other way around (an LLM estimate must not clobber user/db data).
NUTRITION_SOURCE_RANK = {"user": 3, "db": 2, "llm_estimate": 1}


@dataclass
class Product:
    canonical_name: str
    is_food: bool
    category: str | None = None
    canonical_unit: str | None = None
    piece_weight_grams: float | None = None
    id: int | None = None


@dataclass
class Packaging:
    """Net content of one purchased package (e.g. "Рис ... 5х80г" -> 400 g)."""

    net_amount: float
    net_unit: str


@dataclass
class NormalizedItem:
    """A canonical product plus the packaging of the specific SKU it came from.

    Packaging is per-SKU (store-specific), which is why it travels alongside
    the product rather than living on it — see `product_aliases` in schema.sql.
    """

    product: Product
    net_amount: float | None = None
    net_unit: str | None = None


@dataclass
class NutritionFacts:
    """Per-100 g (or 100 ml) macros with provenance."""

    kcal: float | None
    protein: float | None
    fat: float | None
    carbs: float | None
    source: str  # 'db' | 'user' | 'llm_estimate'
    source_ref: str | None = None
