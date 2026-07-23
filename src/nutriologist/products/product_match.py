"""Resolve a free-typed dish/product name to a stored `products` row.

The manual meal form and chat used a byte-exact `WHERE canonical_name = ?`,
so «капустный салат», «Салат из капусты» and «салат из капусты» all missed the
same fridge product, and «бёдра» never matched «бедра». This module adds three
resolution layers, cheapest first (the products table is small — a personal
tool — so a full scan on a miss is fine):

  1. exact canonical_name (the fast path, unchanged);
  2. normalized equality — lower + ё→е + collapsed whitespace (fixes case and
     ё/е, e.g. «салат из капусты» ↔ «Салат из капусты», «бёдра» ↔ «бедра»);
  3. fuzzy token match — order-insensitive, morphology-tolerant, so
     «капустный салат» ↔ «Салат из капусты». Gated by fat-% compatibility so
     «молоко 2,5%» is never merged with «молоко 3,2%», and by a conservative
     score threshold so genuinely different dishes stay separate.

`find_exact_or_normalized` (layers 1–2 only) is the safe get-or-create key;
`resolve_product` (all three layers) is used for read-side fridge lookups.
"""

from __future__ import annotations

import re
import sqlite3
from difflib import SequenceMatcher

# Below this combined score a fuzzy match is considered too weak → None.
_FUZZY_THRESHOLD = 0.72

_PRODUCT_COLS = "id, canonical_name, category, canonical_unit, piece_weight_grams"

_FAT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_NON_CYRILLIC_RE = re.compile(r"[^а-я ]+")
_WS_RE = re.compile(r"\s+")

# Connectives that carry no identity for a dish name («салат ИЗ капусты»).
_STOPWORDS = frozenset({"из", "с", "со", "в", "во", "и", "на", "по", "для", "от", "а"})

# Plural/case/adjective endings, longest first. Stemming collapses word forms
# so «бедра»/«бедро», «капустный»/«капусты» share a root for matching.
_ENDINGS = (
    "ами", "ями", "ного", "ными", "ный", "ная", "ное", "ные", "ому", "ах", "ях",
    "ов", "ев", "ый", "ий", "ые", "ым", "ая", "ое", "ой", "ом",
    "ы", "и", "а", "я", "о", "е", "ь", "й", "у", "ю",
)


def normalize_key(name: str) -> str:
    """Layer-2 key: lower-cased, ё→е, whitespace collapsed."""
    return _WS_RE.sub(" ", (name or "").strip().lower().replace("ё", "е")).strip()


def _fat_percent(name: str) -> float | None:
    m = _FAT_RE.search(name.lower())
    return float(m.group(1).replace(",", ".")) if m else None


def _stem(token: str) -> str:
    for ending in _ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 3:
            return token[: -len(ending)]
    return token


def _tokens(name: str) -> list[str]:
    text = name.lower().replace("ё", "е")
    text = _PERCENT_RE.sub(" ", text)
    text = _NON_CYRILLIC_RE.sub(" ", text)
    return [t for t in text.split() if len(t) > 1 and t not in _STOPWORDS]


def _fuzzy_score(a_tokens: list[str], b_tokens: list[str]) -> float:
    """Order- and morphology-tolerant similarity in [0, 1]."""
    if not a_tokens or not b_tokens:
        return 0.0
    sa = {_stem(t) for t in a_tokens}
    sb = {_stem(t) for t in b_tokens}
    if not (sa & sb):
        return 0.0  # no shared root → never a match (guards short-string noise)
    # Jaccard (not containment/min): symmetric, so a one-word product like
    # «Капуста» does NOT fully match a two-word «капустный салат» just by being
    # a subset — that would misroute a salad onto cabbage stock.
    jaccard = len(sa & sb) / len(sa | sb)
    # Character ratio over sorted tokens: word order doesn't matter, and near
    # word forms («капустный» vs «капусты») still score high.
    ratio = SequenceMatcher(
        None, " ".join(sorted(a_tokens)), " ".join(sorted(b_tokens))
    ).ratio()
    return max(jaccard, ratio)


def _fat_compatible(a: float | None, b: float | None) -> bool:
    # An unstated fat % matches anything; two stated ones must be equal.
    return a is None or b is None or a == b


def find_exact_or_normalized(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """Layers 1–2 only: exact, then case/ё-insensitive equality. No fuzzy."""
    name = (name or "").strip()
    if not name:
        return None
    row = conn.execute(
        f"SELECT {_PRODUCT_COLS} FROM products WHERE canonical_name = ?", (name,)
    ).fetchone()
    if row is not None:
        return row

    key = normalize_key(name)
    for cand in conn.execute(f"SELECT {_PRODUCT_COLS} FROM products").fetchall():
        if normalize_key(cand["canonical_name"]) == key:
            return cand
    return None


def resolve_product(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """Resolve a typed name to a product via all three layers, or None.

    Fuzzy candidates are gated by fat-% compatibility and ranked by score; the
    best above `_FUZZY_THRESHOLD` wins. Read-only.
    """
    exact = find_exact_or_normalized(conn, name)
    if exact is not None:
        return exact

    query_tokens = _tokens(name)
    if not query_tokens:
        return None
    query_fat = _fat_percent(name)

    best: sqlite3.Row | None = None
    best_score = _FUZZY_THRESHOLD
    for cand in conn.execute(f"SELECT {_PRODUCT_COLS} FROM products").fetchall():
        cand_name = cand["canonical_name"]
        if not _fat_compatible(query_fat, _fat_percent(cand_name)):
            continue
        score = _fuzzy_score(query_tokens, _tokens(cand_name))
        if score >= best_score:
            best_score, best = score, cand
    return best
