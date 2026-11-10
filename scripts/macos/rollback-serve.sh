#!/bin/bash
# Remove only the /mcp handler. Does not reset other Serve handlers or enable Funnel.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
macos_refuse_xtrace
PY="$(macos_python)"
exec "$PY" -u "$DIR/rollback_serve.py"
