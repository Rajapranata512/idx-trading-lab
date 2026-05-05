#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash deploy/oracle/update_oracle.sh [app_dir]
#
# Example:
#   bash deploy/oracle/update_oracle.sh /opt/idx-trading-lab

APP_DIR="${1:-/opt/idx-trading-lab}"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

if [[ ! -d "${APP_DIR}/.git" ]]; then
  echo "Repository not found at ${APP_DIR}"
  exit 1
fi

APP_USER="$(stat -c '%U' "${APP_DIR}")"

echo "[1/4] Pull latest source..."
$SUDO -u "${APP_USER}" git -C "${APP_DIR}" fetch --all
$SUDO -u "${APP_USER}" git -C "${APP_DIR}" pull --ff-only

echo "[2/4] Install/update dependencies..."
$SUDO -u "${APP_USER}" bash -lc "
  set -euo pipefail
  cd '${APP_DIR}'
  source .venv/bin/activate
  pip install -r requirements.txt
"

echo "[3/4] Restart services..."
$SUDO systemctl restart idx-web.service
$SUDO systemctl restart idx-daemon.service

echo "[4/4] Status..."
$SUDO systemctl --no-pager --full status idx-web.service idx-daemon.service | sed -n '1,80p'

echo "Update done."
