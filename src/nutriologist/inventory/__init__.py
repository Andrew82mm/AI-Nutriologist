"""Inventory as a signed ledger (итерация 3).

Public flows: automatic income from receipts, manual add/remove, eating, and
cooking a dish (which consumes ingredients and stocks the finished dish).
"""

from __future__ import annotations

from .cooking import cook_dish
from .ledger import balance, current, record
from .operations import (
    add_manual,
    eat,
    income_from_receipt,
    remove,
    resolve_by_name,
)

__all__ = [
    "add_manual",
    "balance",
    "cook_dish",
    "current",
    "eat",
    "income_from_receipt",
    "record",
    "remove",
    "resolve_by_name",
]
