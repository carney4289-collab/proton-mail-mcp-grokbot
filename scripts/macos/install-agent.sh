#!/bin/bash
# Install the per-user LaunchAgent. No sudo. Does not start a second connector
# when 127.0.0.1:8765 is already open; launchd starts this one at login.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
macos_refuse_xtrace
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this as your own user, not with sudo." >&2
  exit 1
fi
PY="$(macos_python)"
PKG="$(macos_package_root)"
"$PY" -u "$DIR/preflight.py"
LABEL="local.proton-mail-mcp.loopback"
DOMAIN="gui/$(id -u)"
AGENTS="${HOME}/Library/LaunchAgents"
LOGS="${HOME}/Library/Logs/ProtonMailMCP"
mkdir -p "$AGENTS" "$LOGS"
PLIST="${AGENTS}/${LABEL}.plist"
"$PY" -u "$DIR/render_plist.py" --package-root "$PKG" --python "$PY" --home "$HOME" > "${PLIST}.tmp"
mv "${PLIST}.tmp" "$PLIST"
chmod 644 "$PLIST"
if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}/${LABEL}"
fi
if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
  echo "Could not load the LaunchAgent." >&2
  echo "Open Terminal.app while you are logged in on the Mac and run this again." >&2
  exit 1
fi
launchctl enable "${DOMAIN}/${LABEL}" >/dev/null 2>&1 || true
echo "LaunchAgent installed. It runs when you are logged in."
echo "Logs: ${LOGS}"
echo "Bridge Open at login was not verified. This script does not change Bridge settings."
echo "Next, check it:"
echo "  bash \"$DIR/status.sh\""
