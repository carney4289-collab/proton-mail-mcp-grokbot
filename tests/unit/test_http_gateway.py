"""Authenticated loopback HTTP against a mock stdio backend. No mail server."""
from __future__ import annotations

import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.backend import BackendError
from connector.http_gateway import McpHttpGateway, parse_bearer, validate_extra_hosts  # noqa: E402
from proton_mail_mcp_policy import (  # noqa: E402
    READ_TOOL_ORDER,
    full_function_env,
    visible_tool_names,
)

DUMMY_AUTH = "DUMMY-ENDPOINT-AUTH-SECRET"
DUMMY_BRIDGE = "DUMMY-BRIDGE-SECRET-VALUE"
ALL_32 = visible_tool_names(full_function_env())


class MockBackend:
    def __init__(self, label: str, tools: list[str]) -> None:
        self.label = label
        self.calls: list[dict] = []
        self.closed = False
        self._tools = tools

    def exchange(self, message: dict) -> dict | None:
        self.calls.append(message)
        if "id" not in message:
            return None
        method = message.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "proton-mail-mcp", "version": "1.0.2"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": [{"name": name, "description": name, "inputSchema": {"type": "object"}} for name in self._tools]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": f"mock-{self.label}"}]}
        else:
            result = {"ok": True}
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def close(self) -> None:
        self.closed = True


def _request(url, *, method="POST", token=None, body=None, session=None, extra=None, host=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if session:
        req.add_header("Mcp-Session-Id", session)
    for key, value in (extra or {}).items():
        req.add_header(key, value)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _gateway(**kwargs):
    created: list[MockBackend] = []

    def factory():
        backend = MockBackend(str(len(created) + 1), list(ALL_32))
        created.append(backend)
        return backend

    gateway = McpHttpGateway(
        auth_token=DUMMY_AUTH,
        backend_factory=factory,
        policy_env=kwargs.pop("policy_env", full_function_env()),
        bind_host="127.0.0.1",
        bind_port=0,
        secrets=(DUMMY_BRIDGE, DUMMY_AUTH),
        log=kwargs.pop("log", lambda _line: None),
        **kwargs,
    )
    gateway.start()
    return gateway, created


def test_parse_bearer_and_extra_hosts():
    assert parse_bearer(f"Bearer {DUMMY_AUTH}") == DUMMY_AUTH
    assert parse_bearer("Basic abc") is None
    assert parse_bearer("Bearer") is None
    assert parse_bearer("Bearer bad\ntoken") is None
    try:
        validate_extra_hosts("*.example.com")
        raise AssertionError("wildcard host was accepted")
    except Exception:
        pass
    try:
        validate_extra_hosts("0.0.0.0:8765")
        raise AssertionError("wildcard bind host was accepted")
    except Exception:
        pass


def test_refuses_non_loopback_bind():
    try:
        McpHttpGateway(
            auth_token=DUMMY_AUTH,
            backend_factory=MockBackend,
            policy_env=full_function_env(),
            bind_host="0.0.0.0",
            bind_port=0,
        )
        raise AssertionError("public bind was accepted")
    except Exception as exc:
        assert "loopback" in str(exc)


def test_unauthenticated_and_bad_token_never_reach_the_backend():
    gateway, created = _gateway()
    try:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        status, headers, body = _request(gateway.endpoint, body=init)
        assert status == 401
        assert b"WWW-Authenticate" in str(headers).encode() or "WWW-Authenticate" in headers or "www-authenticate" in {k.lower() for k in headers}
        assert DUMMY_AUTH.encode() not in body
        assert DUMMY_BRIDGE.encode() not in body
        status, _, body = _request(gateway.endpoint, token="WRONG-TOKEN-VALUE-HERE", body=init)
        assert status == 401
        assert DUMMY_BRIDGE.encode() not in body
        status, _, _ = _request(
            gateway.endpoint + "?access_token=" + DUMMY_AUTH,
            body=init,
            extra={"Tailscale-User-Login": "sean@example.invalid"},
        )
        assert status == 401
        assert created == []
        assert gateway.spawns == 0
    finally:
        gateway.shutdown()


def test_discover_probe_is_authenticated_and_does_not_keep_a_session():
    gateway, created = _gateway()
    try:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}},
        }
        status, _, raw = _request(gateway.endpoint, body=body)
        assert status == 401
        assert created == []
        status, headers, raw = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            body=body,
            extra={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "server/discover"},
        )
        assert status == 200, raw
        assert not (headers.get("Mcp-Session-Id") or headers.get("mcp-session-id"))
        assert created[0].calls[0]["method"] == "server/discover"
        for _ in range(50):
            if created[0].closed:
                break
            time.sleep(0.02)
        assert created[0].closed
        assert gateway.spawns == 1
    finally:
        gateway.shutdown()


