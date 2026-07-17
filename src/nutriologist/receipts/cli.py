"""Manual test-drive of the receipt parser.

Usage:
    python -m nutriologist.receipts.cli path/to/receipt.pdf [more.pdf ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from .parse import UnsupportedReceiptFormat, parse_receipt_pdf


def _print_receipt(pdf_path: Path) -> None:
    print("=" * 80)
    print(pdf_path)
    try:
        receipt = parse_receipt_pdf(pdf_path)
    except UnsupportedReceiptFormat:
        print("  (не распознан ни один известный формат — нужен LLM fallback)")
        return

    print(
        f"  магазин: {receipt.store_name} | ФД: {receipt.fd_number} | ФПД: {receipt.fpd} "
        f"| дата: {receipt.purchased_at} | ИТОГ: {receipt.total}"
    )
    print(f"  сумма позиций: {receipt.items_total} ({len(receipt.items)} шт.)")
    if receipt.items_total != receipt.total:
        print("  !! сумма позиций не совпадает с ИТОГ чека")

    for item in receipt.items:
        vat = f"НДС {item.vat_rate}%={item.vat_amount}" if item.vat_rate is not None else "НДС ?"
        print(
            f"    {item.quantity:>8g} x {item.unit_price:>9.2f} = {item.total:>9.2f}  "
            f"[{item.unit or '?'}]  {vat}  {item.raw_name}"
        )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1

    for arg in argv:
        _print_receipt(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
