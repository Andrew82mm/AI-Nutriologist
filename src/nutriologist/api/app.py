"""FastAPI application factory and shared plumbing.

Design notes
------------
- One SQLite connection per request (`db_conn` dependency). `get_connection`
  is idempotent (schema applied with IF NOT EXISTS), and SQLite connects
  cheaply, so there's no pool to manage for a single-user local app.
- Routers live in sibling modules (`inventory`, ...) and are included here.
- CORS is wide open by default so the Vite dev server (a different origin,
  usually http://localhost:5173) can call the API during development. In a
  packaged build the frontend is served from the same origin, so this only
  matters for `dev`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..db import get_connection


def db_conn() -> Iterator[sqlite3.Connection]:
    """Request-scoped SQLite connection dependency.

    Opens the default database (``$NUTRIOLOGIST_DB_PATH`` or
    ``data/nutriologist.db``), yields it to the endpoint, and always closes it.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_optional_llm():
    """An LLM client if one is configured in `.env`, else None.

    Shared by every endpoint that treats the LLM as an optional enhancement
    (chat parsing, receipt normalization, the planner): a missing/broken config
    degrades to the deterministic offline path instead of erroring.
    """
    try:
        from ..llm.config import load_llm_client_from_env

        return load_llm_client_from_env()
    except Exception:
        return None


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI-Nutriologist API",
        version="0.1.0",
        summary="HTTP-слой над ядром nutriologist для веб-интерфейса.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    from . import actions, diary, inventory, planner, profile, receipts_import, stats

    app.include_router(inventory.router)
    app.include_router(diary.router)
    app.include_router(profile.router)
    app.include_router(actions.router)
    app.include_router(receipts_import.router)
    app.include_router(planner.router)
    app.include_router(stats.router)

    return app


app = create_app()
