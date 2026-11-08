"""Authenticated check of one private HTTPS MCP endpoint. No tools/call.

The bearer token is supplied by the caller from Credential Manager. This
module does not print it, follow redirects, or accept any host except the
one Tailscale Serve name.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
from collections.abc import Callable

import http.client

ALLOWED_HTTPS_HOST = "dell-sean.tail545f1e.ts.net"
ALLOWED_HTTPS_ENDPOINT = f"https://{ALLOWED_HTTPS_HOST}/mcp"

Exchange = Callable[[dict, str | None, str | None], tuple[int, dict, bytes]]


class EndpointError(ValueError):
    pass


def validate_private_https_endpoint(url: str) -> str:
    """Return the canonical URL or reject the request before any connection."""
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme != "https":
        raise EndpointError("endpoint must be https")
    if parsed.username is not None or parsed.password is not None:
        raise EndpointError("endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise EndpointError("endpoint must not contain a query or fragment")
    host = (parsed.hostname or "").lower()
    if host != ALLOWED_HTTPS_HOST:
        raise EndpointError("endpoint host is not the private Tailscale name")
    if parsed.port not in (None, 443):
        raise EndpointError("endpoint port must be 443")
    if parsed.path != "/mcp":
        raise EndpointError("endpoint path must be /mcp")
    return ALLOWED_HTTPS_ENDPOINT


def public_tls_context() -> ssl.SSLContext:
    """Normal certificate verification. There is no insecure override."""
    context = ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise EndpointError("TLS certificate verification is required")
    return context


def read_mcp_response(response: http.client.HTTPResponse) -> tuple[int, dict, bytes]:
    """Read one response. A redirect is refused and not followed."""
    status = response.status
    payload = response.read()
    if 300 <= status < 400:
        raise EndpointError("redirect refused")
    headers = {key: value for key, value in response.getheaders()}
    return status, headers, payload


def post_private_https(
    body: dict,
    *,
    token: str | None,
    session: str | None,
    timeout: float = 30.0,
) -> tuple[int, dict, bytes]:
    context = public_tls_context()
    conn = http.client.HTTPSConnection(
        ALLOWED_HTTPS_HOST,
        443,
        timeout=timeout,
        context=context,
    )
    try:
        return post_on_connection(conn, body, token=token, session=session)
    finally:
        conn.close()


def post_on_connection(
    conn: http.client.HTTPConnection,
    body: dict,
    *,
    token: str | None,
    session: str | None,
) -> tuple[int, dict, bytes]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Connection": "close",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if session:
        headers["Mcp-Session-Id"] = session
    conn.request("POST", "/mcp", body=json.dumps(body).encode("utf-8"), headers=headers)
    return read_mcp_response(conn.getresponse())


def _initialize_body() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "https-check", "version": "0"},
        },
    }


def run_protocol(exchange: Exchange, token: str) -> dict:
    """Unauthenticated reject, then initialize, initialized, and tools/list."""
    status, _, _ = exchange(_initialize_body(), None, None)
    if status != 401:
        raise EndpointError("unauthenticated request was not rejected")
    status, headers, raw = exchange(_initialize_body(), token, None)
    if status != 200:
        raise EndpointError("initialize failed")
    session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    if not session:
        raise EndpointError("initialize did not return a session")
    protocol = json.loads(raw).get("result", {}).get("protocolVersion")
    status, _, _ = exchange({"jsonrpc": "2.0", "method": "notifications/initialized"}, token, session)
    if status not in (200, 202):
        raise EndpointError("notifications/initialized failed")
    status, _, raw = exchange(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        token,
        session,
    )
    if status != 200:
        raise EndpointError("tools/list failed")
    names = [tool.get("name") for tool in json.loads(raw).get("result", {}).get("tools", [])]
    return {"protocol": protocol, "names": names}


def check_private_https(url: str, token: str) -> dict:
    validate_private_https_endpoint(url)

    def exchange(body: dict, presented: str | None, session: str | None) -> tuple[int, dict, bytes]:
        return post_private_https(body, token=presented, session=session)

    return run_protocol(exchange, token)


def format_summary(summary: dict, token: str) -> str:
    names = [name for name in summary.get("names", []) if isinstance(name, str)]
    text = (
        f"endpoint {ALLOWED_HTTPS_ENDPOINT}\n"
        "unauth 401\n"
        f"protocol {summary.get('protocol')}\n"
        f"tools {len(names)}\n"
        + "\n".join(names)
        + "\ntools/call was not sent\n"
    )
    if token and token in text:
        raise EndpointError("refusing to print the endpoint token")
    return text
