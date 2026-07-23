"""Smoke tests for the pipeline-quality benchmarks.

These cover the pure logic (formatting helpers, chain detection, metric math,
rendering) without touching the receipt corpus (gitignored) or a live LLM — so
they run in CI. The end-to-end runs happen locally via `python -m benchmarks.*`.
"""

from __future__ import annotations

from benchmarks import bench_nutrition_llm, bench_reconciliation, corpus
from benchmarks._report import bar, md_table, money, pct


def test_report_helpers() -> None:
    assert pct(1, 4) == "25%"
    assert pct(0, 0) == "—"
    assert money(None) == "—"
    assert money(1549.891) == "1549.89"
    # bar is width-accurate and clamps.
    assert bar(1, 2, width=4) == "██░░"
    assert bar(5, 2, width=4) == "████"  # clamped to 100%
    table = md_table(["a", "b"], [[1, 2], [3, 4]])
    assert table.count("\n") == 3  # header + separator + 2 rows


def test_chain_detection() -> None:
    assert corpus.chain_of("Gmail - Кассовый чек ООО _Лента_ .pdf") == "Лента"
    assert corpus.chain_of("Чек от МАГНИТ.pdf") == "Магнит"
    assert corpus.chain_of("Перекрёсток 179.pdf") == "Перекрёсток"
    assert corpus.chain_of("что-то неизвестное.pdf") == "прочее"


def test_reconciliation_render_handles_empty() -> None:
    # No corpus (as in CI) → empty result must still render without error.
    res = bench_reconciliation.ReconResult(rows=[])
    out = bench_reconciliation.render(res)
    assert "Сходимость парсинга" in out
    assert res.mean_abs_delta_in_store is None and res.mismatches == []


def test_reconciliation_separates_online_from_defects() -> None:
    R = bench_reconciliation.ReconRow  # (store, fmt, total, items_total, delta, n, reconciled, online)
    rows = [
        R("О'КЕЙ", "ofd_ru", 100.0, 100.0, 0.0, 5, True, online=False),
        # Online order: Σ products < ИТОГ by the delivery fee — expected, not a defect.
        R("Лента-онлайн", "ofd_ru", 200.0, 110.0, -90.0, 6, False, online=True),
        # A true in-store mismatch — the only real defect.
        R("Лента-дефект", "ofd_ru", 100.0, 91.0, -9.0, 4, False, online=False),
        R("Магнит", "needs_llm", None, None, None, 0, False),
    ]
    res = bench_reconciliation.ReconResult(rows=rows)
    assert len(res.parsed) == 3               # needs_llm excluded
    assert len(res.in_store) == 2             # online excluded from the clean signal
    assert len(res.reconciled_in_store) == 1
    assert [r.store for r in res.mismatches] == ["Лента-дефект"]  # online is NOT a defect
    assert [r.store for r in res.online] == ["Лента-онлайн"]
    assert res.mean_abs_delta_in_store == 4.5  # (0 + 9) / 2, online excluded
    assert bench_reconciliation._status(rows[1]) == "≈ сбор/доставка"


def test_nutrition_metrics_and_render() -> None:
    rows = [
        bench_nutrition_llm.NutRow(
            "A", ds={"kcal": 100, "protein": 10, "fat": 5, "carbs": 20},
            llm={"kcal": 120, "protein": 12, "fat": 0, "carbs": 20},
        ),
        bench_nutrition_llm.NutRow(
            "B", ds={"kcal": 200, "protein": 0, "fat": 10, "carbs": 40},
            llm={"kcal": 180, "protein": 3, "fat": 15, "carbs": 40},
        ),
    ]
    met = bench_nutrition_llm._metrics(rows)
    assert met["kcal"][0] == 20.0        # MAE: (20 + 20) / 2
    assert met["carbs"][0] == 0.0        # both exact
    # MAPE for protein skips B's zero-valued ground truth (no division by zero).
    out = bench_nutrition_llm.render(bench_nutrition_llm.NutResult(rows=rows, from_cache=True))
    assert "из кэша" in out


def test_nutrition_render_skipped() -> None:
    res = bench_nutrition_llm.NutResult(skipped="LLM не настроен")
    assert "LLM не настроен" in bench_nutrition_llm.render(res)
