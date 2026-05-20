"""Telegram notifier with retry and a separate channel for error alerts."""

from __future__ import annotations

import logging
import time

import requests

from .config import (
    DOWN_THRESHOLD,
    RETRY_ATTEMPTS,
    RETRY_BACKOFF_BASE,
    Config,
)

log = logging.getLogger(__name__)

LEVEL_EMOJI = {1: "🟢", 2: "🟡", 3: "🟠", 4: "🔴"}
LEVEL_LABEL = {
    1: "Низкий",
    2: "Средний",
    3: "Высокий",
    4: "Очень высокий",
}
LEVEL_ADVICE = {
    1: "Воздух чистый.",
    2: "Без ограничений.",
    3: "Рекомендуется закрыть окна и ограничить пребывание на улице.",
    4: "Опасный уровень. Лучше оставаться дома, окна закрыты.",
}


class Notifier:
    """Wrapper around the Telegram Bot API with built-in retry."""

    API_BASE = "https://api.telegram.org"

    def __init__(self, config: Config, *, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    def send_main(self, text: str) -> None:
        self._send(self._config.channel_id, text)

    def send_error(self, text: str) -> None:
        self._send(self._config.error_channel_id, text)

    def _send(self, chat_id: str, text: str) -> None:
        if self._config.dry_run:
            log.info("[DRY_RUN] would send to %s: %s", chat_id, text)
            return
        url = f"{self.API_BASE}/bot{self._config.bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        last_exc: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                resp = self._session.post(url, json=payload, timeout=15)
                resp.raise_for_status()
                log.info("Telegram message sent to %s", chat_id)
                return
            except requests.RequestException as exc:
                last_exc = exc
                wait = RETRY_BACKOFF_BASE * (2**attempt)
                log.warning(
                    "Telegram send attempt %d/%d failed: %s. Sleeping %.1fs.",
                    attempt + 1,
                    RETRY_ATTEMPTS,
                    exc,
                    wait,
                )
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(wait)
        log.error("Failed to send Telegram message after %d attempts: %s", RETRY_ATTEMPTS, last_exc)
        # We deliberately swallow the exception: a failed Telegram delivery
        # should not crash the whole run, otherwise we'd lose the state update
        # and risk re-notifying on the next tick.


# ---------- Message builders (pure functions, easy to unit-test) ----------


def format_level_change(old: int | None, new: int) -> str:
    emoji = LEVEL_EMOJI[new]
    label = LEVEL_LABEL[new]
    advice = LEVEL_ADVICE[new]
    if old is None:
        head = f"{emoji} Уровень {new} ({label})"
    else:
        head = f"{emoji} Уровень {old} → {new} ({label})"
    return f"{head}\n{advice}"


def format_trend_update(old: int | None, new: int, arrow: str) -> str:
    """Periodic update sent on every tick while level >= 3."""
    emoji = LEVEL_EMOJI[new]
    label = LEVEL_LABEL[new]
    advice = LEVEL_ADVICE[new]
    if old is None or old == new:
        head = f"{emoji} Уровень {new} ({label}) {arrow}"
    else:
        head = f"{emoji} Уровень {old} → {new} ({label}) {arrow}"
    return f"{head}\n{advice}"


def format_site_down(consecutive_failures: int, last_error: str) -> str:

    return (
        f"🔴 Сайт DLI не отвечает уже {consecutive_failures} проверок подряд "
        f"(порог: {DOWN_THRESHOLD}).\nПоследняя ошибка: {last_error}"  # noqa: RUF001
    )


def format_site_up(level: int) -> str:
    emoji = LEVEL_EMOJI[level]
    return f"🟢 Сайт DLI снова отвечает. Текущий уровень: {emoji} {level} ({LEVEL_LABEL[level]})."
