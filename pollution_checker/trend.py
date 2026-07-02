"""Pure decision logic: when to notify and what arrow to show.

Kept dependency-free on purpose so it can be tested in isolation without
touching state files, HTTP, or Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

ARROW_UP = "↑"
ARROW_DOWN = "↓"
ARROW_FLAT = "→"


class NotifyKind(StrEnum):
    NONE = "none"
    LEVEL_CHANGE = "level_change"
    TREND_UPDATE = "trend_update"


@dataclass(frozen=True)
class Decision:
    kind: NotifyKind
    arrow: str | None = None  # only set for TREND_UPDATE


def decide(old_level: int | None, new_level: int) -> Decision:
    """Decide whether and how to notify, given previous and current levels.

    Rules:
      * We notify only on level changes.
      * Transitions strictly between 1 and 2 are noise (windows can stay open
        either way), so we suppress them.
    """
    if old_level == new_level:
        return Decision(kind=NotifyKind.NONE)

    # Suppress jitter inside the "safe" band {1, 2}.
    if old_level is not None and {old_level, new_level} == {1, 2}:
        return Decision(kind=NotifyKind.NONE)

    if new_level >= 3:
        arrow = _arrow(old_level, new_level)
        return Decision(kind=NotifyKind.TREND_UPDATE, arrow=arrow)

    # Level dropped from "bad" (>=3) to "safe" (<=2): this is good news, notify.
    return Decision(kind=NotifyKind.LEVEL_CHANGE)


def _arrow(old_level: int | None, new_level: int) -> str:
    if old_level is None or old_level == new_level:
        return ARROW_FLAT
    return ARROW_UP if new_level > old_level else ARROW_DOWN
