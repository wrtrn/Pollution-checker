"""Persistent state stored as a single JSON file.

Schema (all fields optional, defaults handled in ``load``):
    {
      "last_level": 2,
      "recent_levels": [1, 2, 2, 3, 3],   // newest last, capped at TREND_WINDOW
      "consecutive_failures": 0,
      "down_alerted": false,                // we already sent the "site down" message
      "last_check_iso": "2026-05-20T18:50:00+00:00"
    }
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import TREND_WINDOW

log = logging.getLogger(__name__)


@dataclass
class State:
    last_level: int | None = None
    recent_levels: list[int] = field(default_factory=list)
    consecutive_failures: int = 0
    down_alerted: bool = False
    last_check_iso: str | None = None

    def record_level(self, level: int) -> None:
        self.last_level = level
        self.recent_levels.append(level)
        if len(self.recent_levels) > TREND_WINDOW:
            self.recent_levels = self.recent_levels[-TREND_WINDOW:]


def load(path: Path) -> State:
    if not path.exists():
        log.info("State file %s does not exist yet; starting fresh.", path)
        return State()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read state from %s (%s); starting fresh.", path, exc)
        return State()
    return State(
        last_level=data.get("last_level"),
        recent_levels=list(data.get("recent_levels", [])),
        consecutive_failures=int(data.get("consecutive_failures", 0)),
        down_alerted=bool(data.get("down_alerted", False)),
        last_check_iso=data.get("last_check_iso"),
    )


def save(state: State, path: Path) -> None:
    """Atomic write: temp file in the same dir, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        # If anything goes wrong, clean up the temp file so we don't leak.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
