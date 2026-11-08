#!/usr/bin/env python3
"""Store one connector secret from stdin. The secret is never an argument."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector.secrets import LOGICAL_NAMES, SecretStoreError, WindowsCredentialStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in LOGICAL_NAMES:
        sys.stderr.write("usage: proton-mail-mcp-store.py bridge-imap|http-auth < secret-on-stdin\n")
        return 2
    secret = sys.stdin.read()
    if secret.endswith("\n"):
        secret = secret[:-1]
    if secret.endswith("\r"):
        secret = secret[:-1]
    try:
        WindowsCredentialStore().put(args[0], secret)
    except SecretStoreError as exc:
        sys.stderr.write(f"proton-mail-mcp-store: {exc}\n")
        return 2
    sys.stderr.write(f"proton-mail-mcp-store: stored {args[0]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
