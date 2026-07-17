from __future__ import annotations

import subprocess
from pathlib import Path


def extract_text(pdf_path: Path | str) -> str:
    """Extract the text layer of a PDF via poppler's pdftotext."""
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout
