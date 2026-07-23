"""Benchmark #2 — receipt parsing accuracy against a free ground truth.

Every receipt prints its own ИТОГ. A correct parse must have Σ(line totals) equal
that printed total. So for each receipt we compare `items_total` to `total` — no
manual labelling needed, the receipt validates itself.

Reported: share of receipts that reconcile within a kopeck, the mean/worst
absolute gap, and a per-chain breakdown (different chains = different layouts,
so a systematic gap points at a format the parser handles imperfectly).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutriologist.receipts.parse import UnsupportedReceiptFormat, parse_receipt_pdf

from ._report import md_table, money, pct
from .corpus import receipt_pdfs

TOLERANCE = 0.01  # ₽ — a kopeck of rounding is fine


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


@dataclass
class ReconResult:
    rows: list[ReconRow] = field(default_factory=list)
    tolerance: float = TOLERANCE

    @property
    def parsed(self) -> list[ReconRow]:
        return [r for r in self.rows if r.fmt != "needs_llm"]

    @property
    def reconciled(self) -> list[ReconRow]:
        return [r for r in self.rows if r.reconciled]

    @property
    def mean_abs_delta(self) -> float | None:
        deltas = [abs(r.delta) for r in self.parsed if r.delta is not None]
        return round(sum(deltas) / len(deltas), 2) if deltas else None

    @property
    def worst(self) -> ReconRow | None:
        cand = [r for r in self.parsed if r.delta is not None]
        return max(cand, key=lambda r: abs(r.delta)) if cand else None


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
            )
        )
    return res


def render(res: ReconResult) -> str:
    n = len(res.rows)
    parsed = len(res.parsed)
    needs_llm = n - parsed
    ok = len(res.reconciled)
    lines = [
        "## #2 · Сходимость парсинга чеков",
        "",
        f"Истина — печатный ИТОГ каждого чека; метрика меряет корректность "
        f"**детерминированного** парсера (воспроизводимо, без LLM). Сошлось "
        f"(±{res.tolerance:g} ₽): **{ok}/{parsed}** распознанных чеков "
        f"({pct(ok, parsed)}). Средняя ошибка по ним: **{money(res.mean_abs_delta)} ₽**. "
        f"Ещё {needs_llm} чек(ов) — другой layout (не формат OFD.RU), их покрытие "
        f"меряет бенчмарк #1.",
        "",
        md_table(
            ["Чек", "Сеть", "Позиций", "ИТОГ", "Σ позиций", "Δ, ₽", "Сошлось"],
            [
                [
                    r.label, r.store, r.n_items,
                    money(r.total), money(r.items_total), money(r.delta),
                    "✓" if r.reconciled else ("—" if r.fmt == "needs_llm" else "✗"),
                ]
                for r in res.rows
            ],
        ),
    ]
    worst = res.worst
    if worst and not worst.reconciled and worst.delta is not None:
        lines += [
            "",
            f"Худший разрыв — «{worst.label}» ({worst.store}): Δ {money(worst.delta)} ₽. "
            "Систематический разрыв на одной сети указывает на недоучтённую строку "
            "формата (скидка/подарок/сбор) — кандидат на доработку парсера.",
        ]
    return "\n".join(lines)


def main() -> None:
    print(render(run()))


if __name__ == "__main__":
    main()
