"""LLM-based fallback parser for receipt layouts the deterministic parsers
(e.g. ofdru.py) don't recognize.

Depends only on the provider-agnostic `StructuredLLMClient` protocol — any
LLM adapter that implements it (Anthropic, or something else entirely) can
be plugged in here without touching this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..llm.client import StructuredLLMClient
from .models import ParsedReceipt, ReceiptItem

SYSTEM_PROMPT = """\
Ты извлекаешь структурированные данные из текста российского кассового чека \
(текст получен через pdftotext и может быть с потерянной вёрсткой — строки \
могут идти не в исходном порядке колонок таблицы).

Правила:
- Извлекай только то, что реально есть в тексте. Если поле нельзя определить \
надёжно — верни null, не придумывай значения.
- Извлекай ВСЕ позиции чека как есть, включая услуги и сборы (например, \
"Сборка заказа", "Сервисный сбор") — не фильтруй и не классифицируй, это \
делается отдельным шагом позже.
- raw_name — название позиции ровно как в чеке (без изменений и перевода).
- quantity — количество; для весовых товаров может быть дробным (например 0.914).
- unit_price — цена за единицу.
- total — сумма по позиции (количество × цена, с учётом округления в чеке).
- unit — единица измерения (шт., кг, г, л, мл, ед. и т.п.), если явно видна.
- purchased_at — дата и время покупки в формате ISO 8601 (YYYY-MM-DDTHH:MM:SS).
- fd_number — номер фискального документа (ФД), без символа "#".
- fpd — фискальный признак документа (ФПД).
- Числа всегда с точкой как разделителем дробной части.
"""

RECEIPT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "store_name": {"type": ["string", "null"], "description": "Название магазина/продавца"},
        "fd_number": {"type": ["string", "null"], "description": "Номер ФД без символа #"},
        "fpd": {"type": ["string", "null"], "description": "Фискальный признак документа (ФПД)"},
        "purchased_at": {
            "type": ["string", "null"],
            "description": "Дата и время покупки, ISO 8601",
        },
        "total": {"type": ["number", "null"], "description": "Итоговая сумма чека"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "total": {"type": "number"},
                    "unit": {"type": ["string", "null"]},
                },
                "required": ["raw_name", "quantity", "unit_price", "total", "unit"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["store_name", "fd_number", "fpd", "purchased_at", "total", "items"],
    "additionalProperties": False,
}


def _parse_purchased_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def extract_receipt(text: str, llm: StructuredLLMClient) -> ParsedReceipt:
    data = llm.generate_json(system=SYSTEM_PROMPT, user=text, json_schema=RECEIPT_JSON_SCHEMA)

    items = [
        ReceiptItem(
            raw_name=item["raw_name"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            total=item["total"],
            unit=item.get("unit"),
        )
        for item in data.get("items", [])
    ]

    return ParsedReceipt(
        store_name=data.get("store_name"),
        fd_number=data.get("fd_number"),
        fpd=data.get("fpd"),
        purchased_at=_parse_purchased_at(data.get("purchased_at")),
        total=data.get("total"),
        items=items,
        source_format="llm_fallback",
        raw_text=text,
    )
