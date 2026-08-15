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

# Semantic retrieval (spec 40). Embeddings are cached by content hash, so the
# cost is paid once per claim rather than per question.
EMBEDDING_MODEL = os.getenv("PAS_EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDINGS_ENABLED = os.getenv("PAS_EMBEDDINGS", "true").lower() in {"1", "true", "yes", "on"}

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

# In-process monitor scheduler (spec 33). Off by default: it spends money on a
# timer, which should always be a deliberate choice rather than a side effect of
# leaving the app running.
SCHEDULER_ENABLED = os.getenv("PAS_SCHEDULER", "").lower() in {"1", "true", "yes", "on"}
SCHEDULER_TICK_SECONDS = int(os.getenv("PAS_SCHEDULER_TICK", "300"))


# Authentication (spec 41).
#
# Defaults to OFF so local development is unobstructed. This is a deliberate
# convenience, not an oversight - but it means an unauthenticated deployment is
# one missing env var away, so the UI shows a permanent banner while it is off
# and `network_exposure_warning()` escalates when the server is also reachable
# from outside this machine.
AUTH_ENABLED = os.getenv("PAS_AUTH_ENABLED", "").lower() in {"1", "true", "yes", "on"}

# Role granted to accounts after the first. The first account always becomes
# the workspace owner.
DEFAULT_MEMBER_ROLE = os.getenv("PAS_DEFAULT_ROLE", "viewer")

# When auth is enabled, whether strangers may create their own accounts.
ALLOW_SELF_SIGNUP = os.getenv("PAS_ALLOW_SIGNUP", "true").lower() in {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    """Raised when required configuration is absent or malformed."""


@dataclass(frozen=True)
class AppConfig:
    api_key: str | None
    fast_model: str = FAST_MODEL
    deep_model: str = DEEP_MODEL
    db_path: Path = DB_PATH
    offline: bool = False
    auth_enabled: bool = AUTH_ENABLED
    allow_signup: bool = ALLOW_SELF_SIGNUP
    scheduler_enabled: bool = SCHEDULER_ENABLED
    embeddings_enabled: bool = EMBEDDINGS_ENABLED
    embedding_model: str = EMBEDDING_MODEL
    default_role: str = DEFAULT_MEMBER_ROLE
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
        auth_enabled=AUTH_ENABLED,
        allow_signup=ALLOW_SELF_SIGNUP,
        scheduler_enabled=SCHEDULER_ENABLED,
        embeddings_enabled=EMBEDDINGS_ENABLED,
        embedding_model=EMBEDDING_MODEL,
        default_role=DEFAULT_MEMBER_ROLE,
    )


def server_address() -> str:
    """The address Streamlit is bound to, if it can be determined."""
    address = os.getenv("STREAMLIT_SERVER_ADDRESS", "")
    if address:
        return address
    try:
        from streamlit import config as st_config

        return st_config.get_option("server.address") or ""
    except Exception:
        return ""


def network_exposure_warning(auth_enabled: bool) -> str | None:
    """Return a warning when an unauthenticated app is reachable off-machine.

    Running open on localhost while developing is reasonable. Running open on
    ``0.0.0.0`` means anyone who can route to the host has full access to every
    analysis and the configured API key's spend.
    """
    if auth_enabled:
        return None

    address = server_address().strip()
    loopback = {"", "localhost", "127.0.0.1", "::1"}
    if address.lower() in loopback:
        return None

    return (
        f"Authentication is disabled and the server is bound to '{address}', "
        "which is reachable beyond this machine. Anyone who can reach it has "
        "full access to your analyses and can spend against your API key. "
        "Set PAS_AUTH_ENABLED=true, or bind to localhost."
    )


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
