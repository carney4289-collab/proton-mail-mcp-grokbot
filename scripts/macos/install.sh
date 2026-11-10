#!/bin/bash
# Install a user-level Python and Node, then build the pinned MCP server.
#
# uv's standalone binary is used instead of the python.org installer because
# it does not need sudo or a GUI, and Apple's /usr/bin/python3 is too old for
# this connector. Node is the official darwin-arm64 tarball, not Homebrew.
# This script does not read or write the Bridge password or the bearer token.
set -euo pipefail
umask 077

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
macos_refuse_xtrace
PKG="$(macos_package_root)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This installer is for Apple Silicon (arm64)." >&2
  exit 1
fi
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this as your own user, not with sudo." >&2
  exit 1
fi
if [[ -z "${HOME:-}" || "${HOME}" != /* ]]; then
  echo "HOME is not set." >&2
  exit 1
fi

PREFIX="${HOME}/Library/Application Support/ProtonMailMCP"
RUNTIME="${PREFIX}/runtimes"
mkdir -p "$RUNTIME" "${HOME}/Library/Logs/ProtonMailMCP" "${PREFIX}/attachments"

NODE_VERSION="24.22.1"
NODE_SHA256="89c682593d76cd44233fa53b1563264e7de9cbb189cad169135c5b4fadfbc0a7"
UV_VERSION="0.13.7"
UV_SHA256="81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731"

download() {
  local url="$1"
  local dest="$2"
  local sha="$3"
  if [[ -f "$dest" ]]; then
    if echo "${sha}  ${dest}" | shasum -a 256 -c - >/dev/null 2>&1; then
      return 0
    fi
  fi
  curl -fsSL --retry 3 --retry-delay 2 -o "${dest}.partial" "$url"
  mv "${dest}.partial" "$dest"
  echo "${sha}  ${dest}" | shasum -a 256 -c -
}

download \
  "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-apple-darwin.tar.gz" \
  "${RUNTIME}/uv.tar.gz" \
  "$UV_SHA256"
rm -rf "${RUNTIME}/uv-extract"
mkdir -p "${RUNTIME}/uv-extract"
tar -xzf "${RUNTIME}/uv.tar.gz" -C "${RUNTIME}/uv-extract"
UV="${RUNTIME}/uv-extract/uv-aarch64-apple-darwin/uv"
chmod 700 "$UV"

export UV_PYTHON_INSTALL_DIR="${RUNTIME}/python"
export UV_CACHE_DIR="${RUNTIME}/uv-cache"
"$UV" python install 3.12
if [[ ! -x "${RUNTIME}/venv/bin/python3" ]]; then
  "$UV" venv "${RUNTIME}/venv" --python 3.12
fi
"${RUNTIME}/venv/bin/python3" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'

download \
  "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-darwin-arm64.tar.gz" \
  "${RUNTIME}/node.tar.gz" \
  "$NODE_SHA256"
if ! "${RUNTIME}/node/bin/node" -v 2>/dev/null | grep -qx "v${NODE_VERSION}"; then
  rm -rf "${RUNTIME}/node-extract" "${RUNTIME}/node"
  mkdir -p "${RUNTIME}/node-extract"
  tar -xzf "${RUNTIME}/node.tar.gz" -C "${RUNTIME}/node-extract"
  mv "${RUNTIME}/node-extract/node-v${NODE_VERSION}-darwin-arm64" "${RUNTIME}/node"
fi

"${RUNTIME}/venv/bin/python3" -u "$DIR/build_pinned.py" \
  --dest "$PKG/build/proton-mail-mcp" \
  --node "${RUNTIME}/node/bin/node" \
  --npm "${RUNTIME}/node/bin/npm"

ENV_FILE="$PKG/config/macos.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "config/macos.env already exists; left unchanged."
else
  if [[ -n "${PROTONMAIL_USERNAME:-}" ]]; then
    email="$PROTONMAIL_USERNAME"
  elif [[ -t 0 ]]; then
    echo "Type the Proton account email. This is not the password."
    read -r -p "Email: " email
  else
    echo "Run this in Terminal.app so it can ask for the email address." >&2
    exit 1
  fi
  printf '%s\n%s\n%s\n%s\n' \
    "$email" \
    "${RUNTIME}/node/bin" \
    "$PKG/build/proton-mail-mcp/build/index.js" \
    "${PREFIX}/attachments" \
    | "${RUNTIME}/venv/bin/python3" -u "$DIR/write_config.py"
  unset email
fi

echo "Runtime and config are in place."
echo "Next, store the Bridge password:"
echo "  bash \"$DIR/store-bridge.sh\""
