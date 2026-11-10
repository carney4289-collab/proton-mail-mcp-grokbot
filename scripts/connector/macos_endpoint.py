"""Unauthenticated check of the Mac mini's private MCP URL.

One GET, no Authorization header, no redirect, certificate verification on.
The only accepted URL is https://seans-mac-mini.tail545f1e.ts.net/mcp.
"""
from __future__ import annotations

import http.client
import ssl
import urllib.parse

from connector.macos_config import MAC_HOST

ALLOWED_ENDPOINT = f"https://{MAC_HOST}/mcp"


class EndpointError(ValueError):
    pass


def validate_mac_endpoint(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme != "https":
        raise EndpointError("endpoint must be https")
    if parsed.username is not None or parsed.password is not None:
        raise EndpointError("endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise EndpointError("endpoint must not contain a query or fragment")
    host = (parsed.hostname or "").lower()
    if host != MAC_HOST:
        raise EndpointError("endpoint host is not the private Tailscale name")
    if parsed.port not in (None, 443):
        raise EndpointError("endpoint port must be 443")
    if parsed.path != "/mcp":
        raise EndpointError("endpoint path must be /mcp")
    return ALLOWED_ENDPOINT


def interpret_unauth(status: int) -> None:
    if 300 <= status < 400:
        raise EndpointError("redirect refused")
    if status != 401:
        raise EndpointError("unauthenticated request was not rejected")


def public_tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise EndpointError("TLS certificate verification is required")
    return context


def fetch_unauth_status(timeout: float = 20.0) -> int:
    """GET the one allowed URL with no Authorization header. The body is discarded."""
    context = public_tls_context()
    conn = http.client.HTTPSConnection(MAC_HOST, 443, timeout=timeout, context=context)
    try:
        conn.request(
            "GET",
            "/mcp",
            headers={"Accept": "application/json", "Connection": "close"},
        )
        response = conn.getresponse()
        response.read()
        return int(response.status)
    finally:
        conn.close()


def format_ok() -> str:
    return f"endpoint {ALLOWED_ENDPOINT}\nunauth 401\n"
