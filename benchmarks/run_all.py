"""Run every benchmark and (re)generate the report card at benchmarks/REPORT.md.

    python -m benchmarks.run_all              # uses the cached LLM sample for #3
    python -m benchmarks.run_all --refresh    # re-queries the LLM for #3

#1 (coverage) and #2 (reconciliation) are free and always run live. #3 renders
from its cached sample unless --refresh is passed.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from . import bench_coverage, bench_nutrition_llm, bench_reconciliation
from ._report import bar, md_table, pct

REPORT = Path(__file__).resolve().parent / "REPORT.md"


def _summary(cov, rec, nut) -> str:
    """A one-glance table of headline numbers with Unicode bars."""
    rows = [
        ["Парсинг чеков (детерм.)", f"{cov.receipts_deterministic}/{cov.receipts_total}",
         pct(cov.receipts_deterministic, cov.receipts_total),
         bar(cov.receipts_deterministic, cov.receipts_total)],
        ["Фасовка регуляркой", f"{cov.packaging_hits}/{cov.names_total}",
         pct(cov.packaging_hits, cov.names_total), bar(cov.packaging_hits, cov.names_total)],
        ["БЖУ из датасета (без LLM)", f"{cov.nutrition_dataset_hits}/{cov.nutrition_total}",
         pct(cov.nutrition_dataset_hits, cov.nutrition_total),
         bar(cov.nutrition_dataset_hits, cov.nutrition_total)],
        ["Сходимость парсинга (офлайн-чеки)", f"{len(rec.reconciled_in_store)}/{len(rec.in_store)}",
         pct(len(rec.reconciled_in_store), len(rec.in_store)),
         bar(len(rec.reconciled_in_store), len(rec.in_store))],
    ]
    kcal_mae = "—"
    if nut.rows:
        from .bench_nutrition_llm import _metrics
        kcal_mae = f"{_metrics(nut.rows)['kcal'][0]:g} ккал"
    rows.append(["Ошибка LLM-оценки ккал (MAE)", kcal_mae, "", ""])
    return md_table(["Метрика", "Значение", "%", ""], rows)


def build(refresh: bool = False) -> str:
    cov = bench_coverage.run()
    rec = bench_reconciliation.run()
    nut = bench_nutrition_llm.run(refresh=refresh)

    header = "\n".join([
        "# Витрина качества пайплайна",
        "",
        f"_Автогенерация `python -m benchmarks.run_all` · {date.today().isoformat()}_",
        "",
        "Нарратив проекта — «из сырых чеков → чистые данные → польза». Эти метрики "
        "показывают, **сколько пайплайн делает бесплатными правилами** (до платного "
        "LLM), **насколько корректно** парсит чеки и **почему** доверяет датасету "
        "БЖУ больше, чем LLM. Выборки небольшие (корпус чеков и дев-БД) — числа "
        "иллюстративные, но получены на реальных данных.",
        "",
        "## Сводка",
        "",
        _summary(cov, rec, nut),
    ])

    return "\n\n---\n\n".join([
        header,
        bench_coverage.render(cov),
        bench_reconciliation.render(rec),
        bench_nutrition_llm.render(nut),
    ]) + "\n"


def main() -> None:
    text = build(refresh="--refresh" in sys.argv)
    REPORT.write_text(text, encoding="utf-8")
    print(f"→ {REPORT} ({len(text)} байт)")


if __name__ == "__main__":
    main()
