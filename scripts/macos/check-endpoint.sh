#!/bin/bash
# Ask https://seans-mac-mini.tail545f1e.ts.net/mcp with no token.
# Success is one line: unauth 401. The optional argument must be that exact URL.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
PY="$(macos_python)"
exec "$PY" -u "$DIR/check_endpoint.py" "$@"
