"""Light tests for the message builder pure functions."""

from __future__ import annotations

from pollution_checker.notifier import (
    format_level_change,
    format_site_down,
    format_site_up,
    format_trend_update,
)
from pollution_checker.trend import ARROW_FLAT, ARROW_UP


def test_format_level_change_first_run() -> None:
    msg = format_level_change(None, 2)
    assert "Уровень 2" in msg
    assert "Средний" in msg
    assert "🟡" in msg


def test_format_level_change_with_old() -> None:
    msg = format_level_change(3, 2)
    assert "3 → 2" in msg
    assert "🟡" in msg


def test_format_trend_update_includes_arrow() -> None:
    msg = format_trend_update(3, 4, ARROW_UP)
    assert "↑" in msg
    assert "3 → 4" in msg
    assert "🔴" in msg


def test_format_trend_update_flat_no_change() -> None:
    msg = format_trend_update(3, 3, ARROW_FLAT)
    assert "→" in msg
    assert "🟠" in msg


def test_format_site_down_mentions_count() -> None:
    msg = format_site_down(5, "timeout")
    assert "5" in msg
    assert "timeout" in msg


def test_format_site_up_mentions_level() -> None:
    msg = format_site_up(2)
    assert "Средний" in msg or "2" in msg
