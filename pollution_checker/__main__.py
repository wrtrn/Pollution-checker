"""Entry point: python -m pollution_checker

Designed to be invoked once per scheduled run (systemd timer / cron). The
process performs a single check, updates state, optionally sends Telegram
messages, and exits. State across runs is persisted in a JSON file pointed to
by ``STATE_FILE`` env var.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

from . import state as state_mod
from .config import DOWN_THRESHOLD, Config
from .logging_setup import setup_logging
from .notifier import (
    Notifier,
    format_level_change,
    format_site_down,
    format_site_up,
    format_trend_update,
)
from .scraper import ScrapeError, get_current_level
from .trend import NotifyKind, decide

log = logging.getLogger("pollution_checker.main")


def run_once(config: Config) -> int:
    """One scheduled check. Returns exit code (0 ok, 1 scrape failed)."""
    state = state_mod.load(config.state_file)
    notifier = Notifier(config)

    try:
        level = get_current_level()
    except ScrapeError as exc:
        return _handle_failure(config, state, notifier, exc)

    return _handle_success(config, state, notifier, level)


def _handle_failure(config, state, notifier, exc: ScrapeError) -> int:
    state.consecutive_failures += 1
    state.last_check_iso = _now_iso()
    log.error(
        "Scrape failed (%d consecutive): %s",
        state.consecutive_failures,
        exc,
    )

    if state.consecutive_failures >= DOWN_THRESHOLD and not state.down_alerted:
        notifier.send_error(format_site_down(state.consecutive_failures, str(exc)))
        state.down_alerted = True
    state_mod.save(state, config.state_file)
    return 1


def _handle_success(config, state, notifier, level: int) -> int:
    old_level = state.last_level

    # Recovery: notify in error channel if we previously alerted about an outage.
    if state.down_alerted:
        notifier.send_error(format_site_up(level))
        state.down_alerted = False

    decision = decide(old_level, level)
    if decision.kind is NotifyKind.LEVEL_CHANGE:
        notifier.send_main(format_level_change(old_level, level))
    elif decision.kind is NotifyKind.TREND_UPDATE:
        assert decision.arrow is not None
        notifier.send_main(format_trend_update(old_level, level, decision.arrow))
    else:
        log.info("Level %s, no notification needed (decision=%s).", level, decision.kind.value)

    state.record_level(level)
    state.consecutive_failures = 0
    state.last_check_iso = _now_iso()
    state_mod.save(state, config.state_file)
    return 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def main() -> int:
    try:
        config = Config.from_env()
    except RuntimeError as exc:
        # Logging not yet configured — print to stderr and bail out.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    setup_logging(config.log_level)
    
    ret = run_once(config)
    
    if config.healthcheck_url and not config.dry_run:
        import requests
        try:
            requests.get(config.healthcheck_url, timeout=10)
        except Exception as exc:
            log.warning("Failed to ping healthcheck: %s", exc)
            
    return ret


if __name__ == "__main__":
    raise SystemExit(main())
