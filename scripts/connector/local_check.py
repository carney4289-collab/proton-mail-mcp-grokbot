"""initialize and tools/list only. No tools/call and no secret output."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def _post(url: str, token: str, body: dict, session: str | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("Authorization", "Bearer " + token)
    if session:
        req.add_header("Mcp-Session-Id", session)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def initialize_and_list(endpoint: str, token: str) -> dict:
    """Return protocol version and tool names. Does not send tools/call."""
    status, headers, raw = _post(
        endpoint,
        token,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "local-check", "version": "0"},
            },
        },
    )
    if status != 200:
        raise RuntimeError("initialize failed")
    session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    if not session:
        raise RuntimeError("initialize did not return a session")
    payload = json.loads(raw)
    protocol = payload.get("result", {}).get("protocolVersion")
    status, _, raw = _post(
        endpoint,
        token,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session,
    )
    if status != 200:
        raise RuntimeError("tools/list failed")
    names = [tool.get("name") for tool in json.loads(raw).get("result", {}).get("tools", [])]
    return {"protocol": protocol, "names": names}
