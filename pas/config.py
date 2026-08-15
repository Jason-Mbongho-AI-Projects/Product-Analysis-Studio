"""Central configuration for Product Analysis Studio.

All environment access happens here. No other module reads ``os.environ``
directly, so configuration stays testable and secrets never leak into the UI
layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("PAS_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "pas.sqlite3"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Task-based model routing (spec 38/39): cheap models for mechanical work,
# stronger models only where reasoning quality actually changes the output.
FAST_MODEL = os.getenv("PAS_FAST_MODEL", "openai/gpt-4.1-mini")
DEEP_MODEL = os.getenv("PAS_DEEP_MODEL", "openai/gpt-4.1-mini")

# Research fetching limits. Kept conservative on purpose - this product fetches
# third-party sites and must behave itself.
HTTP_TIMEOUT_SECONDS = float(os.getenv("PAS_HTTP_TIMEOUT", "12"))
HTTP_MAX_BYTES = int(os.getenv("PAS_HTTP_MAX_BYTES", str(2_000_000)))
HTTP_USER_AGENT = os.getenv(
    "PAS_USER_AGENT",
    "ProductAnalysisStudio/1.0 (+research bot; respects robots.txt)",
)
RESEARCH_MAX_PAGES_PER_DOMAIN = int(os.getenv("PAS_MAX_PAGES_PER_DOMAIN", "6"))

# Guard rail so a runaway analysis cannot silently burn budget (spec 38).
MAX_LLM_CALLS_PER_ANALYSIS = int(os.getenv("PAS_MAX_LLM_CALLS", "60"))


class ConfigError(RuntimeError):
    """Raised when required configuration is absent or malformed."""


@dataclass(frozen=True)
class AppConfig:
    api_key: str | None
    fast_model: str = FAST_MODEL
    deep_model: str = DEEP_MODEL
    db_path: Path = DB_PATH
    offline: bool = False
    allowed_schemes: tuple[str, ...] = field(default=("http", "https"))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigError(
                "OPENROUTER_API_KEY is missing. Add it to your .env file "
                "(see .env.example) and restart the app."
            )
        return self.api_key


def load_config() -> AppConfig:
    """Build the active configuration from the environment."""
    return AppConfig(
        api_key=os.getenv("OPENROUTER_API_KEY") or None,
        offline=os.getenv("PAS_OFFLINE", "").lower() in {"1", "true", "yes"},
    )


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
