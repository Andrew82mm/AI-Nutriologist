from __future__ import annotations

import pytest

from nutriologist.products import extract_packaging


@pytest.mark.parametrize(
    "raw_name, amount, unit",
    [
        ("Рис Мистраль 5х80г", 400.0, "g"),  # multi-pack, cyrillic х
        ("Кола 2*250мл", 500.0, "ml"),  # multi-pack, asterisk
        ("Молоко Простоквашино 2,5% 950мл", 950.0, "ml"),  # % must not fool it
        ("Сметана 20% 315 г", 315.0, "g"),
        ("Яйцо куриное ЛЕНТА СО, 10шт", 10.0, "piece"),
        ("Хлеб Бородинский 390 г", 390.0, "g"),
        ("Сахар 1 кг", 1000.0, "g"),  # кг -> g
        ("Вода 0,5л", 500.0, "ml"),  # л -> ml, comma decimal
    ],
)
def test_extract_packaging_recognized(raw_name: str, amount: float, unit: str) -> None:
    packaging = extract_packaging(raw_name)
    assert packaging is not None
    assert packaging.net_amount == amount
    assert packaging.net_unit == unit


@pytest.mark.parametrize(
    "raw_name",
    [
        "Огурцы",  # weight item, no packaging in name
        "Творог 5%",  # bare percentage, no unit
        "Сборка заказа",
    ],
)
def test_extract_packaging_unrecognized(raw_name: str) -> None:
    assert extract_packaging(raw_name) is None
