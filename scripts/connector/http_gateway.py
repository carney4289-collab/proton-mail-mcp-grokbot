"""Authenticated loopback Streamable HTTP gateway in front of stdio MCP.

Bearer auth is checked before any backend is created. Tailscale identity
headers are not credentials. Tool registration is not per-message approval.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from connector.redact import redact
from connector.secrets import tokens_equal
from proton_mail_mcp_policy import apply_call_guards, is_hidden_tool

MAX_BODY = 8 * 1024 * 1024
MAX_SESSIONS = 8
SESSION_HEADER = "Mcp-Session-Id"
PROTOCOL_META = "io.modelcontextprotocol/protocolVersion"

BackendFactory = Callable[[], Any]


class GatewayError(RuntimeError):
    pass


def _media_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
        return None
    return token


def host_allowed(host_header: str | None, port: int, extra_hosts: tuple[str, ...] = ()) -> bool:
    if not host_header:
        return False
    host = host_header.strip().lower()
    if any(ch in host for ch in " \t\r\n@/\\"):
        return False
    allowed = {
        f"127.0.0.1:{port}",
        f"localhost:{port}",
        f"[::1]:{port}",
        *extra_hosts,
    }
    return host in allowed


def origin_allowed(origin: str | None, port: int) -> bool:
    if origin is None or origin == "":
        return True
    value = origin.strip().lower().rstrip("/")
    if value in {"null", "undefined"}:
        return False
    allowed = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://[::1]:{port}",
    }
    return value in allowed


def validate_extra_hosts(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    hosts = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    for host in hosts:
        if any(ch in host for ch in "* \t\r\n@/\\"):
            raise GatewayError("extra host contains a wildcard or delimiter")
        if host.startswith("0.0.0.0") or host.startswith("[::]"):
            raise GatewayError("extra host is not a specific name")
    return hosts


def _session_id_ok(value: str) -> bool:
    return 8 <= len(value) <= 128 and all(33 <= ord(ch) <= 126 for ch in value)


class _Session:
    def __init__(self, sid: str, backend: Any) -> None:
        self.id = sid
        self.backend = backend
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        # True once the client was given Mcp-Session-Id and may reconnect.
        self.published = False


class McpHttpGateway:
    def __init__(
        self,
        *,
        auth_token: str,
        backend_factory: BackendFactory,
        policy_env: dict[str, str],
        bind_host: str = "127.0.0.1",
        bind_port: int = 8765,
        extra_hosts: tuple[str, ...] = (),
        secrets: tuple[str, ...] = (),
        log: Callable[[str], None] | None = None,
        idle_timeout: float = 30 * 60,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        if bind_host not in {"127.0.0.1", "::1"}:
            raise GatewayError("listener must bind to loopback")
        if not auth_token or len(auth_token) < 16:
            raise GatewayError("endpoint auth secret is missing or too short")
        self._auth_token = auth_token
        self._factory = backend_factory
        self._policy_env = dict(policy_env)
        self._extra_hosts = extra_hosts
        self._secrets = secrets + (auth_token,)
        self._log = log or (lambda _message: None)
        self._idle_timeout = idle_timeout
        self._max_sessions = max_sessions
        self._sessions: dict[str, _Session | None] = {}
        self._lock = threading.Lock()
        self._spawns = 0
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((bind_host, bind_port), handler)
        self._httpd.daemon_threads = True
        self.bind_host, self.bind_port = self._httpd.server_address[:2]
        if self.bind_host not in {"127.0.0.1", "::1"}:
            self._httpd.server_close()
            raise GatewayError("listener did not bind to loopback")

    @property
    def spawns(self) -> int:
        return self._spawns

    @property
    def endpoint(self) -> str:
        host = self.bind_host
        if host == "::1":
            host = "[::1]"
        return f"http://{host}:{self.bind_port}/mcp"

    def start(self) -> None:
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def serve_forever(self) -> None:
        try:
            self._httpd.serve_forever()
        finally:
            self.close()

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self.close()

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            if session is not None:
                session.backend.close()
        self._httpd.server_close()

    def log(self, message: str) -> None:
        self._log(redact(message, self._secrets))

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                gateway.log("http " + (fmt % args))

            def do_POST(self) -> None:  # noqa: N802
                gateway.handle_post(self)

            def do_GET(self) -> None:  # noqa: N802
                gateway.handle_get(self)

            def do_DELETE(self) -> None:  # noqa: N802
                gateway.handle_delete(self)

            def do_OPTIONS(self) -> None:  # noqa: N802
                gateway._send(self, 405, {"error": "method not allowed"})

            def handle(self) -> None:
                try:
                    super().handle()
                finally:
                    gateway.release_connection(self)

        return Handler

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        """2025 clients open a server SSE stream. 405 tells them we do not keep one."""
        if not self._preamble(handler, read_body=False):
            return
        session = self._existing_session(handler, required=False)
        if session is None and handler.headers.get(SESSION_HEADER):
            return
        self._send(handler, 405, {"error": "server stream is not offered"})

    def handle_delete(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._preamble(handler, read_body=False):
            return
        session = self._existing_session(handler, required=True)
        if session is None:
            return
        self._drop_session(session.id)
        self._send(handler, 204, None)

    def handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._preamble(handler, read_body=False):
            return
        body = self._read_body(handler)
        if body is None:
            return
        try:
            message = json.loads(body)
        except json.JSONDecodeError:
            self._send(handler, 400, {"error": "malformed json"})
            return
        if not isinstance(message, dict):
            self._send(handler, 400, {"error": "json-rpc batch is not accepted"})
            return
        mismatch = self._header_mismatch(handler, message)
        if mismatch:
            self._send(handler, 400, {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32600, "message": mismatch}})
            return
        method = message.get("method")
        if not isinstance(method, str) or not method or len(method) > 128:
            self._send(handler, 400, {"error": "missing method"})
            return
        accept = handler.headers.get("Accept", "")
        if "application/json" not in accept.lower():
            self._send(handler, 406, {"error": "accept must include application/json"})
            return
        if method == "initialize":
            self._initialize(handler, message)
            return
        # A keep-alive connection reuses the backend started by its first call.
        # 2025 clients instead send Mcp-Session-Id on later connections.
        # 2026 clients do neither: each POST is its own Node process. The
        # pinned server answers tools/list on a fresh process when the
        # request carries a 2026 envelope.
        bound = getattr(handler, "_mcp_session", None)
        if not isinstance(bound, _Session):
            if handler.headers.get(SESSION_HEADER):
                bound = self._existing_session(handler, required=True)
                if not isinstance(bound, _Session):
                    return
            else:
                self._bind_new_session(handler, publish=False)
                bound = getattr(handler, "_mcp_session", None)
                if not isinstance(bound, _Session):
                    return
        self._dispatch(handler, bound, message)

    def _bind_new_session(self, handler: BaseHTTPRequestHandler, *, publish: bool) -> None:
        try:
            session = self._open_session()
        except Exception:
            self.log("backend start failed")
            self._send(handler, 502, {"error": "backend failure"})
            return
        if session is None:
            self._send(handler, 503, {"error": "too many sessions"})
            return
        session.published = publish
        handler._mcp_session = session

    def release_connection(self, handler: BaseHTTPRequestHandler) -> None:
        session = getattr(handler, "_mcp_session", None)
        if isinstance(session, _Session) and not session.published:
            self._drop_session(session.id)

    def _initialize(self, handler: BaseHTTPRequestHandler, message: dict) -> None:
        try:
            session = self._open_session()
        except Exception:
            self.log("backend start failed")
            self._send(handler, 502, {"error": "backend failure"})
            return
        if session is None:
            self._send(handler, 503, {"error": "too many sessions"})
            return
        try:
            response = session.backend.exchange(message)
        except Exception:
            self.log("initialize failed: backend error")
            self._drop_session(session.id)
            self._send(handler, 502, {"error": "backend failure"})
            return
        if not isinstance(response, dict):
            self._drop_session(session.id)
            self._send(handler, 502, {"error": "backend failure"})
            return
        session.published = True
        handler._mcp_session = session
        self._send(handler, 200, response, {SESSION_HEADER: session.id})

    def _dispatch(self, handler: BaseHTTPRequestHandler, session: _Session, message: dict) -> None:
        method = str(message.get("method"))
        if method == "tools/call":
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            blocked = apply_call_guards(name, arguments, self._policy_env)
            if blocked:
                self._send(
                    handler,
                    200,
                    {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32601, "message": blocked}},
                )
                return
            params = dict(params)
            params["arguments"] = arguments
            message = dict(message)
            message["params"] = params
        try:
            with session.lock:
                session.last_used = time.monotonic()
                response = session.backend.exchange(message)
        except Exception:
            self.log(f"backend error during {method}")
            self._send(handler, 502, {"error": "backend failure"})
            return
        if response is None:
            self._send(handler, 202, None)
            return
        if method == "tools/list" and isinstance(response.get("result"), dict):
            tools = response["result"].get("tools")
            if isinstance(tools, list):
                response["result"]["tools"] = [
                    tool
                    for tool in tools
                    if not (isinstance(tool, dict) and is_hidden_tool(str(tool.get("name", "")), self._policy_env))
                ]
        self._send(handler, 200, response)

    def _open_session(self) -> _Session | None:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._reap_locked()
            if len(self._sessions) >= self._max_sessions:
                return None
            self._sessions[sid] = None
        try:
            backend = self._factory()
            self._spawns += 1
        except Exception:
            self.log("backend start failed")
            with self._lock:
                self._sessions.pop(sid, None)
            raise
        session = _Session(sid, backend)
        with self._lock:
            self._sessions[sid] = session
        self.log("session started")
        return session

    def _existing_session(self, handler: BaseHTTPRequestHandler, *, required: bool) -> _Session | None:
        raw = handler.headers.get(SESSION_HEADER)
        if not raw:
            if required:
                self._send(handler, 400, {"error": "session required"})
            return None
        if not _session_id_ok(raw):
            self._send(handler, 400, {"error": "malformed session"})
            return None
        with self._lock:
            self._reap_locked()
            session = self._sessions.get(raw)
        if session is None:
            self._send(handler, 404, {"error": "session not found"})
            return None
        return session

    def _drop_session(self, sid: str) -> None:
        with self._lock:
            session = self._sessions.pop(sid, None)
        if session is not None:
            session.backend.close()
            self.log("session closed")

    def _reap_locked(self) -> None:
        now = time.monotonic()
        stale = [
            sid
            for sid, session in self._sessions.items()
            if session is not None and now - session.last_used > self._idle_timeout
        ]
        for sid in stale:
            session = self._sessions.pop(sid, None)
            if session is not None:
                session.backend.close()

    def _preamble(self, handler: BaseHTTPRequestHandler, *, read_body: bool) -> bool:
        if handler.path.split("?", 1)[0] != "/mcp":
            self._send(handler, 404, {"error": "not found"})
            return False
        if handler.headers.get("Transfer-Encoding"):
            self._send(handler, 400, {"error": "chunked bodies are not accepted"})
            return False
        length = handler.headers.get("Content-Length")
        if length is not None:
            try:
                size = int(length)
            except ValueError:
                self._send(handler, 400, {"error": "bad content length"})
                return False
            if size > MAX_BODY:
                self._send(handler, 413, {"error": "body too large"})
                return False
        if not host_allowed(handler.headers.get("Host"), int(self.bind_port), self._extra_hosts):
            self._send(handler, 403, {"error": "host not allowed"})
            return False
        if not origin_allowed(handler.headers.get("Origin"), int(self.bind_port)):
            self._send(handler, 403, {"error": "origin not allowed"})
            return False
        presented = parse_bearer(handler.headers.get("Authorization"))
        if presented is None or not tokens_equal(presented, self._auth_token):
            self.log("authentication failed")
            self._send(handler, 401, {"error": "unauthorized"}, {"WWW-Authenticate": 'Bearer realm="proton-mail-mcp"'})
            return False
        if read_body:
            return self._read_body(handler) is not None
        return True

    def _read_body(self, handler: BaseHTTPRequestHandler) -> bytes | None:
        length = handler.headers.get("Content-Length")
        if length is None:
            self._send(handler, 411, {"error": "content length required"})
            return None
        size = int(length)
        if size > MAX_BODY:
            self._send(handler, 413, {"error": "body too large"})
            return None
        body = handler.rfile.read(size) if size else b""
        if len(body) != size:
            self._send(handler, 400, {"error": "truncated body"})
            return None
        content_type = _media_type(handler.headers.get("Content-Type"))
        if content_type != "application/json":
            self._send(handler, 415, {"error": "content type must be application/json"})
            return None
        return body

    def _header_mismatch(self, handler: BaseHTTPRequestHandler, message: dict) -> str | None:
        method_header = handler.headers.get("Mcp-Method")
        method = message.get("method")
        if method_header and method_header != method:
            return "mcp-method does not match the body"
        version_header = handler.headers.get("MCP-Protocol-Version")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        claimed = meta.get(PROTOCOL_META)
        if version_header and isinstance(claimed, str) and version_header != claimed:
            return "protocol version header does not match the body"
        return None

    def _send(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        payload: dict | None,
        extra: dict[str, str] | None = None,
    ) -> None:
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        if payload is not None:
            handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        if status in (401, 403):
            handler.send_header("Connection", "close")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            handler.send_header(key, value)
        handler.end_headers()
        if body:
            handler.wfile.write(body)
