"""Tiny Markdown helpers shared by the benchmark modules (no dependencies)."""

from __future__ import annotations

from collections.abc import Iterable


def md_table(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    """Render a GitHub-flavoured Markdown table. Cells are str()-ed as-is."""
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def pct(part: float, whole: float) -> str:
    """Percentage string, guarding division by zero."""
    return f"{(100 * part / whole):.0f}%" if whole else "—"


def money(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def bar(part: float, whole: float, width: int = 16) -> str:
    """Unicode progress bar — a dependency-free chart that renders anywhere."""
    frac = (part / whole) if whole else 0.0
    filled = round(max(0.0, min(1.0, frac)) * width)
    return "█" * filled + "░" * (width - filled)
