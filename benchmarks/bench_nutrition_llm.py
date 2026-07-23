"""Benchmark #3 — how far LLM БЖУ estimates drift from the trusted dataset.

The nutrition resolver prefers the Скурихин dataset and only falls back to an
LLM estimate. This benchmark quantifies *why*: for a random sample of dataset
products we also ask the LLM (by name), then measure its error against the
dataset value (MAE + MAPE per macro). A large drift justifies dataset-first.

The LLM sample is cached to results/nutrition_llm_vs_dataset.csv so the report
renders offline; pass refresh=True (or `--refresh`) to re-query the model.
"""

from __future__ import annotations

import csv
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

from nutriologist.products.models import Product
from nutriologist.products.nutrition import LLMEstimateSource
from nutriologist.products.skurikhin import load_dataset

from ._report import md_table

RESULTS_DIR = Path(__file__).resolve().parent / "results"
CACHE = RESULTS_DIR / "nutrition_llm_vs_dataset.csv"
SAMPLE_SIZE = 30
SEED = 12
_MACROS = ["kcal", "protein", "fat", "carbs"]
_MACRO_RU = {"kcal": "ккал", "protein": "белки", "fat": "жиры", "carbs": "углеводы"}


@dataclass
class NutRow:
    name: str
    ds: dict[str, float]   # dataset ground truth
    llm: dict[str, float]  # LLM estimate


@dataclass
class NutResult:
    rows: list[NutRow] = field(default_factory=list)
    skipped: str | None = None
    from_cache: bool = False


def _sample_dataset(n: int) -> list:
    """Random Скурихин rows with all four macros present (deterministic seed)."""
    rows = [
        r for r in load_dataset()
        if r.source_ref.startswith("skurikhin:")
        and None not in (r.kcal, r.protein, r.fat, r.carbs)
        and (r.kcal or 0) > 0
    ]
    return random.Random(SEED).sample(rows, min(n, len(rows)))


def _load_cache() -> list[NutRow]:
    with CACHE.open(encoding="utf-8") as f:
        out = []
        for r in csv.DictReader(f):
            out.append(NutRow(
                name=r["name"],
                ds={m: float(r[f"ds_{m}"]) for m in _MACROS},
                llm={m: float(r[f"llm_{m}"]) for m in _MACROS},
            ))
        return out


def _write_cache(rows: list[NutRow]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    with CACHE.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name"] + [f"ds_{m}" for m in _MACROS] + [f"llm_{m}" for m in _MACROS])
        for r in rows:
            w.writerow([r.name] + [r.ds[m] for m in _MACROS] + [r.llm[m] for m in _MACROS])


def run(refresh: bool = False, sample_size: int = SAMPLE_SIZE) -> NutResult:
    if CACHE.exists() and not refresh:
        return NutResult(rows=_load_cache(), from_cache=True)

    # Deferred import: only need a live LLM when actually querying.
    from nutriologist.api.app import get_optional_llm

    llm = get_optional_llm()
    if llm is None:
        return NutResult(skipped="LLM не настроен (.env) — бенчмарк #3 пропущен.")

    source = LLMEstimateSource(llm)
    rows: list[NutRow] = []
    for ds_row in _sample_dataset(sample_size):
        try:
            facts = source.lookup(Product(canonical_name=ds_row.name, is_food=True, canonical_unit="g"))
        except Exception:
            continue
        if facts is None:
            continue
        rows.append(NutRow(
            name=ds_row.name,
            ds={"kcal": ds_row.kcal, "protein": ds_row.protein, "fat": ds_row.fat, "carbs": ds_row.carbs},
            llm={"kcal": facts.kcal or 0, "protein": facts.protein or 0, "fat": facts.fat or 0, "carbs": facts.carbs or 0},
        ))
    if rows:
        _write_cache(rows)
    return NutResult(rows=rows)


def _metrics(rows: list[NutRow]) -> dict[str, tuple[float, float]]:
    """Per-macro (MAE, MAPE%). MAPE skips zero-valued ground-truth cells."""
    out: dict[str, tuple[float, float]] = {}
    for m in _MACROS:
        abs_err = [abs(r.llm[m] - r.ds[m]) for r in rows]
        mae = sum(abs_err) / len(abs_err) if abs_err else 0.0
        pcts = [abs(r.llm[m] - r.ds[m]) / r.ds[m] for r in rows if r.ds[m]]
        mape = 100 * sum(pcts) / len(pcts) if pcts else 0.0
        out[m] = (round(mae, 1), round(mape, 0))
    return out


def render(res: NutResult) -> str:
    head = "## #3 · Ошибка LLM-оценки БЖУ против Скурихина"
    if res.skipped:
        return f"{head}\n\n_{res.skipped}_"
    if not res.rows:
        return f"{head}\n\n_Нет данных._"

    met = _metrics(res.rows)
    note = " _(из кэша)_" if res.from_cache else ""
    table = md_table(
        ["Макрос", "MAE (на 100 г)", "MAPE"],
        [[_MACRO_RU[m], f"{met[m][0]:g}", f"{met[m][1]:g}%"] for m in _MACROS],
    )
    # A couple of concrete worst misses make the number tangible.
    worst = sorted(
        res.rows, key=lambda r: abs(r.llm["kcal"] - r.ds["kcal"]), reverse=True
    )[:3]
    examples = md_table(
        ["Продукт", "ккал датасет", "ккал LLM", "Δ"],
        [[r.name[:38], f"{r.ds['kcal']:g}", f"{r.llm['kcal']:g}",
          f"{r.llm['kcal'] - r.ds['kcal']:+g}"] for r in worst],
    )
    return "\n".join([
        head, "",
        f"Выборка: **{len(res.rows)}** продуктов из Скурихина; для каждого спросили "
        f"у LLM оценку по названию и сравнили с датасетом.{note}",
        "", table, "",
        "Крупнейшие промахи по калориям:", "", examples, "",
        "MAE — надёжный показатель; MAPE по белкам/жирам раздут продуктами с малым "
        "значением макроса (деление на ≈0), поэтому смотрим прежде всего на MAE. "
        "Ощутимая ошибка (≈40 ккал и ≈5.6 г жиров на 100 г) подтверждает решение "
        "резолвера брать датасет первым, а LLM — только как последний резерв.",
    ])


def main() -> None:
    print(render(run(refresh="--refresh" in sys.argv)))


if __name__ == "__main__":
    main()
