"""Real initialize and tools/list against the patched Node server.

Mail ports are closed (127.0.0.1:1). Credentials are dummy strings. This
file does not call tools/call, so it does not touch a mailbox.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from connector.backend import StdioBackend  # noqa: E402
from connector.http_gateway import McpHttpGateway  # noqa: E402
from connector.launch import node_argv  # noqa: E402
from connector.runtime_env import child_environment  # noqa: E402
from proton_mail_mcp_policy import (  # noqa: E402
    READ_TOOL_ORDER,
    full_function_env,
    visible_tool_names,
)

DUMMY_BRIDGE = "DUMMY-BRIDGE-SECRET-VALUE"
DUMMY_AUTH = "DUMMY-ENDPOINT-AUTH-SECRET"
ALL_32 = visible_tool_names(full_function_env())


def _mcp_js() -> str:
    path = os.environ.get("PROTON_MCP_JS") or os.path.join(ROOT, "build", "proton-mail-mcp", "build", "index.js")
    if not os.path.isfile(path):
        pytest.skip("patched proton-mail-mcp build is not present")
    return path


def _node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("node is not on PATH")
    return found


def _base_env() -> dict[str, str]:
    """Full-tool child env. On Windows this must keep SYSTEMROOT or Node aborts in CSPRNG."""
    source = full_function_env()
    source["IMAP_PORT"] = "1"
    source["PROTONMAIL_PORT"] = "1"
    return child_environment(source, DUMMY_BRIDGE)


def _read_line(proc: subprocess.Popen, timeout: float = 20.0) -> dict:
    """Read one stdout line. A thread is required because Windows select() ignores pipes."""
    box: dict[str, object] = {}

    def _read() -> None:
        stdout = proc.stdout
        if stdout is None:
            box["error"] = AssertionError("stdout is closed")
            return
        try:
            box["line"] = stdout.readline()
        except Exception as exc:
            box["error"] = exc

    worker = threading.Thread(target=_read, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise AssertionError("stdio server did not answer")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    line = box.get("line") or b""
    if not isinstance(line, bytes) or not line.strip():
        raise AssertionError("stdio server closed stdout")
    return json.loads(line)


def _drain(proc: subprocess.Popen) -> None:
    stderr = proc.stderr
    if stderr is None:
        return

    def _read() -> None:
        while stderr.read(4096):
            pass

    threading.Thread(target=_read, daemon=True).start()


def _stdio_tools(env: dict[str, str]) -> list[str]:
    proc = subprocess.Popen(
        [_node(), _mcp_js()],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        shell=False,
    )
    assert proc.stdin is not None
    _drain(proc)
    try:
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "stdio-integration", "version": "0"},
                    },
                }
            ).encode()
            + b"\n"
        )
        proc.stdin.flush()
        init = _read_line(proc)
        assert init["result"]["serverInfo"]["name"] == "proton-mail-mcp"
        assert init["result"]["protocolVersion"] == "2025-03-26"
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        proc.stdin.write(
            b'{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n'
        )
        proc.stdin.flush()
        listed = _read_line(proc)
        return [tool["name"] for tool in listed["result"]["tools"]]
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_stdio_full_list_and_all_token_and_narrow_defaults():
    full = _base_env()
    assert sorted(_stdio_tools(full)) == sorted(ALL_32)
    all_token = dict(full)
    all_token["PROTONMAIL_ALLOWED_ACTIONS"] = "ALL"
    all_token["PROTONMAIL_ALLOWED_FOLDERS"] = "ALL"
    assert sorted(_stdio_tools(all_token)) == sorted(ALL_32)
    narrow = dict(full)
    narrow["PROTONMAIL_ALLOW_SEND"] = "false"
    narrow["ALLOW_EMPTY_FOLDER"] = "false"
    narrow["PROTONMAIL_ALLOWED_ACTIONS"] = (
        "save_draft,update_message_flags,mark_all_read,move_message,update_message_labels"
    )
    narrow_names = _stdio_tools(narrow)
    assert "send_email" not in narrow_names
    assert "save_draft" in narrow_names
    assert len(narrow_names) == 15
    readonly = dict(full)
    readonly["READONLY"] = "true"
    assert sorted(_stdio_tools(readonly)) == sorted(READ_TOOL_ORDER)


def _http_names(env: dict[str, str]) -> list[str]:
    child_env = dict(env)
    policy = {key: value for key, value in child_env.items() if "PASSWORD" not in key}
    node_dir = os.path.dirname(_node())

    def factory():
        return StdioBackend(
            node_argv(node_dir, _mcp_js()),
            child_env,
            secrets=(DUMMY_BRIDGE, DUMMY_AUTH),
            timeout=20,
        )

    gateway = McpHttpGateway(
        auth_token=DUMMY_AUTH,
        backend_factory=factory,
        policy_env=policy,
        bind_host="127.0.0.1",
        bind_port=0,
        secrets=(DUMMY_BRIDGE, DUMMY_AUTH),
    )
    gateway.start()
    try:
        def post(body, token=DUMMY_AUTH, session=None):
            req = urllib.request.Request(gateway.endpoint, data=json.dumps(body).encode(), method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json, text/event-stream")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            if session:
                req.add_header("Mcp-Session-Id", session)
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return resp.status, dict(resp.headers), resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, dict(exc.headers), exc.read()

        status, _, denied = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, token=None)
        assert status == 401
        assert DUMMY_BRIDGE.encode() not in denied
        assert gateway.spawns == 0
        status, headers, body = post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "http-integration", "version": "0"},
                },
            }
        )
        assert status == 200, body
        assert DUMMY_BRIDGE.encode() not in body
        session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        status, _, listed = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session=session)
        assert status == 200, listed
        return sorted(tool["name"] for tool in json.loads(listed)["result"]["tools"])
    finally:
        gateway.shutdown()


def test_authenticated_http_lists_the_same_32_tools():
    assert _http_names(_base_env()) == sorted(ALL_32)


def test_linux_stdio_wrapper_still_lists_32_with_full_env():
    if os.name == "nt":
        pytest.skip(
            "proton-mail-mcp-wrapper.py waits on stdio with select(), and Windows "
            "select() cannot wait on pipes. The Windows process is the loopback HTTP "
            "connector, covered by the other tests in this file."
        )
    wrapper = os.path.join(ROOT, "scripts", "proton-mail-mcp-wrapper.py")
    env = _base_env()
    env["NODE_BIN"] = os.path.dirname(_node())
    env["MCP_JS"] = _mcp_js()
    env["HOME"] = os.environ.get("HOME", "/tmp")
    proc = subprocess.Popen(
        [sys.executable, wrapper],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        shell=False,
    )
    assert proc.stdin is not None
    _drain(proc)
    try:
        if os.path.exists(f"/proc/{proc.pid}/cmdline"):
            cmdline = open(f"/proc/{proc.pid}/cmdline", "rb").read().decode("utf-8", "replace")
            assert DUMMY_BRIDGE not in cmdline
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "wrapper", "version": "0"},
                    },
                }
            ).encode()
            + b"\n"
        )
        proc.stdin.flush()
        init = _read_line(proc)
        assert init["result"]["protocolVersion"] == "2025-03-26"
        proc.stdin.write(b'{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n')
        proc.stdin.flush()
        listed = _read_line(proc)
        names = [tool["name"] for tool in listed["result"]["tools"]]
        assert sorted(names) == sorted(ALL_32)
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_official_streamable_http_client_both_eras():
    client_root = os.path.join(ROOT, "build", "proton-mail-mcp")
    if not os.path.isdir(os.path.join(client_root, "node_modules", "@modelcontextprotocol", "client")):
        pytest.skip("MCP client package is not installed in the pinned build")
    env = _base_env()
    node_dir = os.path.dirname(_node())

    def factory():
        return StdioBackend(node_argv(node_dir, _mcp_js()), env, secrets=(DUMMY_BRIDGE, DUMMY_AUTH), timeout=20)

    gateway = McpHttpGateway(
        auth_token=DUMMY_AUTH,
        backend_factory=factory,
        policy_env={key: value for key, value in env.items() if "PASSWORD" not in key},
        bind_host="127.0.0.1",
        bind_port=0,
        secrets=(DUMMY_BRIDGE, DUMMY_AUTH),
    )
    gateway.start()
    probe = os.path.join(ROOT, "tests", "probes", "http_roundtrip.mjs")
    probe_copy = os.path.join(client_root, "http_roundtrip.mjs")
    shutil.copyfile(probe, probe_copy)
    try:
        for era in ("legacy", "modern"):
            probe_env = os.environ.copy()
            probe_env["MCP_URL"] = gateway.endpoint
            probe_env["MCP_HTTP_TOKEN"] = DUMMY_AUTH
            probe_env["MCP_ERA"] = era
            proc = subprocess.run(
                [_node(), probe_copy],
                check=False,
                capture_output=True,
                text=True,
                cwd=client_root,
                env=probe_env,
            )
            assert proc.returncode == 0, proc.stderr
            assert DUMMY_AUTH not in proc.stdout
            assert DUMMY_BRIDGE not in proc.stdout
            assert DUMMY_AUTH not in proc.stderr
            payload = json.loads(proc.stdout)
            assert payload["count"] == 32
            assert payload["names"] == sorted(ALL_32)
            assert payload["era"] == ("modern" if era == "modern" else "legacy")
    finally:
        gateway.shutdown()
