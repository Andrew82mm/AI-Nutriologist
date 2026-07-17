from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ReceiptItem:
    raw_name: str
    quantity: float
    unit_price: float
    total: float
    unit: str | None = None
    vat_rate: int | None = None
    vat_amount: float | None = None


@dataclass
class ParsedReceipt:
    store_name: str | None
    fd_number: str | None
    fpd: str | None
    purchased_at: datetime | None
    total: float | None
    items: list[ReceiptItem] = field(default_factory=list)
    source_format: str = "unknown"
    raw_text: str = ""

    @property
    def items_total(self) -> float:
        return round(sum(item.total for item in self.items), 2)
