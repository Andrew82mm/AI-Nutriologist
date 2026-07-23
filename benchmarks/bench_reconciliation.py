"""Benchmark #2 — receipt parsing accuracy against a free ground truth.

Every receipt prints its own ИТОГ. For an in-store receipt a correct parse must
have Σ(product line totals) equal that printed total, so we compare `items_total`
to `total` — no labelling needed, the receipt validates itself.

Online orders are separated out: their ИТОГ also includes a service/delivery
charge (a nameless «1 X 90.99» line, plus «Сборка заказа») that isn't a grocery
product, so Σ(products) < ИТОГ by that amount — expected, not a parse defect.
The clean reconciliation signal is therefore measured on in-store receipts, with
online orders reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutriologist.receipts.parse import UnsupportedReceiptFormat, parse_receipt_pdf

from ._report import md_table, money, pct
from .corpus import receipt_pdfs

TOLERANCE = 0.01  # ₽ — a kopeck of rounding is fine

# Markers that a receipt is an online order (ИТОГ carries a service/delivery fee
# on top of the grocery line items).
_ONLINE_MARKERS = ("сборка заказа", "доставк", "самовывоз")


@dataclass
class ReconRow:
    label: str
    store: str
    fmt: str
    total: float | None
    items_total: float | None
    delta: float | None      # items_total − total (None if unparsed)
    n_items: int
    reconciled: bool
    online: bool = False     # ИТОГ includes a non-product service/delivery fee


@dataclass
class ReconResult:
    rows: list[ReconRow] = field(default_factory=list)
    tolerance: float = TOLERANCE

    @property
    def parsed(self) -> list[ReconRow]:
        return [r for r in self.rows if r.fmt != "needs_llm"]

    @property
    def in_store(self) -> list[ReconRow]:
        return [r for r in self.parsed if not r.online]

    @property
    def online(self) -> list[ReconRow]:
        return [r for r in self.parsed if r.online]

    @property
    def reconciled_in_store(self) -> list[ReconRow]:
        return [r for r in self.in_store if r.reconciled]

    @property
    def mismatches(self) -> list[ReconRow]:
        """In-store receipts that don't reconcile — the only real defects."""
        return [r for r in self.in_store if not r.reconciled]

    @property
    def mean_abs_delta_in_store(self) -> float | None:
        deltas = [abs(r.delta) for r in self.in_store if r.delta is not None]
        return round(sum(deltas) / len(deltas), 2) if deltas else None


def _short(name: str) -> str:
    """Trim the noisy Gmail export filename to something readable."""
    stem = name.removeprefix("Gmail - ").removeprefix("Gmail").removesuffix(".pdf")
    return stem.strip(" -.")[:40] or name


def run(tolerance: float = TOLERANCE) -> ReconResult:
    res = ReconResult(tolerance=tolerance)
    for pdf in receipt_pdfs():
        try:
            r = parse_receipt_pdf(pdf)
        except UnsupportedReceiptFormat:
            res.rows.append(ReconRow(_short(pdf.name), "—", "needs_llm", None, None, None, 0, False))
            continue
        it = r.items_total
        delta = round(it - r.total, 2) if r.total is not None else None
        reconciled = delta is not None and abs(delta) <= tolerance
        online = any(m in r.raw_text.lower() for m in _ONLINE_MARKERS)
        res.rows.append(
            ReconRow(
                label=_short(pdf.name),
                store=(r.store_name or "—"),
                fmt=r.source_format,
                total=r.total,
                items_total=it,
                delta=delta,
                n_items=len(r.items),
                reconciled=reconciled,
                online=online,
            )
        )
    return res


def _status(r: ReconRow) -> str:
    if r.fmt == "needs_llm":
        return "—"
    if r.reconciled:
        return "✓"
    return "≈ сбор/доставка" if r.online else "✗"


def render(res: ReconResult) -> str:
    needs_llm = len(res.rows) - len(res.parsed)
    ins = len(res.in_store)
    ok = len(res.reconciled_in_store)
    online = len(res.online)
    bad = len(res.mismatches)
    lines = [
        "## #2 · Сходимость парсинга чеков",
        "",
        f"Истина — печатный ИТОГ; метрика меряет корректность **детерминированного** "
        f"парсера (без LLM). На офлайн-чеках сошлось (±{res.tolerance:g} ₽): "
        f"**{ok}/{ins}** ({pct(ok, ins)}), средняя ошибка **{money(res.mean_abs_delta_in_store)} ₽**, "
        f"необъяснённых расхождений: **{bad}**. Онлайн-заказов: {online} — их ИТОГ "
        f"включает сборку/доставку (не товарные позиции), поэтому Σ позиций законно "
        f"меньше — это ожидаемо, не дефект. Ещё {needs_llm} чек(ов) — другой layout "
        f"(покрытие меряет #1).",
        "",
        md_table(
            ["Чек", "Сеть", "Тип", "Позиций", "ИТОГ", "Σ позиций", "Δ, ₽", "Статус"],
            [
                [
                    r.label, r.store,
                    ("онлайн" if r.online else "офлайн") if r.fmt != "needs_llm" else "—",
                    r.n_items, money(r.total), money(r.items_total), money(r.delta),
                    _status(r),
                ]
                for r in res.rows
            ],
        ),
        "",
        "На онлайн-заказах остаток соответствует строке сервисного сбора «1 × …» "
        "(доставка/сборка) без товарного имени — в инвентарь еды она не идёт. "
        "Поэтому чистый сигнал сходимости берём по офлайн-чекам.",
    ]
    return "\n".join(lines)


def main() -> None:
    print(render(run()))


if __name__ == "__main__":
    main()
