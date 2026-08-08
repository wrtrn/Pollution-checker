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


def get_pollutant_thresholds(name: str) -> str | None:
    mapping = {
        "PM₁₀": "🟢 0-50 | 🟡 50-100 | 🟠 100-200 | 🔴 >200",
        "PM₂.₅": "🟢 0-25 | 🟡 25-50 | 🟠 50-100 | 🔴 >100",
        "O₃": "🟢 0-100 | 🟡 100-140 | 🟠 140-180 | 🔴 >180",
        "NO₂": "🟢 0-100 | 🟡 100-150 | 🟠 150-200 | 🔴 >200",
        "SO₂": "🟢 0-150 | 🟡 150-250 | 🟠 250-350 | 🔴 >350",
        "CO": "🟢 0-7000 | 🟡 7000-15000 | 🟠 15000-20000 | 🔴 >20000",
        "Benzene": "🟢 0-5 | 🟡 5-10 | 🟠 10-15 | 🔴 >15",
        "C₆H₆": "🟢 0-5 | 🟡 5-10 | 🟠 10-15 | 🔴 >15",
    }
    return mapping.get(name)


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


def format_level_change(old: int | None, new: int, worst_pollutants: list | None = None) -> str:
    emoji = LEVEL_EMOJI[new]
    label = LEVEL_LABEL[new]
    advice = LEVEL_ADVICE[new]
    if old is None:
        head = f"{emoji} Уровень {new} ({label})"
    else:
        head = f"{emoji} Уровень {old} → {new} ({label})"
        
    if new >= 3 and worst_pollutants:
        lines = ["\nПревышены параметры:"]
        seen = set()
        for p in worst_pollutants:
            if p.name not in seen:
                lines.append(f"• {p.name}: {p.value} (Уровень {p.level})")
                thresholds = get_pollutant_thresholds(p.name)
                if thresholds:
                    lines.append(f"  Пороги: {thresholds}")
                seen.add(p.name)
        advice += "\n" + "\n".join(lines)
        
    return f"{head}\n{advice}"


def format_trend_update(old: int | None, new: int, arrow: str, worst_pollutants: list | None = None) -> str:
    """Periodic update sent on every tick while level >= 3."""
    emoji = LEVEL_EMOJI[new]
    label = LEVEL_LABEL[new]
    advice = LEVEL_ADVICE[new]
    if old is None or old == new:
        head = f"{emoji} Уровень {new} ({label}) {arrow}"
    else:
        head = f"{emoji} Уровень {old} → {new} ({label}) {arrow}"
        
    if new >= 3 and worst_pollutants:
        lines = ["\nПревышены параметры:"]
        seen = set()
        for p in worst_pollutants:
            if p.name not in seen:
                lines.append(f"• {p.name}: {p.value} (Уровень {p.level})")
                thresholds = get_pollutant_thresholds(p.name)
                if thresholds:
                    lines.append(f"  Пороги: {thresholds}")
                seen.add(p.name)
        advice += "\n" + "\n".join(lines)
        
    return f"{head}\n{advice}"


def format_site_down(consecutive_failures: int, last_error: str) -> str:

    return (
        f"🔴 Сайт DLI не отвечает уже {consecutive_failures} проверок подряд "
        f"(порог: {DOWN_THRESHOLD}).\nПоследняя ошибка: {last_error}"  # noqa: RUF001
    )


def format_site_up(level: int) -> str:
    emoji = LEVEL_EMOJI[level]
    return f"🟢 Сайт DLI снова отвечает. Текущий уровень: {emoji} {level} ({LEVEL_LABEL[level]})."
