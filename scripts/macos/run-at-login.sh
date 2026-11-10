#!/bin/bash
# LaunchAgent entry point. Waits for Bridge, then replaces this process with
# the connector. An open 127.0.0.1:8765 is left alone. Does not read the keychain.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
PY="$(macos_python)"
if "$PY" -u "$DIR/wait_for_ports.py" --check 8765; then
  echo "connector port 127.0.0.1:8765 is already open; not starting another process"
  exit 0
fi
if ! "$PY" -u "$DIR/wait_for_ports.py" --wait-bridge; then
  echo "bridge ports 127.0.0.1:1143 and 127.0.0.1:1025 were not both open; connector was not started"
  echo "Bridge Open at login was not verified. This script does not change Bridge settings."
  exit 1
fi
exec "$PY" -u "$DIR/start_connector.py"
