"""Rule-based Russian food-phrase parser for the chat endpoint.

A Python port of the prototype's client-side `parseFoods` (web/…dc.html): turn
free text like «съел два яйца и творог 5% 200 г» into a list of
(canonical product, grams, unit) matches with per-100 macros. It is deliberately
a small deterministic parser — no LLM — so the chat works offline and cheaply.
When an LLM is configured, product resolution/nutrition for *unknown* foods is a
later enhancement layered on top; this table covers the staples the demo uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Per-100 g (or ml) macros, keyed by fuzzy stem list. `gpu` = grams per unit for
# piece-goods (eggs), `def_g` = default grams when no quantity is given.
_FOODS: list[dict] = [
    {"keys": ["творог", "творож"], "name": "творог 5%", "cat": "молочное", "unit": "г", "def_g": 200, "per100": (121, 17.2, 5, 1.8)},
    {"keys": ["яйц", "яиц", "яйк"], "name": "яйцо куриное", "cat": "молочное", "unit": "шт", "gpu": 50, "per100": (157, 12.7, 11.5, 0.7)},
    {"keys": ["молок", "молоч"], "name": "молоко 2,5%", "cat": "молочное", "unit": "мл", "def_g": 200, "per100": (52, 2.9, 2.5, 4.7)},
    {"keys": ["куриц", "куриное", "филе", "куру", "курин"], "name": "куриное филе", "cat": "мясо", "unit": "г", "def_g": 150, "per100": (110, 23, 1.2, 0)},
    {"keys": ["гречк", "гречн"], "name": "гречка", "cat": "крупы/макароны", "unit": "г", "def_g": 150, "per100": (313, 12.6, 3.3, 62)},
    {"keys": ["абрикос"], "name": "абрикос", "cat": "фрукты", "unit": "г", "def_g": 100, "per100": (44, 0.9, 0.1, 9)},
    {"keys": ["помидор", "томат"], "name": "помидор", "cat": "овощи", "unit": "шт", "gpu": 120, "per100": (20, 0.6, 0.2, 4.2)},
    {"keys": ["борщ"], "name": "борщ", "cat": "блюда", "unit": "г", "def_g": 400, "per100": (49, 1.1, 2.1, 6.7)},
    {"keys": ["жарко"], "name": "жаркое", "cat": "блюда", "unit": "г", "def_g": 300, "per100": (184, 7, 11, 10)},
    {"keys": ["говядин", "говяж"], "name": "говядина", "cat": "мясо", "unit": "г", "def_g": 150, "per100": (187, 18.9, 12.4, 0)},
    {"keys": ["картоф", "картош"], "name": "картофель", "cat": "овощи", "unit": "г", "def_g": 200, "per100": (77, 2, 0.4, 16.3)},
]

_WORD_NUMS = {
    "полкило": 500, "пол-кило": 500, "один": 1, "одно": 1, "одну": 1, "одна": 1,
    "два": 2, "две": 2, "пару": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "десять": 10, "дюжина": 12,
}

# Canonical unit token per display unit, for the ledger.
_CANON_UNIT = {"г": "g", "мл": "ml", "шт": "piece"}


@dataclass
class ParsedFood:
    name: str
    cat: str
    grams: float          # amount in canonical measure (g/ml, or piece count for шт)
    unit: str             # display unit: г | мл | шт
    canonical_unit: str   # g | ml | piece
    kcal: float           # macros for this portion
    protein: float
    fat: float
    carbs: float
    per100: tuple         # (kcal, protein, fat, carbs) per 100 — for the nutrition table
    amount_canonical: float  # amount in the product's canonical_unit: pieces for шт, else grams


def _macros_for(per100: tuple, grams: float) -> tuple[float, float, float, float]:
    k = grams / 100
    kcal, b, zh, u = per100
    return kcal * k, b * k, zh * k, u * k


def parse_foods(text: str) -> list[ParsedFood]:
    """Extract every recognized food + quantity from a Russian phrase."""
    t = " " + text.lower().replace("ё", "е") + " "
    t = re.sub(r"\d+(?:[.,]\d+)?\s*%", " ", t)  # strip fat % (part of name, not qty)

    matches = []
    for f in _FOODS:
        idx, kl = -1, 0
        for k in f["keys"]:
            i = t.find(k)
            if i >= 0:
                idx, kl = i, len(k)
                break
        if idx >= 0:
            matches.append({"f": f, "idx": idx, "kl": kl})
    if not matches:
        return []
    matches.sort(key=lambda m: m["idx"])

    out: list[ParsedFood] = []
    for n, mt in enumerate(matches):
        # Region: end of previous match → start of next, so quantities don't
        # bleed across foods.
        start = matches[n - 1]["idx"] + matches[n - 1]["kl"] if n > 0 else 0
        end = matches[n + 1]["idx"] if n < len(matches) - 1 else len(t)
        region = t[start:end]
        f = mt["f"]
        unit = f["unit"]
        grams = None
        count = None

        if re.search(r"кг|кило", region) and "полкило" not in region:
            m = re.search(r"([\d.,]+)\s*(кг|кило)", region)
            num = float(m.group(1).replace(",", ".")) if m else 1
            grams, unit = num * 1000, "г"
        elif "полкило" in region:
            grams, unit = 500, "г"
        else:
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*(мл|л|г|шт|штук|штуки|стакан)?", region)
            num = float(m.group(1).replace(",", ".")) if m and m.group(1) else None
            u2 = m.group(2) if m else None
            if num is None:
                for w, val in _WORD_NUMS.items():
                    if w in region:
                        num = val
                        break
            if f["unit"] == "шт":
                count = num or 1
                grams, unit = count * f.get("gpu", 100), "шт"
            elif u2 == "л":
                grams, unit = (num or 1) * 1000, "мл"
            elif u2 == "мл":
                grams, unit = num or f.get("def_g", 100), "мл"
            elif num is not None:
                grams, unit = num, f["unit"]
            else:
                grams, unit = f.get("def_g", 100), f["unit"]

        grams = round(grams)
        amount_canonical = round(count) if (unit == "шт" and count is not None) else grams
        kcal, b, zh, u = _macros_for(f["per100"], grams)
        out.append(
            ParsedFood(
                name=f["name"], cat=f["cat"], grams=grams, unit=unit,
                canonical_unit=_CANON_UNIT.get(unit, "g"),
                kcal=round(kcal, 1), protein=round(b, 1), fat=round(zh, 1), carbs=round(u, 1),
                per100=f["per100"], amount_canonical=amount_canonical,
            )
        )
    return out


# Intent detection, mirroring the prototype's buildResponse regexes.
_RE_REPORT = re.compile(r"отчет|итог за|сколько.*съе")
_RE_RECIPE = re.compile(r"приготов|рецепт|что.*съесть|что.*есть|поужин.*что")
_RE_BUY = re.compile(r"куп|прибрел|приобрел|взял|принес|закупил|запас")
_RE_EAT = re.compile(r"съе|поел|ел |выпил|перекус|позавтрак|пообед|поужин|скушал|навернул|съест")


# Meal-name keywords → canonical title, for naming a meal via chat
# («на завтрак съел…», «обед: борщ»).
_MEAL_TITLES = [
    (("завтрак", "позавтрак"), "Завтрак"),
    (("обед", "пообед"), "Обед"),
    (("ужин", "поужин"), "Ужин"),
    (("перекус",), "Перекус"),
]


def detect_meal_title(text: str) -> str | None:
    """Meal name mentioned in a phrase, or None to fall back to the time of day."""
    t = text.lower().replace("ё", "е")
    for stems, title in _MEAL_TITLES:
        if any(s in t for s in stems):
            return title
    return None


def detect_intent(text: str) -> str:
    """Classify a chat phrase: 'report' | 'recipes' | 'buy' | 'eat' | 'unknown'."""
    t = text.lower().replace("ё", "е")
    if _RE_REPORT.search(t) and not _RE_RECIPE.search(t):
        return "report"
    if _RE_RECIPE.search(t):
        return "recipes"
    if _RE_BUY.search(t):
        return "buy"
    if _RE_EAT.search(t):
        return "eat"
    return "unknown"
