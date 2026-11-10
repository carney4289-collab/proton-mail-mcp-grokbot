#!/usr/bin/env python3
"""Store the Bridge password from stdin into the login keychain.

Bridge uses one password for IMAP and SMTP. It is not the Proton account
password. Two lines are required and must match. The password is not printed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.keychain_macos import MacKeychainStore  # noqa: E402
from connector.secrets import SecretStoreError  # noqa: E402


def main() -> int:
    parts = sys.stdin.read().splitlines()
    if len(parts) != 2 or parts[0] != parts[1] or not parts[0]:
        sys.stderr.write("proton-mail-mcp-macos: the two entries did not match\n")
        return 2
    secret = parts[0]
    if any(ch in secret for ch in "\r\n\x00"):
        sys.stderr.write("proton-mail-mcp-macos: the Bridge password was rejected\n")
        return 2
    try:
        store = MacKeychainStore()
        store.put("bridge-imap", secret)
    except SecretStoreError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    sys.stderr.write("proton-mail-mcp-macos: stored bridge-imap\n")
    if not store.unattended:
        sys.stderr.write(
            "proton-mail-mcp-macos: macOS may ask again the next time this Python runs. Click Always Allow.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
