#!/usr/bin/env python3
"""Check config and that both keychain items exist. Values are not printed."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from connector.keychain_macos import MacKeychainStore  # noqa: E402
from connector.macos_config import assert_launch_config, load_macos_config  # noqa: E402
from connector.runtime_env import ConfigError  # noqa: E402
from connector.secrets import SecretStoreError  # noqa: E402


def main() -> int:
    env_path = ROOT / "config" / "macos.env"
    if not env_path.is_file():
        sys.stderr.write("proton-mail-mcp-macos: missing config/macos.env\n")
        return 2
    home = os.environ.get("HOME", "")
    if not home.startswith("/"):
        sys.stderr.write("proton-mail-mcp-macos: HOME is not set\n")
        return 2
    source: dict[str, str] = {}
    try:
        load_macos_config(env_path, source, home)
        assert_launch_config(source)
    except ConfigError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    node = source.get("NODE_BIN", "")
    mcp = source.get("MCP_JS", "")
    if not node or not os.path.exists(node) or not os.path.isfile(mcp):
        sys.stderr.write("proton-mail-mcp-macos: Node runtime or MCP build was not found\n")
        return 2
    try:
        store = MacKeychainStore()
        bridge = bool(store.get("bridge-imap"))
        auth = bool(store.get("http-auth"))
    except SecretStoreError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    sys.stdout.write("bridge-imap: " + ("present" if bridge else "missing") + "\n")
    sys.stdout.write("http-auth: " + ("present" if auth else "missing") + "\n")
    if not bridge or not auth:
        sys.stderr.write("proton-mail-mcp-macos: store the Bridge password and generate the token first\n")
        return 2
    sys.stdout.write("config: ok\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
