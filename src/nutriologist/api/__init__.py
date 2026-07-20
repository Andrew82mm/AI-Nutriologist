"""HTTP API layer over the nutriologist core.

A thin FastAPI application that exposes the existing domain modules
(`inventory`, `products`, `llm`, ...) over JSON so a web frontend can drive
them. The API owns no business logic of its own — every endpoint is a small
adapter that opens a DB connection, calls into `nutriologist.*`, and shapes the
result for the client.

Run it with:  ``python -m nutriologist.api``  (see ``__main__``).
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
