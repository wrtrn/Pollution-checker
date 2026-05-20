from __future__ import annotations

from pathlib import Path

from pollution_checker import state as state_mod
from pollution_checker.config import TREND_WINDOW


def test_load_missing_file_returns_default(tmp_path: Path) -> None:
    s = state_mod.load(tmp_path / "missing.json")
    assert s.last_level is None
    assert s.recent_levels == []
    assert s.consecutive_failures == 0
    assert s.down_alerted is False


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    s = state_mod.State(
        last_level=3,
        recent_levels=[2, 3, 3],
        consecutive_failures=0,
        down_alerted=False,
        last_check_iso="2026-05-20T18:50:00+00:00",
    )
    state_mod.save(s, p)

    loaded = state_mod.load(p)
    assert loaded == s


def test_record_level_caps_recent_window() -> None:
    s = state_mod.State()
    sequence = [1, 1, 2, 3, 3, 4, 4, 3]
    for level in sequence:
        s.record_level(level)
    assert s.last_level == sequence[-1]
    assert len(s.recent_levels) == TREND_WINDOW
    assert s.recent_levels == sequence[-TREND_WINDOW:]


def test_corrupt_state_file_recovers_gracefully(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text("not json", encoding="utf-8")
    s = state_mod.load(p)
    assert s.last_level is None  # back to defaults instead of crashing
