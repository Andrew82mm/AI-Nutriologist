"""Match a canonical product to the Скурихин reference dataset for БЖУ.

The dataset (`data/skurikhin_nutrition.csv`, ~1028 rows) holds per-100 g macros
for specific Russian foods ("Молоко пастеризованное, 2,5% жирности"), while our
receipt normalization yields coarser canonical names ("молоко 2,5%"). This
module bridges that gap with a lexical retriever (no embeddings — the corpus is
tiny) that both sides feed through the same normalizer, then scores candidates:

  * gate — the row must be *titled* by the same head noun as the query (both
    first tokens equal after light stemming), so "молоко" hits rows named
    "Молоко …" but not a dish that merely mentions milk;
  * score — token overlap, an exact fat-percent match bonus, and a soft
    category-section bonus, minus a small "prefer the plainer name" penalty.

Лёгкий стеммер (`_stem`) срезает одно числовое/падежное окончание — этого хватает
на регулярные формы (яблоко↔яблоки, яйцо↔яйца) без словарей/pymorphy. Нерегулярные
основы и синонимы (куриное↔куры, гречка↔«каша гречневая») остаются промахом и
честно падают на LLM-оценку в каскаде.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from .models import NutritionFacts, Product

_DATA_PACKAGE = "nutriologist.products"
_DATA_FILE = "data/skurikhin_nutrition.csv"

# Слова, не несущие различающего смысла в именах — выкидываем из токенов, чтобы
# они не разбавляли overlap и «prefer plainer».
_STOPWORDS = frozenset(
    {"жирности", "жирность", "высшего", "первого", "сорта", "сорт", "кат", "по"}
)

# Наш закрытый enum категорий (models.CATEGORIES) → верхний раздел датасета.
# Мягкий сигнал: совпадение даёт бонус, отсутствие маппинга — не штраф. Часть
# категорий (консервы/заморозка/бакалея/…) размазаны по разделам, их не мапим.
_CATEGORY_TO_SECTION: dict[str, str] = {
    "молочное": "МОЛОКО И МОЛОЧНЫЕ ПРОДУКТЫ",
    "мясо": "МЯСО И МЯСНЫЕ ПРОДУКТЫ",
    "рыба": "РЫБА. НЕРЫБНЫЕ ОБЪЕКТЫ ПРОМЫСЛА И ПРОДУКТЫ ИЗ НИХ",
    "овощи": "ОВОЩИ, ГРИБЫ И ПРОДУКТЫ ИХ ПЕРЕРАБОТКИ",
    "фрукты": "ФРУКТЫ, ЯГОДЫ И ПРОДУКТЫ ИХ ПЕРЕРАБОТКИ",
    "крупы/макароны": "ЗЕРНО И ПРОДУКТЫ ЕГО ПЕРЕРАБОТКИ",
    "напитки": "НАПИТКИ",
    "снеки": "КОНДИТЕРСКИЕ ИЗДЕЛИЯ",
}

# Ниже этого счёта совпадение считаем неуверенным → None (каскад идёт к LLM).
_MIN_SCORE = 1.0

_FAT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_PERCENT_EXPR_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_NON_CYRILLIC_RE = re.compile(r"[^а-я ]+")

# Числовые/падежные окончания, длинные раньше коротких. Срезаем ровно одно и
# только если основа остаётся ≥3 символов — это склеивает регулярные формы
# (яблоко/яблоки, яйцо/яйца, морковь/моркови) без ложных склеек вида
# сахар↔сахар-н-ое (у «сахарное» основа «сахарн», а не «сахар»).
_ENDINGS = (
    "ами", "ями", "ах", "ях", "ов", "ев", "ий", "ые", "ый", "ая", "ое",
    "ы", "и", "а", "я", "о", "е", "ь", "й", "у", "ю",
)


def _stem(token: str) -> str:
    for ending in _ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 3:
            return token[: -len(ending)]
    return token


def normalize_name(name: str) -> tuple[list[str], float | None]:
    """`"Молоко ... 2,5% жирности"` → `(["молок", ...], 2.5)`.

    Возвращает список стеммированных токенов (порядок сохранён — первый это head
    noun) и извлечённую жирность (или None). Цифры, латиница, пунктуация и
    стоп-слова выброшены; ё→е. Стемминг — для устойчивого матчинга словоформ.
    """
    text = name.lower().replace("ё", "е")
    fat_match = _FAT_RE.search(text)
    fat = float(fat_match.group(1).replace(",", ".")) if fat_match else None
    text = _PERCENT_EXPR_RE.sub(" ", text)
    text = _NON_CYRILLIC_RE.sub(" ", text)
    tokens = [_stem(t) for t in text.split() if len(t) > 1 and t not in _STOPWORDS]
    return tokens, fat


@dataclass(frozen=True)
class DatasetRow:
    code: str
    name: str
    category_path: str
    kcal: float | None
    protein: float | None
    fat: float | None
    carbs: float | None
    # Предвычислено для матчинга:
    tokens: frozenset[str]
    head: str | None
    fat_percent: float | None
    section: str


def _parse_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def load_dataset() -> tuple[DatasetRow, ...]:
    """Загрузить и проиндексировать датасет (один раз, кэш на процесс)."""
    csv_text = (
        resources.files(_DATA_PACKAGE).joinpath(_DATA_FILE).read_text(encoding="utf-8")
    )
    out: list[DatasetRow] = []
    for raw in csv.DictReader(csv_text.splitlines()):
        tokens, name_fat = normalize_name(raw["name"])
        out.append(
            DatasetRow(
                code=raw["code"],
                name=raw["name"],
                category_path=raw["category_path"],
                kcal=_parse_float(raw["kcal"]),
                protein=_parse_float(raw["protein"]),
                fat=_parse_float(raw["fat"]),
                carbs=_parse_float(raw["carbs"]),
                tokens=frozenset(tokens),
                head=tokens[0] if tokens else None,
                fat_percent=name_fat,
                section=raw["category_path"].split(" > ")[0],
            )
        )
    return tuple(out)


def _score(
    row: DatasetRow,
    query_tokens: set[str],
    query_fat: float | None,
    wanted_section: str | None,
) -> float:
    score = float(len(query_tokens & row.tokens))  # overlap (head guaranteed in)
    if query_fat is not None:
        if row.fat_percent == query_fat:
            score += 5.0
        elif row.fat_percent is not None:
            score -= 4.0  # жирность указана и не та — почти наверняка не он
    elif row.fat_percent is None:
        score += 0.5  # запрос без %, строка тоже базовая — чуть предпочтительнее
    if wanted_section is not None and row.section == wanted_section:
        score += 1.0
    score -= 0.15 * len(row.tokens)  # при прочих равных — более «простое» имя
    return score


def retrieve(
    canonical_name: str, category: str | None = None
) -> tuple[DatasetRow, float] | None:
    """Лучшая строка датасета для канонического имени, или None если неуверенно.

    Гейт: строка должна быть *озаглавлена* тем же head noun (`row.head == head`),
    а не просто упоминать его — так «молоко» ловит строки «Молоко …», но не блюдо,
    где молоко лишь ингредиент. Из прошедших берём максимум по `_score`; ниже
    `_MIN_SCORE` → None.
    """
    tokens, fat = normalize_name(canonical_name)
    if not tokens:
        return None
    head = tokens[0]
    token_set = set(tokens)
    wanted_section = _CATEGORY_TO_SECTION.get(category) if category else None

    best: tuple[DatasetRow, float] | None = None
    for row in load_dataset():
        if row.head != head:
            continue
        score = _score(row, token_set, fat, wanted_section)
        if best is None or score > best[1]:
            best = (row, score)

    if best is None or best[1] < _MIN_SCORE:
        return None
    return best


class SkurikhinSource:
    """`NutritionSource` поверх датасета Скурихина (source='db')."""

    def lookup(self, product: Product) -> NutritionFacts | None:
        match = retrieve(product.canonical_name, product.category)
        if match is None:
            return None
        row, _score_value = match
        return NutritionFacts(
            kcal=row.kcal,
            protein=row.protein,
            fat=row.fat,
            carbs=row.carbs,
            source="db",
            source_ref=f"skurikhin:{row.code}",
        )
