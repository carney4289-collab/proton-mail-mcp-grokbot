#!/usr/bin/env python3
"""Check the private HTTPS endpoint. Does not start a server or read the Bridge secret."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector.https_check import (  # noqa: E402
    EndpointError,
    check_private_https,
    format_summary,
    validate_private_https_endpoint,
)
from connector.secrets import HTTP_AUTH, SecretStoreError, WindowsCredentialStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "--endpoint":
        sys.stderr.write(
            "usage: proton-mail-mcp-check-endpoint.py --endpoint https://dell-sean.tail545f1e.ts.net/mcp\n"
        )
        return 2
    try:
        endpoint = validate_private_https_endpoint(args[1])
    except EndpointError:
        sys.stderr.write("proton-mail-mcp-check-endpoint: endpoint rejected\n")
        return 2
    try:
        token = WindowsCredentialStore().get(HTTP_AUTH)
    except SecretStoreError as exc:
        sys.stderr.write(f"proton-mail-mcp-check-endpoint: {exc}\n")
        return 2
    if not token:
        sys.stderr.write("proton-mail-mcp-check-endpoint: http-auth token is not stored\n")
        return 2
    try:
        summary = check_private_https(endpoint, token)
        sys.stdout.write(format_summary(summary, token))
    except EndpointError as exc:
        sys.stderr.write(f"proton-mail-mcp-check-endpoint: {exc}\n")
        return 2
    except Exception:
        sys.stderr.write("proton-mail-mcp-check-endpoint: https check failed\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
