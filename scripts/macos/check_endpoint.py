#!/usr/bin/env python3
"""Confirm an unauthenticated request to the Mac mini MCP URL returns 401.

No Authorization header is sent. Redirects are refused. The response body
is not printed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.macos_endpoint import (  # noqa: E402
    ALLOWED_ENDPOINT,
    EndpointError,
    fetch_unauth_status,
    format_ok,
    interpret_unauth,
    validate_mac_endpoint,
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        sys.stderr.write("proton-mail-mcp-macos: arguments rejected\n")
        return 2
    url = args[0] if args else ALLOWED_ENDPOINT
    try:
        validate_mac_endpoint(url)
    except EndpointError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    try:
        status = fetch_unauth_status()
        interpret_unauth(status)
    except EndpointError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    except OSError:
        sys.stderr.write("proton-mail-mcp-macos: the endpoint could not be reached\n")
        return 2
    sys.stdout.write(format_ok())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
