"""Офлайн-демо пайплайна: сырой текст чека → чистые данные → БЖУ → остатки.

Запуск (из корня репозитория):

    python demo/run_demo.py

Нужен установленный пакет (`pip install -e ".[api]"`). Без сети, без ключей,
без `pdftotext`, без реального LLM: на вход идёт синтетический чек
`demo/sample_receipt.txt` (в том виде, в каком его отдаёт `pdftotext`), а
единственное место, где в боевом режиме нужен LLM — приведение названия товара
к каноническому, — подменено небольшим словарём (`StubNormalizer`).

БД создаётся в памяти и исчезает по завершении, ничего на диск не пишется.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nutriologist.api.foods import parse_foods
from nutriologist.db import get_connection
from nutriologist.inventory import ledger
from nutriologist.inventory.operations import eat, income_from_receipt, resolve_by_name
from nutriologist.products.nutrition import resolve_nutrition
from nutriologist.products.packaging import extract_packaging
from nutriologist.products.receipt_link import normalize_receipt_items
from nutriologist.receipts import ofdru
from nutriologist.receipts.storage import save_receipt

SAMPLE = Path(__file__).with_name("sample_receipt.txt")

# (подстрока в названии → каноническое имя, категория, это еда?, базовая единица)
_CATALOG = [
    ("гречнев", "гречка", "крупы/макароны", True, "g"),
    ("яйцо", "яйцо куриное", "молочное", True, "piece"),
    ("молоко", "молоко", "молочное", True, "ml"),
    ("филе куриное", "куриное филе", "мясо", True, "g"),
    ("пакет", "пакет", "непищевое", False, None),
]


class StubNormalizer:
    """Замена LLM для демо: словарь вместо вызова модели (тот же JSON-контракт)."""

    def generate_json(self, *, system: str, user: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        name = user.lower()
        for needle, canonical, category, is_food, unit in _CATALOG:
            if needle in name:
                return {
                    "canonical_name": canonical,
                    "category": category,
                    "is_food": is_food,
                    "canonical_unit": unit,
                    "net_amount": None,
                    "net_unit": None,
                }
        return {"canonical_name": user, "category": "прочее", "is_food": False,
                "canonical_unit": None, "net_amount": None, "net_unit": None}


def title(text: str) -> None:
    print(f"\n\033[1m── {text} ──\033[0m")


def main() -> None:
    conn = get_connection(":memory:")
    llm = StubNormalizer()

    title("1. Сырой текст чека (вход)")
    text = SAMPLE.read_text(encoding="utf-8")
    print("\n".join(text.splitlines()[:12]) + "\n  …")

    title("2. Детерминированный парсер (без LLM)")
    parsed = ofdru.parse(text)
    print(f"{parsed.store_name} · ФД {parsed.fd_number} · ФПД {parsed.fpd} · {parsed.purchased_at}")
    for it in parsed.items:
        pack = extract_packaging(it.raw_name)
        net = f"→ {pack.net_amount:g} {pack.net_unit}" if pack else ""
        print(f"  {it.raw_name:<40} {it.quantity:>6g} × {it.unit_price:>7.2f} = {it.total:>7.2f}  {net}")
    ok = abs(parsed.items_total - (parsed.total or 0)) < 0.01
    print(f"Σ позиций {parsed.items_total:.2f} ₽  vs  ИТОГ {parsed.total:.2f} ₽  →",
          "сошлось ✓" if ok else "РАСХОЖДЕНИЕ ✗")

    title("3. Сохранение и дедупликация по ФД/ФПД")
    first = save_receipt(conn, parsed)
    again = save_receipt(conn, parsed)
    rows = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    print(f"Первый импорт → чек #{first}; повторный → чек #{again}; строк в таблице: {rows}")

    title("4. Нормализация товаров и приход в «холодильник»")
    normalize_receipt_items(conn, first, llm)
    posted = income_from_receipt(conn, first)
    print(f"Позиций оприходовано: {posted} (непищевое отфильтровано)")
    for r in ledger.current(conn):
        print(f"  {r['canonical_name']:<16} {r['qty_estimate']:>7.0f} {r['canonical_unit']}   [{r['category']}]")

    title("5. БЖУ из справочника (без LLM)")
    for r in ledger.current(conn):
        product = resolve_by_name(conn, r["canonical_name"], llm)
        facts = resolve_nutrition(conn, product, llm=None)
        if facts:
            print(f"  {product.canonical_name:<16} {facts.kcal:>5.0f} ккал · Б {facts.protein:>4.1f} · "
                  f"Ж {facts.fat:>4.1f} · У {facts.carbs:>4.1f}  на 100 г  (источник: {facts.source})")

    title("6. Свободный ввод: «съел 200 г гречки и два яйца»")
    phrase = "съел 200 г гречки и два яйца"
    foods = parse_foods(phrase)
    items = [(resolve_by_name(conn, f.name, llm), f.amount_canonical) for f in foods]
    eat(conn, items=items, raw_text=phrase)
    kcal = protein = 0.0
    for (product, amount), f in zip(items, foods):
        facts = resolve_nutrition(conn, product, llm=None)  # те же цифры, что в шаге 5
        k = f.grams / 100
        kcal += facts.kcal * k
        protein += facts.protein * k
        print(f"  {f.name:<16} {amount:>5g} {f.canonical_unit:<5} {facts.kcal * k:>5.0f} ккал")
    print(f"Итого: {kcal:.0f} ккал, белка {protein:.1f} г")

    title("7. Остаток после ужина")
    for r in ledger.current(conn):
        print(f"  {r['canonical_name']:<16} {r['qty_estimate']:>7.0f} {r['canonical_unit']}")
    print()


if __name__ == "__main__":
    main()
