#!/usr/bin/env python3
"""Load config/macos.env and replace this process with the loopback connector."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from connector.macos_config import assert_launch_config, load_macos_config  # noqa: E402
from connector.runtime_env import ConfigError  # noqa: E402


def main() -> int:
    if sys.argv[1:]:
        sys.stderr.write("proton-mail-mcp-macos: this program takes no arguments\n")
        return 2
    env_path = ROOT / "config" / "macos.env"
    if not env_path.is_file():
        sys.stderr.write("proton-mail-mcp-macos: missing config/macos.env\n")
        return 2
    home = os.environ.get("HOME", "")
    if not home.startswith("/"):
        sys.stderr.write("proton-mail-mcp-macos: HOME is not set\n")
        return 2
    os.environ.pop("IMAP_PASSWORD", None)
    os.environ.pop("PROTONMAIL_PASSWORD", None)
    try:
        load_macos_config(env_path, os.environ, home)
        assert_launch_config(os.environ)
    except ConfigError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    node = os.environ.get("NODE_BIN", "")
    mcp = os.environ.get("MCP_JS", "")
    if not node or not os.path.exists(node):
        sys.stderr.write("proton-mail-mcp-macos: Node runtime was not found. Run scripts/macos/install.sh.\n")
        return 2
    if not os.path.isfile(mcp):
        sys.stderr.write("proton-mail-mcp-macos: the MCP build was not found. Run scripts/macos/install.sh.\n")
        return 2
    node_dir = node if os.path.isdir(node) else os.path.dirname(node)
    os.environ["PATH"] = node_dir + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")
    os.environ["PROTON_MCP_SECRET_STORE"] = "keychain"
    os.environ["HOME"] = home
    http_py = ROOT / "scripts" / "proton-mail-mcp-http.py"
    os.execv(sys.executable, [sys.executable, "-u", str(http_py)])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
