#!/usr/bin/env python3
"""Place the existing http-auth bearer on the clipboard. Does not print it.

Reads only proton-mail-mcp:http-auth. Does not read or write the Bridge
credential, start a server, or contact the network.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector.clipboard_auth import (  # noqa: E402
    ClipboardHandoffError,
    WindowsClipboard,
    parse_cli,
    run_handoff,
)
from connector.secrets import WindowsCredentialStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        seconds = parse_cli(args)
    except ClipboardHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-clipboard-auth: {exc}\n")
        return 2
    if sys.platform != "win32":
        sys.stderr.write("proton-mail-mcp-clipboard-auth: clipboard handoff is only supported on Windows\n")
        return 2
    try:
        store = WindowsCredentialStore()
        clipboard = WindowsClipboard()
    except Exception:
        sys.stderr.write("proton-mail-mcp-clipboard-auth: clipboard handoff is only supported on Windows\n")
        return 2
    return run_handoff(store, clipboard, seconds, time.sleep, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
