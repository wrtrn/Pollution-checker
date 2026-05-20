# Pollution Checker

Telegram bot that watches the [Cyprus DLI air quality](https://www.airquality.dli.mlsi.gov.cy/) page for Nicosia and notifies a Telegram channel when the pollution level changes — with a separate "trend mode" while air quality is bad.

The whole bot is a single Python entry point designed to be invoked once per scheduled run by `systemd timer` (or cron). State between runs lives in a small JSON file.

## How notifications work

Pollution levels follow the DLI legend: **1 (green)** — Low, **2 (yellow)** — Moderate, **3 (orange)** — High, **4 (red)** — Very high. Nicosia has two stations (Traffic + Residential); the bot uses the worst of the two as the city's level — the safer choice for "should I close the windows?" decisions.

Two Telegram channels are used:

- **Main channel (`CHANNEL_ID`)** — pollution level updates.
  - For levels **1–2**: a message is sent only when the level actually changes. Jitter between 1 and 2 is suppressed (windows can stay open either way).
  - For levels **≥ 3**: the bot sends an update on **every** check (once per timer tick) with a directional arrow (`↑`/`↓`/`→`), so you can watch the trend while the air is bad.
  - Going from a bad level (≥ 3) back to a safe one (≤ 2) always produces a "good news" message.
- **Error channel (`ERROR_CHANNEL_ID`)** — only operational alerts:
  - One message after **3 consecutive failed scrapes** (DLI site down / network issue).
  - One message when scraping recovers, with the current level.

## Project layout

```
pollution_checker/        # The bot package
  config.py               # Reads env vars; minimal .env loader for local runs
  scraper.py              # HTTP + BeautifulSoup, retry with backoff
  notifier.py             # Telegram client + message templates
  state.py                # Atomic JSON state file
  trend.py                # Pure decision logic (when to notify, which arrow)
  logging_setup.py        # Stdout logger configured for systemd journal
  __main__.py             # Entry point: `python -m pollution_checker`
tests/                    # pytest suite, including a captured DLI HTML fixture
deploy/
  pollution-checker.service
  pollution-checker.timer
  install.sh              # Idempotent installer for systemd hosts
.env.example              # Template for environment variables
pyproject.toml
requirements.txt
```

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env
# Edit .env: real BOT_TOKEN / CHANNEL_ID / ERROR_CHANNEL_ID, plus DRY_RUN=1 for tests.

python -m pollution_checker        # one check
pytest                              # full test suite
ruff check .                        # lint
```

`DRY_RUN=1` makes the bot log Telegram messages instead of sending them — useful while iterating.

## Deploying on Oracle Cloud Free Tier (or any systemd host)

The free `VM.Standard.A1.Flex` ARM instance is more than enough — 4 vCPU / 24 GB RAM, while this bot uses tens of megabytes.

1. **Provision an Always-Free ARM Compute instance** with Ubuntu 22.04+ or Oracle Linux 9.
   - Allow outbound 443 (default).
   - SSH in: `ssh ubuntu@<public_ip>`.
2. **Install dependencies**:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-venv git rsync
   ```
3. **Clone the repo and run the installer**:
   ```bash
   git clone https://github.com/wrtrn/Pollution-checker.git
   cd Pollution-checker
   sudo ./deploy/install.sh
   ```
4. **Fill in real secrets**:
   ```bash
   sudo nano /etc/pollution-checker/env
   ```
   Set `BOT_TOKEN`, `CHANNEL_ID`, `ERROR_CHANNEL_ID`. **Do not set `STATE_FILE` here** — the systemd unit pins it to `/var/lib/pollution-checker/state.json`; setting it in the env file would override the unit and break the read-only-filesystem hardening.
5. **Verify**:
   ```bash
   sudo systemctl start pollution-checker.service           # one immediate run
   sudo systemctl status pollution-checker.timer
   journalctl -u pollution-checker.service -n 50 -f         # live logs
   ```

That's it — the timer runs every 15 minutes, survives reboots (`Persistent=true` + `WantedBy=timers.target`), and the `oneshot` service shape means there is nothing to crash between runs. If the host goes down, the bot resumes automatically the moment the host boots back up.

## Updating

```bash
cd ~/Pollution-checker
git pull
sudo ./deploy/install.sh   # idempotent: re-syncs code and reinstalls units
```

The existing `/etc/pollution-checker/env` and `/var/lib/pollution-checker/state.json` are preserved.

## Refreshing the test fixture

If the DLI site layout changes and parser tests start failing:

```bash
curl -A 'Mozilla/5.0' https://www.airquality.dli.mlsi.gov.cy/ \
    -o tests/fixtures/dli_sample.html
pytest
```

If the parser needs updating, the relevant logic lives in `pollution_checker/scraper.py` (`parse_stations` and `_find_status_color`).

## Security notes

- Real secrets never live in the repo — only `.env.example` with placeholders.
- `.env` and any local `pollution_state.json` are git-ignored.
- On the server, `/etc/pollution-checker/env` is `0640 root:pollution` so no other user can read it.
- The systemd unit ships with a hardening preamble (`ProtectSystem=strict`, `NoNewPrivileges`, etc.) — the service can only write to `/var/lib/pollution-checker/`.
