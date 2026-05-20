#!/usr/bin/env bash
# Idempotent installer for an Oracle Cloud (or any systemd-based) host.
# Run as root. Re-running upgrades the code from the current working tree.
#
# Usage:
#   sudo ./deploy/install.sh
#
# What it does:
#   1. Creates a `pollution` system user and home /opt/pollution-checker.
#   2. Copies source into /opt/pollution-checker and creates a venv there.
#   3. Installs the systemd unit + timer and enables the timer.
#   4. Creates /etc/pollution-checker/env from .env.example if it does not exist
#      yet and reminds the operator to fill it in.
#
# It deliberately does NOT overwrite an existing /etc/pollution-checker/env.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/pollution-checker"
ETC_DIR="/etc/pollution-checker"
ENV_FILE="${ETC_DIR}/env"
SERVICE_USER="pollution"

echo "==> Ensuring system user '${SERVICE_USER}' exists"
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

echo "==> Syncing source into ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
    --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    --exclude='tests' --exclude='*.pyc' --exclude='.pytest_cache' \
    --exclude='.ruff_cache' --exclude='deploy' \
    "${REPO_DIR}/" "${INSTALL_DIR}/"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

echo "==> Setting up venv"
if [[ ! -x "${INSTALL_DIR}/.venv/bin/python" ]]; then
    python3 -m venv "${INSTALL_DIR}/.venv"
fi
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/.venv"

echo "==> Setting up ${ETC_DIR}"
mkdir -p "${ETC_DIR}"
chmod 0750 "${ETC_DIR}"
chown root:"${SERVICE_USER}" "${ETC_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${REPO_DIR}/.env.example" "${ENV_FILE}"
    chmod 0640 "${ENV_FILE}"
    chown root:"${SERVICE_USER}" "${ENV_FILE}"
    echo "    Created ${ENV_FILE} from .env.example."
    echo "    EDIT IT NOW and put real BOT_TOKEN / CHANNEL_ID / ERROR_CHANNEL_ID."
else
    echo "    Existing ${ENV_FILE} kept."
    # Common upgrade hazard: older .env.example shipped a STATE_FILE= line
    # that overrides the unit's StateDirectory and breaks the read-only-fs
    # hardening. Detect and warn loudly.
    if grep -qE '^[[:space:]]*STATE_FILE=' "${ENV_FILE}"; then
        echo
        echo "    WARNING: ${ENV_FILE} sets STATE_FILE=. The systemd unit pins"
        echo "    STATE_FILE to /var/lib/pollution-checker/state.json and the"
        echo "    EnvironmentFile would override that, causing read-only-fs"
        echo "    errors. Removing the line so the unit's value wins."
        sed -i.bak -E 's/^[[:space:]]*STATE_FILE=/# (removed by installer) STATE_FILE=/' "${ENV_FILE}"
        echo "    Backup at ${ENV_FILE}.bak"
    fi
fi

echo "==> Installing systemd units"
install -m 0644 "${REPO_DIR}/deploy/pollution-checker.service" /etc/systemd/system/
install -m 0644 "${REPO_DIR}/deploy/pollution-checker.timer"   /etc/systemd/system/
systemctl daemon-reload

echo "==> Enabling and starting timer"
systemctl enable --now pollution-checker.timer

echo
echo "Done."
echo "  Status:      systemctl status pollution-checker.timer"
echo "  Last run:    journalctl -u pollution-checker.service -n 50"
echo "  Trigger now: sudo systemctl start pollution-checker.service"
