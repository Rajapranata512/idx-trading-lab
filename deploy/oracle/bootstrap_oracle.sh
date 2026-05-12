#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash deploy/oracle/bootstrap_oracle.sh <repo_url> [domain]
#
# Example:
#   bash deploy/oracle/bootstrap_oracle.sh https://github.com/yourname/idx-trading-lab.git trading.example.com
#
# Notes:
# - Run this on Oracle Ubuntu VM as a sudo-capable user (e.g., ubuntu).
# - Domain is optional; use "_" for no custom domain yet.

if [[ $# -lt 1 ]]; then
  echo "Usage: bash deploy/oracle/bootstrap_oracle.sh <repo_url> [domain]"
  exit 1
fi

REPO_URL="$1"
DOMAIN="${2:-_}"

APP_DIR="${APP_DIR:-/opt/idx-trading-lab}"
APP_USER="${APP_USER:-ubuntu}"
WEB_PORT="${WEB_PORT:-8080}"
SETTINGS_PATH="${SETTINGS_PATH:-config/settings.json}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "[1/8] Install OS packages..."
$SUDO apt-get update -y
$SUDO apt-get install -y git "${PYTHON_BIN}" "${PYTHON_BIN}-venv" python3-pip nginx

echo "[2/8] Clone or update repository..."
if [[ ! -d "${APP_DIR}/.git" ]]; then
  $SUDO rm -rf "${APP_DIR}"
  $SUDO git clone "${REPO_URL}" "${APP_DIR}"
else
  $SUDO git -C "${APP_DIR}" fetch --all
  $SUDO git -C "${APP_DIR}" pull --ff-only || true
fi
$SUDO chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

echo "[3/8] Create virtualenv and install Python dependencies..."
$SUDO -u "${APP_USER}" bash -lc "
  set -euo pipefail
  cd '${APP_DIR}'
  ${PYTHON_BIN} -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
"

echo "[4/8] Prepare runtime settings..."
if [[ ! -f "${APP_DIR}/${SETTINGS_PATH}" ]]; then
  if [[ -f "${APP_DIR}/config/settings.example.json" ]]; then
    $SUDO cp "${APP_DIR}/config/settings.example.json" "${APP_DIR}/${SETTINGS_PATH}"
    $SUDO chown "${APP_USER}:${APP_USER}" "${APP_DIR}/${SETTINGS_PATH}"
    echo "Created ${SETTINGS_PATH} from settings.example.json"
  else
    echo "WARNING: settings file not found. Please create ${APP_DIR}/${SETTINGS_PATH} manually."
  fi
fi

echo "[5/8] Create environment file (/etc/default/idx-trading-lab)..."
if [[ ! -f /etc/default/idx-trading-lab ]]; then
  $SUDO tee /etc/default/idx-trading-lab >/dev/null <<'EOF'
# Fill your provider tokens here.
# Example:
# EODHD_API_TOKEN=your_token_here
EODHD_API_TOKEN=
EOF
fi

echo "[6/8] Install systemd services..."
$SUDO tee /etc/systemd/system/idx-web.service >/dev/null <<EOF
[Unit]
Description=IDX Trading Lab Web Server
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/default/idx-trading-lab
ExecStart=${APP_DIR}/.venv/bin/python -m src.cli --settings ${SETTINGS_PATH} serve-web --host 127.0.0.1 --port ${WEB_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

$SUDO tee /etc/systemd/system/idx-daemon.service >/dev/null <<EOF
[Unit]
Description=IDX Trading Lab Intraday Daemon
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/default/idx-trading-lab
ExecStart=${APP_DIR}/.venv/bin/python -m src.cli --settings ${SETTINGS_PATH} run-intraday-daemon
Restart=always
RestartSec=8

[Install]
WantedBy=multi-user.target
EOF

echo "[7/8] Configure Nginx reverse proxy..."
$SUDO tee /etc/nginx/sites-available/idx-trading-lab >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

$SUDO rm -f /etc/nginx/sites-enabled/default
$SUDO ln -sf /etc/nginx/sites-available/idx-trading-lab /etc/nginx/sites-enabled/idx-trading-lab
$SUDO nginx -t

echo "[8/8] Start services..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now idx-web.service
$SUDO systemctl enable --now idx-daemon.service
$SUDO systemctl enable --now nginx
$SUDO systemctl restart nginx

echo
echo "Done."
echo "Open: http://<YOUR_VM_PUBLIC_IP>/"
echo
echo "Useful commands:"
echo "  sudo systemctl status idx-web idx-daemon --no-pager"
echo "  sudo journalctl -u idx-web -f"
echo "  sudo journalctl -u idx-daemon -f"
echo
echo "Next (optional HTTPS):"
echo "  sudo apt-get install -y certbot python3-certbot-nginx"
echo "  sudo certbot --nginx -d ${DOMAIN}"