def test_keepalive_discover_then_tools_list_shares_one_backend():
    gateway, created = _gateway()
    try:
        port = gateway.bind_port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {DUMMY_AUTH}",
            "Connection": "keep-alive",
        }
        discover = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}},
            }
        )
        conn.request("POST", "/mcp", body=discover, headers=headers)
        first = conn.getresponse()
        assert first.status == 200
        first.read()
        listed = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        conn.request("POST", "/mcp", body=listed, headers=headers)
        second = conn.getresponse()
        body = second.read()
        conn.close()
        assert second.status == 200, body
        names = [tool["name"] for tool in json.loads(body)["result"]["tools"]]
        assert names == ALL_32
        assert gateway.spawns == 1
        assert len(created) == 1
        assert [call["method"] for call in created[0].calls] == ["server/discover", "tools/list"]
    finally:
        gateway.shutdown()


def test_initialize_and_tools_list_return_the_32_names():
    logs: list[str] = []
    gateway, created = _gateway(log=logs.append)
    try:
        status, headers, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            body={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "mock", "version": "0"},
                },
            },
        )
        assert status == 200
        session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        assert session
        payload = json.loads(body)
        assert payload["result"]["serverInfo"]["name"] == "proton-mail-mcp"
        status, _, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=session,
            body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert status == 202
        status, _, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=session,
            body={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        )
        assert status == 200
        names = [tool["name"] for tool in json.loads(body)["result"]["tools"]]
        assert names == ALL_32
        assert len(names) == 32
        assert gateway.spawns == 1
        assert DUMMY_AUTH.encode() not in body
        assert all(DUMMY_AUTH not in line and DUMMY_BRIDGE not in line for line in logs)
    finally:
        gateway.shutdown()


def test_invalid_session_and_hidden_tool_do_not_call_backend():
    gateway, created = _gateway(policy_env={"READONLY": "false", "PROTONMAIL_ALLOW_SEND": "false", "PROTONMAIL_ALLOWED_ACTIONS": "ALL", "ALLOW_EMPTY_FOLDER": "false"})
    try:
        status, headers, _ = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        status, _, _ = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session="not-a-real-session",
            body={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert status == 404
        before = len(created[0].calls)
        status, _, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=session,
            body={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "send_email", "arguments": {"to": "a@example.invalid", "subject": "x"}},
            },
        )
        assert status == 200
        assert json.loads(body)["error"]["code"] == -32601
        assert len(created[0].calls) == before
        status, _, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=session,
            body={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "list_folders", "arguments": {}},
            },
        )
        assert status == 200
        assert json.loads(body)["result"]["content"][0]["text"] == "mock-1"
        assert created[0].calls[-1]["method"] == "tools/call"
    finally:
        gateway.shutdown()


