"""LLM parse of a free-form Russian food phrase into intent + items.

This is the LLM-fallback half of the chat's hybrid parser: the deterministic
`api/foods.py` handles the staples it knows, and this module takes over when a
phrase mentions food the rule table doesn't cover («съел плов», «шаурма»).

It returns both what was meant — eaten (`eat`) vs bought (`buy`) — and the list
of positions, because those route to different commits (diary vs fridge). The
caller (chat) still prefers the rule-based verb detection when it's confident;
this intent is used only when the rules couldn't decide.

Depends only on the provider-agnostic `StructuredLLMClient` — reusable by any
future surface (e.g. a Telegram bot), not tied to the web API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..llm.client import StructuredLLMClient
from .models import CANONICAL_UNITS, CATEGORIES

SYSTEM_PROMPT = """\
Ты разбираешь фразу пользователя о еде на русском языке.

Верни:
- intent — «eat», если пользователь съел/выпил/перекусил, или «buy», если купил/\
приобрёл/принёс продукты домой. Если явного глагола нет, выбери по смыслу \
(«на завтрак бургер» → eat; «2 кг картошки» в контексте покупок → buy).
- items — список позиций. Для каждой:
  - name — обобщённое название продукта или блюда в единственном числе, без \
бренда и магазина, НО с жирностью/вкусом/типом, если они названы («творог 5%», \
«кофе с молоком»). Готовое блюдо оставляй как блюдо («борщ», «плов», «шаурма»).
  - amount — количество в единице canonical_unit (граммы для «g», миллилитры \
для «ml», штуки для «piece»). Если количество не названо — оцени обычную \
бытовую порцию/упаковку. Никогда не оставляй null, если можешь оценить.
  - unit — «g», «ml» или «piece».
  - category — одна из заданного списка; если не подходит ничего — «прочее».
  - protein_100 / fat_100 / carbs_100 — если в тексте для этой позиции ЯВНО \
названы БЖУ (например «с бжу 8,5 2,5 54» — это белки, жиры, углеводы в этом \
порядке), верни их как значения НА 100 ГРАММ продукта. Если названо меньше \
трёх чисел — заполни что названо, остальные ставь 0. Если БЖУ во фразе НЕ \
названы — верни все три null (тогда состав возьмём из базы).

Не придумывай продукты, которых во фразе нет. Пустой список items допустим, \
если еды во фразе не упомянуто.
"""

MEAL_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["eat", "buy"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": ["number", "null"]},
                    "unit": {"type": "string", "enum": list(CANONICAL_UNITS)},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "protein_100": {"type": ["number", "null"]},
                    "fat_100": {"type": ["number", "null"]},
                    "carbs_100": {"type": ["number", "null"]},
                },
                "required": [
                    "name", "amount", "unit", "category",
                    "protein_100", "fat_100", "carbs_100",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["intent", "items"],
    "additionalProperties": False,
}


@dataclass
class ParsedMealItem:
    name: str
    amount: float | None  # in canonical unit; None → caller estimates a default
    unit: str             # g | ml | piece
    category: str | None
    # Per-100 g macros explicitly stated in the phrase («с бжу 8,5 2,5 54»), or
    # None when not given (then the nutrition cascade fills them in).
    protein_100: float | None = None
    fat_100: float | None = None
    carbs_100: float | None = None

    @property
    def user_macros(self) -> tuple[float, float, float] | None:
        """(protein, fat, carbs) per-100 if the user stated any, else None."""
        if self.protein_100 is None and self.fat_100 is None and self.carbs_100 is None:
            return None
        return (self.protein_100 or 0.0, self.fat_100 or 0.0, self.carbs_100 or 0.0)


@dataclass
class ParsedMeal:
    intent: str  # 'eat' | 'buy'
    items: list[ParsedMealItem] = field(default_factory=list)


def _coerce_unit(value: Any) -> str:
    return value if value in CANONICAL_UNITS else "g"


def _coerce_category(value: Any) -> str | None:
    return value if value in CATEGORIES else None


def parse_meal_text(text: str, llm: StructuredLLMClient) -> ParsedMeal:
    """Parse `text` into an intent (eat/buy) and a list of food positions."""
    data = llm.generate_json(
        system=SYSTEM_PROMPT, user=text, json_schema=MEAL_JSON_SCHEMA
    )
    intent = data.get("intent")
    if intent not in ("eat", "buy"):
        intent = "eat"

    items: list[ParsedMealItem] = []
    for raw in data.get("items") or []:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        items.append(
            ParsedMealItem(
                name=name,
                amount=raw.get("amount"),
                unit=_coerce_unit(raw.get("unit")),
                category=_coerce_category(raw.get("category")),
                protein_100=raw.get("protein_100"),
                fat_100=raw.get("fat_100"),
                carbs_100=raw.get("carbs_100"),
            )
        )
    return ParsedMeal(intent=intent, items=items)
