"""The offline demo (`demo/run_demo.py`) must keep running end to end.

It's the first thing a reader of the README tries, so a silent break there is
worse than a failing unit test: this runs it in-process and checks that each
stage of the pipeline reports what it should.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from nutriologist.receipts import ofdru

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"


@pytest.fixture(scope="module")
def demo_module():
    spec = importlib.util.spec_from_file_location("run_demo", DEMO_DIR / "run_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sample_receipt_parses_and_reconciles() -> None:
    parsed = ofdru.parse((DEMO_DIR / "sample_receipt.txt").read_text(encoding="utf-8"))
    assert len(parsed.items) == 5
    assert parsed.total == pytest.approx(890.89)
    assert parsed.items_total == pytest.approx(parsed.total)


def test_demo_runs_offline_end_to_end(demo_module, capsys) -> None:
    demo_module.main()
    out = capsys.readouterr().out

    assert "сошлось ✓" in out
    assert "строк в таблице: 1" in out  # re-import was deduplicated
    assert "Позиций оприходовано: 4" in out  # the carrier bag is filtered out
    assert "источник: db" in out  # macros came from the dataset, not an LLM
    assert "яйцо куриное           8 piece" in out  # 10 bought − 2 eaten


def test_stub_normalizer_flags_non_food(demo_module) -> None:
    stub = demo_module.StubNormalizer()
    bag = stub.generate_json(system="", user="Пакет-майка ЛЕНТА", json_schema={})
    assert bag["is_food"] is False
    unknown = stub.generate_json(system="", user="Что-то новое", json_schema={})
    assert unknown["is_food"] is False
