"""Smoke tests for the pipeline-quality benchmarks.

These cover the pure logic (formatting helpers, chain detection, metric math,
rendering) without touching the receipt corpus (gitignored) or a live LLM — so
they run in CI. The end-to-end runs happen locally via `python -m benchmarks.*`.
"""

from __future__ import annotations

from benchmarks import bench_coverage, bench_nutrition_llm, bench_reconciliation
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
    assert bench_coverage._chain("Gmail - Кассовый чек ООО _Лента_ .pdf") == "Лента"
    assert bench_coverage._chain("Чек от МАГНИТ.pdf") == "Магнит"
    assert bench_coverage._chain("Перекрёсток 179.pdf") == "Перекрёсток"
    assert bench_coverage._chain("что-то неизвестное.pdf") == "прочее"


def test_reconciliation_render_handles_empty() -> None:
    # No corpus (as in CI) → empty result must still render without error.
    res = bench_reconciliation.ReconResult(rows=[])
    out = bench_reconciliation.render(res)
    assert "Сходимость парсинга" in out
    assert res.mean_abs_delta is None and res.worst is None


def test_reconciliation_flags_mismatch() -> None:
    rows = [
        bench_reconciliation.ReconRow("ok", "О'КЕЙ", "ofd_ru", 100.0, 100.0, 0.0, 5, True),
        bench_reconciliation.ReconRow("bad", "Лента", "ofd_ru", 100.0, 91.0, -9.0, 4, False),
        bench_reconciliation.ReconRow("skip", "—", "needs_llm", None, None, None, 0, False),
    ]
    res = bench_reconciliation.ReconResult(rows=rows)
    assert len(res.parsed) == 2          # needs_llm excluded from the denominator
    assert len(res.reconciled) == 1
    assert res.mean_abs_delta == 4.5     # (0 + 9) / 2
    assert res.worst.label == "bad"


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
