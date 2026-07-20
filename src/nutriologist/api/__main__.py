"""Run the API with uvicorn:  ``python -m nutriologist.api``.

Host/port/reload come from env so it stays config, not code:
    NUTRIOLOGIST_API_HOST (default 127.0.0.1)
    NUTRIOLOGIST_API_PORT (default 8000)
    NUTRIOLOGIST_API_RELOAD=1 to enable autoreload (dev).
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    reload = os.environ.get("NUTRIOLOGIST_API_RELOAD", "") not in ("", "0", "false")
    uvicorn.run(
        "nutriologist.api.app:app",
        host=os.environ.get("NUTRIOLOGIST_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("NUTRIOLOGIST_API_PORT", "8000")),
        reload=reload,
    )


if __name__ == "__main__":
    main()
