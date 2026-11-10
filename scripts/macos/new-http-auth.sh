#!/bin/bash
# Generate a bearer token and store it as proton-mail-mcp:http-auth.
# The token is not printed, not an argument, and not written to a file.
# An existing token is left in place.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
macos_refuse_xtrace
PY="$(macos_python)"
echo "If macOS asks to use the keychain, click Always Allow."
exec "$PY" -u "$DIR/new_http_auth.py"
