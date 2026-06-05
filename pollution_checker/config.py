"""Runtime configuration loaded from environment variables.

All secrets and tunables live here. The rest of the codebase only imports
``Config`` and never reads ``os.environ`` directly. Local development can
populate variables from a ``.env`` file (see ``_load_dotenv``); production
loads them through systemd's ``EnvironmentFile=``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# How many consecutive failed scrapes trigger a "site is down" alert.
DOWN_THRESHOLD = 10

# How many recent levels we keep in state for trend arrow computation.
TREND_WINDOW = 5

# Source URL of the DLI air quality page.
DLI_URL = "https://www.airquality.dli.mlsi.gov.cy/"

# HTTP timeout for fetching the DLI page, in seconds.
HTTP_TIMEOUT = 30

# Retry configuration shared by HTTP and Telegram clients.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1.0  # seconds; delay = base * 2**attempt


@dataclass(frozen=True)
class Config:
    bot_token: str
    channel_id: str
    error_channel_id: str
    state_file: Path
    dry_run: bool
    log_level: str
    healthcheck_url: str | None

    @classmethod
    def from_env(cls) -> Config:
        _load_dotenv()
        bot_token = _require("BOT_TOKEN")
        channel_id = _require("CHANNEL_ID")
        error_channel_id = _require("ERROR_CHANNEL_ID")
        state_file = Path(os.environ.get("STATE_FILE", "./pollution_state.json")).expanduser()
        dry_run = os.environ.get("DRY_RUN", "0").strip() in {"1", "true", "TRUE", "yes"}
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        healthcheck_url = os.environ.get("HEALTHCHECK_URL", "").strip() or None
        return cls(
            bot_token=bot_token,
            channel_id=channel_id,
            error_channel_id=error_channel_id,
            state_file=state_file,
            dry_run=dry_run,
            log_level=log_level,
            healthcheck_url=healthcheck_url,
        )


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            f"See .env.example for the full list."
        )
    return value


def _load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Minimal .env loader so we don't pull in python-dotenv just for this.

    Lines like ``KEY=VALUE`` are loaded into ``os.environ`` unless the variable
    is already defined (real env always wins over .env). Quoted values and
    blank/comment lines are handled. Anything fancier is intentionally out of
    scope.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
