#!/bin/bash
# Copy Bearer plus the existing http-auth token to the pasteboard.
# Pass --confirm. The token is not printed. The Bridge password is not read.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
macos_refuse_xtrace
PY="$(macos_python)"
exec "$PY" -u "$DIR/copy_http_auth.py" "$@"
