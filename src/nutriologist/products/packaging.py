"""Extract packaging net content from a raw receipt line name.

`quantity` on a receipt counts *packages*, not the amount inside them: "Рис
Мистраль 5х80г" has quantity=1 but is 400 g of rice. This module pulls the net
content out of the name with cheap regexes covering the common Russian
packaging patterns; anything they miss is left to the LLM in `normalize`.

All results are in canonical units: 'g' | 'ml' | 'piece' (кг/л are converted).
"""

from __future__ import annotations

import re

from .models import UNIT_GRAM, UNIT_ML, UNIT_PIECE, Packaging

# Map a Russian unit token to (canonical_unit, multiplier-to-canonical).
_UNIT_MAP: dict[str, tuple[str, float]] = {
    "кг": (UNIT_GRAM, 1000.0),
    "гр": (UNIT_GRAM, 1.0),
    "г": (UNIT_GRAM, 1.0),
    "мл": (UNIT_ML, 1.0),
    "л": (UNIT_ML, 1000.0),
    "шт": (UNIT_PIECE, 1.0),
}

_NUM = r"\d+(?:[.,]\d+)?"
# Longest tokens first so "кг"/"гр"/"мл"/"шт" win over "г"/"л".
_UNIT = r"(?:кг|гр|мл|шт|г|л)"

# "5х80г", "5 x 80 г", "2*250мл" — count × amount of a unit.
_MULTI_RE = re.compile(
    rf"(?<!\d)({_NUM})\s*[xх*]\s*({_NUM})\s*({_UNIT})\.?",
    re.IGNORECASE,
)
# "80г", "0,5 л", "10шт", "1 кг" — a single amount of a unit.
_SINGLE_RE = re.compile(
    rf"(?<!\d)({_NUM})\s*({_UNIT})\.?",
    re.IGNORECASE,
)


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def extract_packaging(raw_name: str) -> Packaging | None:
    """Best-effort packaging extraction; returns None if nothing recognized.

    Multi-pack patterns ("NxMг") take precedence over single amounts so the
    "N" isn't mistaken for the net content.
    """
    multi = _MULTI_RE.search(raw_name)
    if multi is not None:
        count = _to_float(multi.group(1))
        amount = _to_float(multi.group(2))
        canonical_unit, factor = _UNIT_MAP[multi.group(3).lower()]
        return Packaging(net_amount=count * amount * factor, net_unit=canonical_unit)

    single = _SINGLE_RE.search(raw_name)
    if single is not None:
        amount = _to_float(single.group(1))
        canonical_unit, factor = _UNIT_MAP[single.group(2).lower()]
        return Packaging(net_amount=amount * factor, net_unit=canonical_unit)

    return None
