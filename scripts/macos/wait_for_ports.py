#!/usr/bin/env python3
"""Check loopback TCP ports. Does not send IMAP, SMTP, or HTTP."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.macos_ports import bridge_ready, parse_wait_seconds, tcp_open  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args == ["--status"]:
            for port, label in ((8765, "connector-port"), (1143, "bridge-imap-port"), (1025, "bridge-smtp-port")):
                state = "open" if tcp_open(port) else "closed"
                sys.stdout.write(f"{label} 127.0.0.1:{port} {state}\n")
            return 0
        if len(args) == 2 and args[0] == "--check":
            port = int(args[1]) if args[1].isdigit() else 0
            return 0 if tcp_open(port) else 1
        if args == ["--wait-bridge"]:
            seconds = parse_wait_seconds(os.environ.get("PROTON_MCP_BRIDGE_WAIT_SECONDS"))
            return 0 if bridge_ready(seconds) else 1
    except ValueError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    sys.stderr.write("proton-mail-mcp-macos: arguments rejected\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
