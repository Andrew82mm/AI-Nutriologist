"""Synthetic OFD.RU-style receipt text builders for tests.

These reproduce the pdftotext-flattened paragraph structure that
`nutriologist.receipts.ofdru` relies on (see its module docstring), without
depending on any real receipt PDF or personal purchase data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ItemSpec:
    name: str
    qty: float
    unit_price: float
    total: float
    unit: str | None = None
    vat_rate: int | None = None
    vat_amount: float | None = None
    # If True, splits the VAT "= amount" continuation onto its own line
    # within the same paragraph, reproducing a pdftotext layout quirk seen
    # on some receipts (regression coverage for paragraph-joining).
    split_vat_line: bool = False


def _fmt(n: float) -> str:
    return f"{n:g}"


def _item_block(item: ItemSpec) -> str:
    lines = [item.name, "", f"{_fmt(item.qty)} X {_fmt(item.unit_price)}"]
    if item.vat_rate is not None:
        if item.split_vat_line:
            lines.append(f"В Т.Ч. НДС {item.vat_rate}% =")
            lines.append(f"{_fmt(item.vat_amount)}")
        else:
            lines.append(f"В Т.Ч. НДС {item.vat_rate}% = {_fmt(item.vat_amount)}")
    lines.append(f"СУММА = {_fmt(item.total)}")
    if item.unit:
        lines.append("")
        lines.append(item.unit)
    return "\n".join(lines)


def build_ofdru_receipt(
    *,
    store_name: str,
    fd_number: str,
    fpd: str,
    date: str,
    items: list[ItemSpec],
    total: float,
) -> str:
    """Build synthetic pdftotext-style output for an OFD.RU receipt."""
    header = "\n".join(
        [
            "Кассовый чек / Приход",
            store_name,
            f"ФД #{fd_number}",
            date,
            f"ФПД {fpd}",
            "check.ofd.ru",
        ]
    )
    item_blocks = "\n\n".join(_item_block(item) for item in items)
    footer = f"ИТОГ\n\n{_fmt(total)}"
    return f"{header}\n\n{item_blocks}\n\n{footer}\n"


LENTA_LIKE_ITEMS = [
    ItemSpec(
        name="Яйцо куриное ЛЕНТА СО, 10шт",
        qty=1.0,
        unit_price=117.87,
        total=117.87,
        unit="шт.",
        vat_rate=10,
        vat_amount=10.72,
    ),
    ItemSpec(
        name="Филе куриное",
        qty=0.914,
        unit_price=531.00,
        total=485.33,
        unit="кг",
        vat_rate=10,
        vat_amount=44.12,
    ),
    ItemSpec(
        name="Сборка заказа",
        qty=1.0,
        unit_price=74.00,
        total=74.00,
        unit="ед.",
    ),
]

LENTA_LIKE_TOTAL = round(sum(i.total for i in LENTA_LIKE_ITEMS), 2)

LENTA_LIKE_TEXT = build_ofdru_receipt(
    store_name='ООО "Лента"',
    fd_number="195404",
    fpd="2992761570",
    date="17.01.26 21:09",
    items=LENTA_LIKE_ITEMS,
    total=LENTA_LIKE_TOTAL,
)


OKEY_LIKE_ITEMS = [
    ItemSpec(
        name="Hochland Сыр плавленый ломтики",
        qty=1.0,
        unit_price=149.99,
        total=149.99,
        unit="шт.",
        vat_rate=10,
        vat_amount=13.64,
        split_vat_line=True,
    ),
    ItemSpec(
        name="Филе цыпленка",
        qty=0.888,
        unit_price=399.00,
        total=354.31,
        unit="кг",
        vat_rate=10,
        vat_amount=32.21,
    ),
    ItemSpec(
        name="Филе цыпленка",
        qty=1.068,
        unit_price=399.00,
        total=426.13,
        unit="кг",
        vat_rate=10,
        vat_amount=38.74,
    ),
]

OKEY_LIKE_TOTAL = round(sum(i.total for i in OKEY_LIKE_ITEMS), 2)

OKEY_LIKE_TEXT = build_ofdru_receipt(
    store_name='ООО "О\'КЕЙ"',
    fd_number="12789",
    fpd="3742448762",
    date="15.02.26 18:41",
    items=OKEY_LIKE_ITEMS,
    total=OKEY_LIKE_TOTAL,
)


# Different ОФД provider (Яндекс.ОФД) with a layout the deterministic OFD.RU
# parser must not confidently match — that's the LLM fallback's job.
YANDEX_LIKE_TEXT = """Яндекс.ОФД
Кассовый чек
ООО "ЯНДЕКС.ЕДА"
ФД 90850
ФПД 888106157
21.06.22 19:25
ИТОГО К ОПЛАТЕ 605.00
"""
