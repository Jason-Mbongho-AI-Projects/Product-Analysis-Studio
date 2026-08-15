"""Run the HTTP API: ``python -m pas.api``.

Refuses to start unless ``PAS_API_ENABLED=true``, so it cannot be launched by
accident, and binds to loopback by default.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.getenv("PAS_API_ENABLED", "").lower() not in {"1", "true", "yes", "on"}:
        print(
            "The API is disabled. Set PAS_API_ENABLED=true to start it.\n"
            "Issue a key first from the Account -> API keys tab in the app.",
            file=sys.stderr,
        )
        return 1

    import uvicorn

    host = os.getenv("PAS_API_HOST", "127.0.0.1")
    port = int(os.getenv("PAS_API_PORT", "8000"))

    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"WARNING: binding to {host} exposes the API beyond this machine. "
            "Ensure keys are scoped and rate limits are appropriate.",
            file=sys.stderr,
        )

    uvicorn.run("pas.api.app:app", host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
