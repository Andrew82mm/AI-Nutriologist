"""Manual test-drive of the receipt parser.

Usage:
    python -m nutriologist.receipts.cli path/to/receipt.pdf [more.pdf ...]
    python -m nutriologist.receipts.cli --llm path/to/receipt.pdf

Without --llm, receipts in an unrecognized format are reported as such
instead of falling back (no LLM calls happen unless you opt in). With --llm,
the provider is whatever is configured in .env (see .env.example) — this
CLI has no knowledge of which vendor that is.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..llm.client import StructuredLLMClient
from ..llm.config import LLMConfigError, load_llm_client_from_env
from .parse import UnsupportedReceiptFormat, parse_receipt_pdf


def _print_receipt(pdf_path: Path, llm: StructuredLLMClient | None) -> None:
    print("=" * 80)
    print(pdf_path)
    try:
        receipt = parse_receipt_pdf(pdf_path, llm=llm)
    except UnsupportedReceiptFormat:
        print("  (не распознан ни один известный формат — запусти с --llm)")
        return

    print(
        f"  формат: {receipt.source_format} | магазин: {receipt.store_name} | "
        f"ФД: {receipt.fd_number} | ФПД: {receipt.fpd} | дата: {receipt.purchased_at} "
        f"| ИТОГ: {receipt.total}"
    )
    print(f"  сумма позиций: {receipt.items_total} ({len(receipt.items)} шт.)")
    if receipt.total is not None and receipt.items_total != receipt.total:
        print("  !! сумма позиций не совпадает с ИТОГ чека")

    for item in receipt.items:
        vat = f"НДС {item.vat_rate}%={item.vat_amount}" if item.vat_rate is not None else "НДС ?"
        print(
            f"    {item.quantity:>8g} x {item.unit_price:>9.2f} = {item.total:>9.2f}  "
            f"[{item.unit or '?'}]  {vat}  {item.raw_name}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_paths", nargs="+", type=Path)
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable the LLM fallback parser (opt-in; costs money/network). "
        "Provider comes from .env — see .env.example.",
    )
    args = parser.parse_args(argv)

    if args.llm:
        try:
            llm = load_llm_client_from_env()
        except (LLMConfigError, ImportError) as exc:
            print(f"LLM configuration error: {exc}")
            return 1
    else:
        llm = None

    for pdf_path in args.pdf_paths:
        _print_receipt(pdf_path, llm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
