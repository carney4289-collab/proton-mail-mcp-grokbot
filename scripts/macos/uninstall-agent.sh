#!/bin/bash
# Remove the per-user LaunchAgent and stop the connector it started.
# Does not delete keychain items, Bridge, or Tailscale Serve.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this as your own user, not with sudo." >&2
  exit 1
fi
LABEL="local.proton-mail-mcp.loopback"
DOMAIN="gui/$(id -u)"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}/${LABEL}"
fi
rm -f "$PLIST"
echo "LaunchAgent removed. The connector process was stopped."
echo "Bridge, Tailscale, and the login keychain items were not changed."
echo "To remove only the /mcp Serve handler, run:"
echo "  bash \"$DIR/rollback-serve.sh\""
