#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${1:-/opt/idx-trading-lab}"
SERVICE_NAME="${2:-idx-web.service}"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -d "$REPO_DIR" ]]; then
  echo "Repository directory not found: $REPO_DIR" >&2
  exit 1
fi

if [[ ! -f "$REPO_DIR/deploy/systemd/idx-web.service.example" ]]; then
  echo "Service example not found in repo." >&2
  exit 1
fi

sudo cp "$REPO_DIR/deploy/systemd/idx-web.service.example" "$SERVICE_TARGET"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager
