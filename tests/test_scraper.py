"""Parser tests use a captured snapshot of the live DLI page.

Snapshot location: tests/fixtures/dli_sample.html. To refresh it:
    curl -A "Mozilla/5.0" https://www.airquality.dli.mlsi.gov.cy/ \
        -o tests/fixtures/dli_sample.html
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pollution_checker.scraper import (
    COLOR_TO_LEVEL,
    nicosia_level,
    parse_stations,
)

FIXTURE = Path(__file__).parent / "fixtures" / "dli_sample.html"


@pytest.fixture
def sample_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_finds_all_known_stations(sample_html: str) -> None:
    stations = parse_stations(sample_html)
    names = {s.name for s in stations}
    # Two Nicosia stations are what we care about.
    assert "Nicosia - Traffic Station" in names
    assert "Nicosia - Residential Station" in names
    # Sanity: 11 station cards in the snapshot.
    assert len(stations) >= 5


def test_each_station_has_known_color(sample_html: str) -> None:
    stations = parse_stations(sample_html)
    for s in stations:
        assert s.color in COLOR_TO_LEVEL, f"Unknown color {s.color!r} for {s.name}"
        assert s.level == COLOR_TO_LEVEL[s.color]


def test_nicosia_level_is_max_of_two_stations(sample_html: str) -> None:
    stations = parse_stations(sample_html)
    nico_stations = [s for s in stations if "Nicosia" in s.name]
    assert nico_stations, "Snapshot must contain Nicosia"
    expected = max(s.level for s in nico_stations)
    assert nicosia_level(stations) == expected


def test_nicosia_level_returns_none_when_absent() -> None:
    assert nicosia_level([]) is None
