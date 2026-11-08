"""Private HTTPS checks: one host, no redirects, no tools/call, TLS stays on."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.https_check import (  # noqa: E402
    ALLOWED_HTTPS_ENDPOINT,
    EndpointError,
    format_summary,
    post_on_connection,
    public_tls_context,
    run_protocol,
    validate_private_https_endpoint,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOKEN = "DUMMY-HTTPS-CHECK-TOKEN-VALUE"


def test_only_the_private_tailscale_url_is_accepted():
    assert validate_private_https_endpoint(ALLOWED_HTTPS_ENDPOINT) == ALLOWED_HTTPS_ENDPOINT
    assert validate_private_https_endpoint("https://Dell-Sean.tail545f1e.ts.net/mcp") == ALLOWED_HTTPS_ENDPOINT
    rejected = [
        "http://dell-sean.tail545f1e.ts.net/mcp",
        "https://dell-sean.tail545f1e.ts.net:8443/mcp",
        "https://dell-sean.tail545f1e.ts.net/mcp?x=1",
        "https://dell-sean.tail545f1e.ts.net/mcp#frag",
        "https://dell-sean.tail545f1e.ts.net/other",
        "https://user:secret-in-url@dell-sean.tail545f1e.ts.net/mcp",
        "https://127.0.0.1/mcp",
        "https://evil.example/mcp",
        "https://dell-sean.tail545f1e.ts.net.evil.example/mcp",
    ]
    for url in rejected:
        try:
            validate_private_https_endpoint(url)
            raise AssertionError("accepted " + url.split("@")[-1])
        except EndpointError:
            pass


def test_endpoint_cli_does_not_echo_a_url_secret():
    script = os.path.join(ROOT, "scripts", "proton-mail-mcp-check-endpoint.py")
    planted = "secret-in-url"
    proc = subprocess.run(
        [
            sys.executable,
            script,
            "--endpoint",
            f"https://user:{planted}@dell-sean.tail545f1e.ts.net/mcp",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    if planted in proc.stdout or planted in proc.stderr:
        raise AssertionError("credential embedded in the URL was written to the output")
    assert "endpoint rejected" in proc.stderr
    source = open(script, encoding="utf-8").read()
    assert "BRIDGE_IMAP" not in source
    assert "tools/call" not in source


def test_public_tls_context_verifies_certificates():
    context = public_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_redirect_is_not_followed_and_authorization_stays_on_the_first_host():
    sink_hits: list[str | None] = []

    class Sink(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            self.rfile.read(length)
            sink_hits.append(self.headers.get("Authorization"))
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    sink = ThreadingHTTPServer(("127.0.0.1", 0), Sink)
    sink_thread = threading.Thread(target=sink.serve_forever, daemon=True)
    sink_thread.start()
    first_hits: list[str | None] = []

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            self.rfile.read(length)
            first_hits.append(self.headers.get("Authorization"))
            location = f"http://127.0.0.1:{sink.server_address[1]}/mcp"
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    first = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    first_thread = threading.Thread(target=first.serve_forever, daemon=True)
    first_thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", first.server_address[1], timeout=5)
        try:
            post_on_connection(
                conn,
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                token=TOKEN,
                session=None,
            )
            raise AssertionError("redirect was accepted")
        except EndpointError as exc:
            assert "redirect" in str(exc)
            assert TOKEN not in str(exc)
        finally:
            conn.close()
        assert first_hits == ["Bearer " + TOKEN]
        assert sink_hits == []
    finally:
        first.shutdown()
        sink.shutdown()


def test_protocol_is_only_initialize_initialized_and_tools_list():
    seen: list[tuple[str, bool]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            body = json.loads(self.rfile.read(length))
            method = body.get("method")
            authed = self.headers.get("Authorization") is not None
            seen.append((method, authed))
            if method == "tools/call":
                raise AssertionError("tools/call was sent")
            if not authed:
                raw = b""
                status = 401
            elif method == "initialize":
                status = 200
                raw = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"protocolVersion": "2025-03-26"},
                    }
                ).encode()
            elif method == "notifications/initialized":
                status = 202
                raw = b""
            elif method == "tools/list":
                status = 200
                raw = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {"tools": [{"name": "list_folders"}, {"name": "send_email"}]},
                    }
                ).encode()
            else:
                status = 400
                raw = b""
            self.send_response(status)
            if method == "initialize" and authed:
                self.send_header("Mcp-Session-Id", "session-id")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def exchange(body: dict, token: str | None, session: str | None) -> tuple[int, dict, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            return post_on_connection(conn, body, token=token, session=session)
        finally:
            conn.close()

    try:
        summary = run_protocol(exchange, TOKEN)
    finally:
        server.shutdown()
    assert seen == [
        ("initialize", False),
        ("initialize", True),
        ("notifications/initialized", True),
        ("tools/list", True),
    ]
    text = format_summary(summary, TOKEN)
    assert "tools 2" in text
    assert "tools/call was not sent" in text
    if TOKEN in text:
        raise AssertionError("token appeared in the summary")


def test_default_tls_rejects_a_self_signed_certificate(tmp_path):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl is not available to mint a throwaway certificate")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            self.rfile.read(length)
            raw = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPSConnection(
            "127.0.0.1",
            server.server_address[1],
            timeout=5,
            context=public_tls_context(),
        )
        try:
            post_on_connection(
                conn,
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                token=TOKEN,
                session=None,
            )
            raise AssertionError("self-signed certificate was accepted")
        except ssl.SSLError:
            pass
        finally:
            conn.close()
    finally:
        server.shutdown()


def test_powershell_rejects_any_other_endpoint_on_windows():
    if sys.platform != "win32":
        pytest.skip("PowerShell endpoint guard is tested on Windows")
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("powershell.exe is not available")
    script = os.path.join(ROOT, "scripts", "windows", "check-endpoint.ps1")
    proc = subprocess.run(
        [powershell, "-NoProfile", "-File", script, "-Endpoint", "http://127.0.0.1:8765/mcp"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert TOKEN not in proc.stdout and TOKEN not in proc.stderr
