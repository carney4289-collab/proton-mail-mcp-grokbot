#!/usr/bin/env python3
"""Write config/macos.env from the example. The email is read from stdin, not argv."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from connector.macos_config import valid_username  # noqa: E402


def main() -> int:
    lines = sys.stdin.read().splitlines()
    if len(lines) != 4:
        sys.stderr.write("proton-mail-mcp-macos: config values were rejected\n")
        return 2
    email, node_bin, mcp_js, attachments = lines
    if not valid_username(email):
        sys.stderr.write("proton-mail-mcp-macos: the email address was rejected\n")
        return 2
    for path in (node_bin, mcp_js, attachments):
        if not path.startswith("/") or any(ch in path for ch in "\r\n"):
            sys.stderr.write("proton-mail-mcp-macos: a path was rejected\n")
            return 2
    example = (ROOT / "config" / "macos.env.example").read_text(encoding="utf-8")
    text = (
        example.replace("REPLACE_NODE_BIN", node_bin)
        .replace("REPLACE_MCP_JS", mcp_js)
        .replace("REPLACE_WITH_PROTON_ACCOUNT_USERNAME", email)
        .replace("REPLACE_ATTACHMENTS", attachments)
    )
    if "REPLACE_" in text:
        sys.stderr.write("proton-mail-mcp-macos: config template was not filled\n")
        return 2
    if email not in text.split("PROTONMAIL_USERNAME=", 1)[-1].splitlines()[0]:
        sys.stderr.write("proton-mail-mcp-macos: config template was not filled\n")
        return 2
    destination = ROOT / "config" / "macos.env"
    destination.write_text(text, encoding="utf-8")
    os.chmod(destination, 0o600)
    sys.stderr.write("proton-mail-mcp-macos: wrote config/macos.env\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
