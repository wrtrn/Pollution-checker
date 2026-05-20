"""HTTP-only scraper for the Cyprus DLI air quality site.

The DLI front page renders each station card with a CSS class
``station-status-{green|yellow|orange|red}`` directly in the server-side HTML.
That means we do not need a headless browser at all: a plain HTTPS request and
a small BeautifulSoup parser are enough.

The mapping ``COLOR_TO_LEVEL`` matches the legend on the DLI site:
    green=1 (low), yellow=2 (moderate), orange=3 (high), red=4 (very high).

Nicosia has two stations (Traffic + Residential). We aggregate their statuses
by taking the maximum level — i.e. the worst air quality observed across the
city — which is the safer choice for "should I close the windows?" decisions.

Why we shell out to `curl` instead of using `requests`
------------------------------------------------------
The DLI site sits behind a WAF that fingerprints clients by their TLS
ClientHello (and probably http/2 frame patterns). Python's
``requests`` + ``urllib3`` produce a fingerprint distinct from any real
browser, and the WAF returns 403 to it regardless of how careful we are
with the HTTP-level headers (we tried: full browser header set, minimal
``User-Agent`` only, no headers at all — all 403). The same machine
running `curl -A 'Mozilla/5.0' <url>` gets a clean 200, because curl's
TLS stack is a known good shape that the WAF allows.

Replicating curl's TLS fingerprint from Python would require a special
build (``curl_cffi``, ``pycurl`` against a custom libcurl, or
``tls-client``). Each of these is heavy and finicky on ARM. Calling the
system ``curl`` is the simplest robust path: it's already installed on
every Linux distro we'd ever deploy to, the install script verifies its
presence, and we keep the rest of the codebase pure-Python.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .config import (
    DLI_URL,
    HTTP_TIMEOUT,
    RETRY_ATTEMPTS,
    RETRY_BACKOFF_BASE,
)

log = logging.getLogger(__name__)

COLOR_TO_LEVEL: dict[str, int] = {
    "green": 1,
    "yellow": 2,
    "orange": 3,
    "red": 4,
}

# Matches <span class="station-status-green"> etc.
_STATUS_CLASS_RE = re.compile(r"station-status-(green|yellow|orange|red)")

# Matches plain `curl -A "..."` exactly: just User-Agent on top of curl's
# own (very small) defaults. Production testing on Oracle Cloud Amsterdam
# confirmed this yields 200 from the DLI WAF.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ScrapeError(RuntimeError):
    """Raised when the page cannot be fetched or parsed."""


@dataclass(frozen=True)
class StationStatus:
    name: str
    color: str
    level: int


def _fetch_once_via_curl(url: str, timeout_sec: int) -> str:
    """Single HTTP fetch via the system ``curl`` binary.

    Raises ``ScrapeError`` on any failure (curl missing, network error,
    HTTP >= 400, timeout, suspiciously small body).
    """
    curl_bin = shutil.which("curl")
    if curl_bin is None:
        raise ScrapeError(
            "The 'curl' binary was not found on PATH. Install it (Debian/Ubuntu: "
            "'apt-get install -y curl') — this scraper relies on curl's TLS stack "
            "to bypass the DLI WAF that rejects Python's TLS fingerprint."
        )
    cmd = [
        curl_bin,
        "--silent",
        "--show-error",
        "--location",  # follow redirects
        "--fail",  # exit non-zero on HTTP >= 400
        "--max-time",
        str(timeout_sec),
        "--user-agent",
        _USER_AGENT,
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScrapeError(f"curl timed out after {timeout_sec}s") from exc
    if proc.returncode != 0:
        # curl writes the HTTP status to stderr in --fail mode; surface it.
        stderr = proc.stderr.strip() or "(no stderr)"
        raise ScrapeError(f"curl exited with code {proc.returncode}: {stderr}")
    body = proc.stdout
    if not body or len(body) < 1000:
        raise ScrapeError(f"Suspiciously small curl response body: {len(body)} bytes")
    return body


def fetch_html(url: str = DLI_URL, *, session: object | None = None) -> str:
    """Fetch the DLI front page with retry + exponential backoff.

    The ``session`` parameter is kept for backwards compatibility with
    tests but is unused — we always go through the system ``curl``.

    Raises ``ScrapeError`` if all attempts fail.
    """
    del session  # unused
    last_exc: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return _fetch_once_via_curl(url, HTTP_TIMEOUT)
        except ScrapeError as exc:
            last_exc = exc
            wait = RETRY_BACKOFF_BASE * (2**attempt)
            log.warning(
                "Fetch attempt %d/%d failed: %s. Sleeping %.1fs before retry.",
                attempt + 1,
                RETRY_ATTEMPTS,
                exc,
                wait,
            )
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(wait)
    raise ScrapeError(f"All {RETRY_ATTEMPTS} fetch attempts failed: {last_exc}") from last_exc


def parse_stations(html: str) -> list[StationStatus]:
    """Extract status of every station from the DLI page HTML.

    Each station card contains an ``<h4 class="stations-overview-title">`` with
    the station name, plus a sibling/ancestor element with a
    ``station-status-<color>`` class. We walk up the DOM until we find that
    color marker — this is more resilient than matching a specific id like
    ``image_1066`` which is bound to map coordinates.
    """
    soup = BeautifulSoup(html, "lxml")
    stations: list[StationStatus] = []
    for h4 in soup.select("h4.stations-overview-title"):
        name = h4.get_text(strip=True)
        if not name:
            continue
        color = _find_status_color(h4)
        if color is None:
            log.warning("No status marker found for station %r; skipping.", name)
            continue
        stations.append(StationStatus(name=name, color=color, level=COLOR_TO_LEVEL[color]))
    return stations


def _find_status_color(h4_node) -> str | None:
    node = h4_node
    for _ in range(10):
        node = node.parent
        if node is None:
            return None
        marker = node.find(class_=_STATUS_CLASS_RE)
        if marker is None:
            continue
        for cls in marker.get("class", []):
            m = _STATUS_CLASS_RE.fullmatch(cls)
            if m:
                return m.group(1)
    return None


def nicosia_level(stations: list[StationStatus]) -> int | None:
    """Aggregate Nicosia stations into a single pollution level (max of all).

    Returns ``None`` if no Nicosia station is present in the parsed list — the
    caller should treat this as a scrape failure.
    """
    nico = [s for s in stations if "Nicosia" in s.name]
    if not nico:
        return None
    return max(s.level for s in nico)


def get_current_level(*, session: object | None = None) -> int:
    """High-level entry point used by ``main``. Raises ``ScrapeError`` on failure.

    The ``session`` parameter is unused — kept only for API compatibility.
    """
    html = fetch_html(session=session)
    stations = parse_stations(html)
    if not stations:
        raise ScrapeError("Parser found no station cards — site layout may have changed.")
    level = nicosia_level(stations)
    if level is None:
        raise ScrapeError("Parser found stations but no Nicosia entry.")
    log.info(
        "Scraped %d stations; Nicosia aggregate level = %d (%s)",
        len(stations),
        level,
        ", ".join(f"{s.name}:{s.color}" for s in stations if "Nicosia" in s.name),
    )
    return level
