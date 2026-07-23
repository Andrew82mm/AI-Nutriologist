"""Benchmark #1 — how much of the pipeline runs deterministically (for free).

The pipeline is hybrid: cheap deterministic rules first, a paid LLM call only on
a miss. This benchmark quantifies that split at three stages — and runs entirely
without an LLM, so it's free and reproducible:

  • parsing     — receipts recognised by the deterministic OFD.RU parser vs those
                  that fall back to the LLM (by `looks_like_ofdru`, per chain);
  • packaging   — net pack size pulled from the item name by regex vs left to LLM;
  • nutrition   — products the trusted dataset (Скурихин + curated + stub) can
                  cover on its own vs those needing an LLM estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutriologist.db import get_connection
from nutriologist.products.models import Product
from nutriologist.products.nutrition import resolve_nutrition
from nutriologist.products.packaging import extract_packaging
from nutriologist.receipts import ofdru
from nutriologist.receipts.pdf_text import extract_text

from ._report import md_table, pct
from .corpus import chain_of, receipt_pdfs


@dataclass
class CoverageResult:
    # parsing
    receipts_total: int = 0
    receipts_deterministic: int = 0
    by_chain: dict[str, list[int]] = field(default_factory=dict)  # chain -> [det, total]
    # packaging
    names_total: int = 0
    packaging_hits: int = 0
    # nutrition (dataset-only resolution over real products)
    nutrition_total: int = 0
    nutrition_dataset_hits: int = 0
    source_split: dict[str, int] = field(default_factory=dict)  # historical, from dev DB


def _parsing_coverage(res: CoverageResult) -> list[str]:
    """Deterministic layout recognition over the receipt corpus. Returns raw
    item names harvested from the deterministically-parsed receipts (for the
    packaging stage), as a side effect."""
    raw_names: list[str] = []
    for pdf in receipt_pdfs():
        text = extract_text(pdf)
        chain = chain_of(pdf.name)
        res.by_chain.setdefault(chain, [0, 0])
        res.by_chain[chain][1] += 1
        res.receipts_total += 1
        if ofdru.looks_like_ofdru(text):
            res.receipts_deterministic += 1
            res.by_chain[chain][0] += 1
            raw_names.extend(it.raw_name for it in ofdru.parse(text).items)
    return raw_names


def _packaging_coverage(res: CoverageResult, raw_names: list[str]) -> None:
    res.names_total = len(raw_names)
    res.packaging_hits = sum(1 for n in raw_names if extract_packaging(n) is not None)


def _nutrition_coverage(res: CoverageResult) -> None:
    """Dataset-only БЖУ resolution rate over the real (already-normalised) food
    products in the dev DB — plus the historical source split for context."""
    conn = get_connection()  # dev DB (read-only use)
    # Historical split — where existing БЖУ actually came from.
    for row in conn.execute("SELECT source, COUNT(*) n FROM nutrition GROUP BY source"):
        res.source_split[row["source"]] = row["n"]

    # Pure dataset coverage: resolve each food product with llm=None on a scratch
    # connection and id=None, so nothing is cached/saved and only the dataset +
    # stub tiers run. Dishes are excluded (they're never in a nutrition dataset).
    products = conn.execute(
        "SELECT canonical_name FROM products "
        "WHERE is_food = 1 AND (category IS NULL OR category != 'блюда')"
    ).fetchall()
    scratch = get_connection(":memory:")
    for row in products:
        res.nutrition_total += 1
        facts = resolve_nutrition(
            scratch,
            Product(canonical_name=row["canonical_name"], is_food=True, canonical_unit="g"),
            llm=None,
        )
        if facts is not None:
            res.nutrition_dataset_hits += 1


def run() -> CoverageResult:
    res = CoverageResult()
    raw_names = _parsing_coverage(res)
    _packaging_coverage(res, raw_names)
    _nutrition_coverage(res)
    return res


def render(res: CoverageResult) -> str:
    det, tot = res.receipts_deterministic, res.receipts_total
    # Neutral routing view: how many receipts each path handles per chain.
    route_rows = [
        [chain, d, t - d]
        for chain, (d, t) in sorted(res.by_chain.items())
    ]
    split = " · ".join(f"{k}: {v}" for k, v in sorted(res.source_split.items())) or "—"

    return "\n".join([
        "## #1 · Разделение труда: правила против LLM",
        "",
        "Пайплайн — гибрид: сначала дешёвые детерминированные правила, платный LLM "
        "только на промахе. Здесь — сколько работы делается бесплатно (всё меряется "
        "**без единого LLM-вызова**).",
        "",
        "**Извлечение фасовки** — размер упаковки вытащен из названия позиции "
        f"регуляркой: **{res.packaging_hits}/{res.names_total}** "
        f"({pct(res.packaging_hits, res.names_total)}) без LLM (остальное — весовые "
        "товары или нестандартные названия).",
        "",
        "**БЖУ** — покрыто доверенным датасетом (Скурихин + курируемая таблица), "
        f"llm=None: **{res.nutrition_dataset_hits}/{res.nutrition_total}** "
        f"({pct(res.nutrition_dataset_hits, res.nutrition_total)}) реальных продуктов "
        f"— бесплатно. Историческое распределение источников БЖУ в БД: {split}.",
        "",
        "**Парсинг чеков — маршрутизация по формату (не метрика качества).** "
        "Детерминированный парсер разбирает формат OFD.RU; чеки других сетей/шаблонов "
        "сознательно уходят в LLM-fallback — отдельные парсеры под каждую сеть мы не "
        f"пишем. Парсятся все {tot} чеков корпуса, разница только в цене: {det} "
        f"бесплатно правилами, {tot - det} — через LLM.",
        "",
        md_table(["Сеть", "Правилами", "Через LLM"], route_rows),
    ])


def main() -> None:
    print(render(run()))


if __name__ == "__main__":
    main()