def test_sessions_are_isolated_and_delete_closes_backend():
    gateway, created = _gateway()
    try:
        def open_session():
            status, headers, _ = _request(
                gateway.endpoint,
                token=DUMMY_AUTH,
                body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            assert status == 200
            return headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")

        first = open_session()
        second = open_session()
        _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=first,
            body={"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "list_folders", "arguments": {}}},
        )
        assert created[0].calls[-1]["id"] == 9
        assert all(call.get("id") != 9 for call in created[1].calls)
        status, _, _ = _request(gateway.endpoint, method="DELETE", token=DUMMY_AUTH, session=first)
        assert status == 204
        assert created[0].closed
        assert not created[1].closed
    finally:
        gateway.shutdown()
        assert created[1].closed


def test_origin_host_and_header_mismatch_fail_closed():
    gateway, created = _gateway()
    try:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        status, _, _ = _request(gateway.endpoint, token=DUMMY_AUTH, body=init, extra={"Origin": "https://evil.example"})
        assert status == 403
        status, _, _ = _request(gateway.endpoint, token=DUMMY_AUTH, body=init, extra={"Origin": "null"})
        assert status == 403
        status, _, _ = _request(gateway.endpoint, token=DUMMY_AUTH, body=init, host="evil.example")
        assert status == 403
        assert gateway.spawns == 0
        status, headers, _ = _request(gateway.endpoint, token=DUMMY_AUTH, body=init)
        assert status == 200
        session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        status, _, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=session,
            body={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}},
            },
            extra={"MCP-Protocol-Version": "2025-03-26", "Mcp-Method": "tools/call"},
        )
        assert status == 400
        assert b"tools/list" not in body or b"does not match" in body
        assert all(call.get("method") != "tools/list" for call in created[0].calls)
    finally:
        gateway.shutdown()


def test_narrow_policy_filters_the_mock_catalog():
    env = {
        "READONLY": "true",
        "PROTONMAIL_ALLOW_SEND": "true",
        "PROTONMAIL_ALLOWED_ACTIONS": "ALL",
        "ALLOW_EMPTY_FOLDER": "true",
    }
    gateway, _created = _gateway(policy_env=env)
    try:
        status, headers, _ = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        _, _, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=session,
            body={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        names = [tool["name"] for tool in json.loads(body)["result"]["tools"]]
        assert names == list(READ_TOOL_ORDER)
    finally:
        gateway.shutdown()


def test_idle_session_is_closed():
    gateway, created = _gateway(idle_timeout=0.05)
    try:
        _, headers, _ = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        time.sleep(0.12)
        status, _, _ = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            session=session,
            body={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert status == 404
        assert created[0].closed
    finally:
        gateway.shutdown()


def test_backend_failure_response_does_not_echo_the_secret():
    def factory():
        raise RuntimeError(DUMMY_BRIDGE)

    gateway = McpHttpGateway(
        auth_token=DUMMY_AUTH,
        backend_factory=factory,
        policy_env=full_function_env(),
        bind_host="127.0.0.1",
        bind_port=0,
        secrets=(DUMMY_BRIDGE, DUMMY_AUTH),
    )
    gateway.start()
    try:
        status, _, body = _request(
            gateway.endpoint,
            token=DUMMY_AUTH,
            body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert status == 502
        assert DUMMY_BRIDGE.encode() not in body
        assert gateway.spawns == 0
    finally:
        gateway.shutdown()


def test_tools_call_backend_error_is_named_without_the_secret():
    class TimedOut(MockBackend):
        def exchange(self, message: dict) -> dict | None:
            if message.get("method") == "tools/call":
                raise BackendError("backend timed out")
            return super().exchange(message)

    class Leaks(MockBackend):
        def exchange(self, message: dict) -> dict | None:
            if message.get("method") == "tools/call":
                raise BackendError(DUMMY_BRIDGE)
            return super().exchange(message)

    def run(backend_cls: type[MockBackend]) -> bytes:
        def factory():
            return backend_cls("1", list(ALL_32))

        gateway = McpHttpGateway(
            auth_token=DUMMY_AUTH,
            backend_factory=factory,
            policy_env=full_function_env(),
            bind_host="127.0.0.1",
            bind_port=0,
            secrets=(DUMMY_BRIDGE, DUMMY_AUTH),
        )
        gateway.start()
        try:
            status, headers, _ = _request(
                gateway.endpoint,
                token=DUMMY_AUTH,
                body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            assert status == 200
            session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
            status, _, body = _request(
                gateway.endpoint,
                token=DUMMY_AUTH,
                session=session,
                body={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "read_message", "arguments": {"uid": 5359}},
                },
            )
            assert status == 502
            return body
        finally:
            gateway.shutdown()

    timed = run(TimedOut)
    assert b"backend timed out" in timed
    assert DUMMY_BRIDGE.encode() not in timed
    leaked = run(Leaks)
    assert DUMMY_BRIDGE.encode() not in leaked
    assert b"backend failure" in leaked
