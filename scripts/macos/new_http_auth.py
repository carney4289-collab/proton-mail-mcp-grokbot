#!/usr/bin/env python3
"""Generate the HTTP bearer into the login keychain. The token is not printed."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.keychain_macos import MacKeychainStore  # noqa: E402
from connector.secrets import SecretStoreError, store_generated_token  # noqa: E402


def main() -> int:
    if sys.argv[1:]:
        sys.stderr.write("proton-mail-mcp-macos: this program takes no arguments\n")
        return 2
    try:
        store = MacKeychainStore()
        store_generated_token(store, "http-auth")
    except SecretStoreError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    sys.stderr.write("proton-mail-mcp-macos: stored http-auth\n")
    if not store.unattended:
        sys.stderr.write(
            "proton-mail-mcp-macos: macOS may ask again the next time this Python runs. Click Always Allow.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
