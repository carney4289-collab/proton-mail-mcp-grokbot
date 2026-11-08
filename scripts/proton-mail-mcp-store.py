#!/usr/bin/env python3
"""Store one connector secret from stdin. The secret is never an argument."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector.secrets import (  # noqa: E402
    BRIDGE_IMAP,
    HTTP_AUTH,
    LOGICAL_NAMES,
    SecretStoreError,
    WindowsCredentialStore,
    store_generated_token,
)

GENERATE_NAMES = (HTTP_AUTH, "ci-dummy")


def _generate(name: str) -> int:
    if name == BRIDGE_IMAP or name not in GENERATE_NAMES:
        sys.stderr.write("proton-mail-mcp-store: refusing to generate that credential\n")
        return 2
    try:
        store_generated_token(WindowsCredentialStore(), name)
    except SecretStoreError as exc:
        sys.stderr.write(f"proton-mail-mcp-store: {exc}\n")
        return 2
    sys.stderr.write(f"proton-mail-mcp-store: stored {name}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "--generate":
        return _generate(args[1])
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
