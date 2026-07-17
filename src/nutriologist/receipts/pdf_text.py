from __future__ import annotations

import subprocess
from pathlib import Path


class PdfExtractionError(Exception):
    """Raised when pdftotext can't be run or fails on a given PDF."""


def extract_text(pdf_path: Path | str) -> str:
    """Extract the text layer of a PDF via poppler's pdftotext."""
    try:
        result = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PdfExtractionError(
            "Команда 'pdftotext' не найдена. Установите poppler-utils "
            "(например: sudo apt install poppler-utils)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else "код возврата " + str(exc.returncode)
        raise PdfExtractionError(f"pdftotext не смог обработать '{pdf_path}': {detail}") from exc

    return result.stdout
