#!/bin/bash
# Report the LaunchAgent and the loopback ports. Does not read the keychain
# and does not change Tailscale.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
LABEL="local.proton-mail-mcp.loopback"
DOMAIN="gui/$(id -u)"
if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  echo "agent: loaded"
else
  echo "agent: not loaded"
fi
if [[ -f "${HOME}/Library/LaunchAgents/${LABEL}.plist" ]]; then
  echo "plist: present"
else
  echo "plist: missing"
fi
PY="$(macos_python)"
"$PY" -u "$DIR/wait_for_ports.py" --status
echo "logs: ${HOME}/Library/Logs/ProtonMailMCP"
echo "bridge-autostart: not-verified"
echo "serve: not changed by this status check"
