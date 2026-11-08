#!/usr/bin/env bash
set -euo pipefail

# Installs the agent files and systemd unit. It does not start the service or
# modify the token for you.
if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: sudo $0" >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/airs-agent"
CONFIG_DIR="/etc/airs-agent"
STATE_DIR="/var/lib/airs-agent"

install -d -m 0755 "${INSTALL_DIR}"
install -d -m 0700 "${CONFIG_DIR}"
install -d -m 0700 "${STATE_DIR}"

cp -a "${SOURCE_DIR}/app" "${INSTALL_DIR}/"
cp "${SOURCE_DIR}/requirements.txt" "${INSTALL_DIR}/"

if [[ ! -x "${INSTALL_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${INSTALL_DIR}/.venv"
fi
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

if [[ ! -f "${CONFIG_DIR}/agent.env" ]]; then
  cp "${SOURCE_DIR}/.env.example" "${CONFIG_DIR}/agent.env"
  chmod 0600 "${CONFIG_DIR}/agent.env"
  echo "Created ${CONFIG_DIR}/agent.env; edit it before starting the service."
fi

install -m 0644 "${SOURCE_DIR}/systemd/airs-agent.service" \
  /etc/systemd/system/airs-agent.service
systemctl daemon-reload

echo "Installed. Next:"
echo "  1. sudo editor ${CONFIG_DIR}/agent.env"
echo "  2. sudo systemctl enable --now airs-agent"
echo "  3. journalctl -u airs-agent -f"
