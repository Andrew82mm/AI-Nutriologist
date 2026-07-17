"""Deterministic parser for OFD.RU-formatted cash receipts (e.g. Лента, О'КЕЙ).

pdftotext flattens the receipt's original table/label layout into a stream of
lines, but it reliably preserves blank lines between the original visual
"cells". This parser leans on that: it groups lines into paragraphs (runs of
non-blank lines separated by blank lines) and looks for the paragraph whose
first line is a "quantity X unit_price" line — that paragraph always holds
the quantity/price/VAT/total for one line item, and the paragraph immediately
before it is always that item's name.
"""

from __future__ import annotations

import re
from datetime import datetime

from .models import ParsedReceipt, ReceiptItem

_QTY_PRICE_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[XxХх]\s*(\d+(?:[.,]\d+)?)$")
_AMOUNT_RE = re.compile(r"=\s*(\d+(?:[.,]\d+)?)")
_VAT_RE = re.compile(r"НДС\s*(\d+)\s*%\s*=?\s*(\d+(?:[.,]\d+)?)?")
_UNIT_RE = re.compile(r"^(шт\.|кг|ед\.|г|мл|л)$")
_FPD_RE = re.compile(r"\bФПД\s+(\d+)")
_FD_NUMBER_RE = re.compile(r"#(\d+)")
_DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{2})\s+(\d{2}:\d{2})")
_ITOG_VALUE_RE = re.compile(r"^(\d+(?:[.,]\d+)?)$")


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def _split_paragraphs(text: str) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append(current)
    return paragraphs


def looks_like_ofdru(text: str) -> bool:
    """OFD.RU's own check-verification domain — a signature unique to
    receipts it renders, unlike other ОФД providers (e.g. Яндекс.ОФД)."""
    return "check.ofd.ru" in text


def _parse_items(paragraphs: list[list[str]]) -> list[ReceiptItem]:
    items: list[ReceiptItem] = []

    for i, paragraph in enumerate(paragraphs):
        qty_price_match = _QTY_PRICE_RE.match(paragraph[0])
        if not qty_price_match or i == 0:
            continue

        quantity = _to_float(qty_price_match.group(1))
        unit_price = _to_float(qty_price_match.group(2))

        joined = " ".join(paragraph)
        amount_matches = _AMOUNT_RE.findall(joined)
        if not amount_matches:
            continue
        total = _to_float(amount_matches[-1])

        vat_rate: int | None = None
        vat_amount: float | None = None
        vat_match = _VAT_RE.search(joined)
        if vat_match:
            vat_rate = int(vat_match.group(1))
            if vat_match.group(2):
                vat_amount = _to_float(vat_match.group(2))

        name = " ".join(paragraphs[i - 1]).strip().rstrip(",")

        unit: str | None = None
        for follow in paragraphs[i + 1 :]:
            if _QTY_PRICE_RE.match(follow[0]):
                break
            if follow == ["ИТОГ"]:
                break
            if len(follow) == 1 and _UNIT_RE.match(follow[0]):
                unit = follow[0]

        items.append(
            ReceiptItem(
                raw_name=name,
                quantity=quantity,
                unit_price=unit_price,
                total=total,
                unit=unit,
                vat_rate=vat_rate,
                vat_amount=vat_amount,
            )
        )

    return items


def _parse_store_name(text: str) -> str | None:
    match = re.search(r"Кассовый чек\s*/\s*Приход\s*\n([^\n]+)", text)
    return match.group(1).strip() if match else None


def _parse_fd_number(text: str) -> str | None:
    header = text.split("Кассовый чек / Приход", 1)
    scope = header[1] if len(header) > 1 else text
    match = _FD_NUMBER_RE.search(scope)
    return match.group(1) if match else None


def _parse_purchased_at(text: str) -> datetime | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    date_part, time_part = match.groups()
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%d.%m.%y %H:%M")
    except ValueError:
        return None


def _parse_fpd(text: str) -> str | None:
    match = _FPD_RE.search(text)
    return match.group(1) if match else None


def _parse_total(paragraphs: list[list[str]]) -> float | None:
    for i, paragraph in enumerate(paragraphs):
        if paragraph == ["ИТОГ"] and i + 1 < len(paragraphs):
            value_match = _ITOG_VALUE_RE.match(paragraphs[i + 1][0])
            if value_match:
                return _to_float(value_match.group(1))
    return None


def parse(text: str) -> ParsedReceipt:
    paragraphs = _split_paragraphs(text)
    return ParsedReceipt(
        store_name=_parse_store_name(text),
        fd_number=_parse_fd_number(text),
        fpd=_parse_fpd(text),
        purchased_at=_parse_purchased_at(text),
        total=_parse_total(paragraphs),
        items=_parse_items(paragraphs),
        source_format="ofd_ru",
        raw_text=text,
    )
