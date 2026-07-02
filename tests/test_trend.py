from __future__ import annotations

import pytest

from pollution_checker.trend import (
    ARROW_DOWN,
    ARROW_FLAT,
    ARROW_UP,
    NotifyKind,
    decide,
)

# --- Safe band (1, 2): notify only on real changes, suppress 1↔2 jitter ---


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (1, 1),
        (2, 2),
        (1, 2),  # jitter, suppressed
        (2, 1),  # jitter, suppressed
    ],
)
def test_safe_band_no_notify(old: int, new: int) -> None:
    assert decide(old, new).kind is NotifyKind.NONE


def test_first_run_in_safe_band_does_notify() -> None:
    # First run (old=None) -> level 1: not interesting enough on its own.
    # We treat it as a "level change from unknown", which is informative.
    d = decide(None, 1)
    assert d.kind is NotifyKind.LEVEL_CHANGE


# --- Bad band (>= 3): every check produces an update with arrow ---


def test_bad_band_first_run_flat_arrow() -> None:
    d = decide(None, 3)
    assert d.kind is NotifyKind.TREND_UPDATE
    assert d.arrow == ARROW_FLAT


def test_bad_band_same_level_no_notify() -> None:
    d = decide(3, 3)
    assert d.kind is NotifyKind.NONE


def test_bad_band_rising() -> None:
    d = decide(3, 4)
    assert d.kind is NotifyKind.TREND_UPDATE
    assert d.arrow == ARROW_UP


def test_bad_band_falling_within_bad() -> None:
    d = decide(4, 3)
    assert d.kind is NotifyKind.TREND_UPDATE
    assert d.arrow == ARROW_DOWN


def test_entering_bad_band_from_safe_is_trend_update() -> None:
    # Going 2 -> 3 should switch us into trend-update mode immediately.
    d = decide(2, 3)
    assert d.kind is NotifyKind.TREND_UPDATE
    assert d.arrow == ARROW_UP


# --- Recovery: leaving the bad band ---


def test_leaving_bad_band_is_level_change() -> None:
    # 3 -> 2: good news, send a level-change message (not a trend update).
    d = decide(3, 2)
    assert d.kind is NotifyKind.LEVEL_CHANGE


def test_leaving_bad_band_to_low() -> None:
    d = decide(4, 1)
    assert d.kind is NotifyKind.LEVEL_CHANGE
