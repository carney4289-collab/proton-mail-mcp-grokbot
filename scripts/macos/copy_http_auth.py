#!/usr/bin/env python3
"""Place the existing http-auth bearer on the pasteboard. Does not print it.

Reads only proton-mail-mcp:http-auth. Does not read the Bridge password,
start a server, or contact the network.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.clipboard_auth import ClipboardHandoffError, parse_cli, run_handoff  # noqa: E402
from connector.keychain_macos import MacKeychainStore  # noqa: E402
from connector.mac_clipboard import MacPasteboard  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        seconds = parse_cli(args)
    except ClipboardHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-clipboard-auth: {exc}\n")
        return 2
    if sys.platform != "darwin":
        sys.stderr.write("proton-mail-mcp-clipboard-auth: clipboard handoff is only supported on macOS\n")
        return 2
    try:
        store = MacKeychainStore()
        clipboard = MacPasteboard()
    except Exception as exc:
        message = str(exc) or "clipboard handoff is only supported on macOS"
        if "keychain" in message.lower() or "clipboard" in message.lower():
            sys.stderr.write(f"proton-mail-mcp-clipboard-auth: {message}\n")
        else:
            sys.stderr.write("proton-mail-mcp-clipboard-auth: clipboard handoff is only supported on macOS\n")
        return 2
    return run_handoff(store, clipboard, seconds, time.sleep, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
