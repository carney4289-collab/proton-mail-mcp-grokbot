#!/bin/bash
# Apply the persistent private /mcp Serve handler, or report that it is already saved.
# Run this in Terminal.app. An SSH shell can fail to start the Tailscale GUI.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
macos_refuse_xtrace
PY="$(macos_python)"
exec "$PY" -u "$DIR/apply_serve.py"
