"""ASGI entry point: `uvicorn patribot.api.main:app`, or `uv run patribot-api`."""

from __future__ import annotations

import os

from patribot.api.app import create_app

app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "patribot.api.main:app",
        host=os.environ.get("PATRIBOT_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("PATRIBOT_API_PORT", "8000")),
        reload=os.environ.get("PATRIBOT_API_RELOAD", "") == "1",
    )


if __name__ == "__main__":
    main()
