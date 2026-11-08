"""Token generation stays out of argv, logs, and the bridge credential."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.local_check import initialize_and_list  # noqa: E402
from connector.secrets import (  # noqa: E402
    MemorySecretStore,
    SecretStoreError,
    store_generated_token,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_generated_token_is_new_and_does_not_replace_bridge_or_itself():
    store = MemorySecretStore({"bridge-imap": "BRIDGE-CREDENTIAL-UNCHANGED"})
    try:
        store_generated_token(store, "bridge-imap")
        raise AssertionError("bridge credential generation was accepted")
    except SecretStoreError as exc:
        assert "bridge" in str(exc)
    assert store.get("bridge-imap") == "BRIDGE-CREDENTIAL-UNCHANGED"
    first = store_generated_token(store, "http-auth")
    assert len(first) >= 32
    assert " " not in first and "\n" not in first
    try:
        store_generated_token(store, "http-auth")
        raise AssertionError("existing token was overwritten")
    except SecretStoreError as exc:
        assert "not overwritten" in str(exc)
        assert first not in str(exc)
    assert store.get("http-auth") == first
    second_store = MemorySecretStore({})
    second = store_generated_token(second_store, "http-auth")
    assert second != first


def test_generate_cli_output_does_not_contain_the_token_on_windows():
    if sys.platform != "win32":
        pytest.skip("Credential Manager generation is tested on Windows")
    script = os.path.join(ROOT, "scripts", "proton-mail-mcp-store.py")
    from connector.secrets import WindowsCredentialStore

    store = WindowsCredentialStore()
    store.delete("ci-dummy")
    before_bridge = store.get("bridge-imap")
    proc = subprocess.run(
        [sys.executable, script, "--generate", "ci-dummy"],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        assert proc.returncode == 0, "generate failed"
        token = store.get("ci-dummy")
        assert token and len(token) >= 32
        leaked = token in proc.stdout or token in proc.stderr or token in " ".join(proc.args)
        if leaked:
            raise AssertionError("generated token appeared in process output or argv")
        assert "stored ci-dummy" in proc.stderr
        again = subprocess.run(
            [sys.executable, script, "--generate", "ci-dummy"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert again.returncode == 2
        if token in again.stdout or token in again.stderr:
            raise AssertionError("existing token appeared while refusing overwrite")
        assert store.get("ci-dummy") == token
        refused = subprocess.run(
            [sys.executable, script, "--generate", "bridge-imap"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert refused.returncode == 2
        assert store.get("bridge-imap") == before_bridge
    finally:
        store.delete("ci-dummy")


def test_initialize_and_list_helper_never_calls_tools_call(monkeypatch):
    calls = []

    def fake_post(url, token, body, session=None):
        calls.append(body["method"])
        if body["method"] == "initialize":
            return 200, {"Mcp-Session-Id": "session-id"}, b'{"result":{"protocolVersion":"2025-03-26"}}'
        if body["method"] == "tools/list":
            return 200, {}, b'{"result":{"tools":[{"name":"list_folders"},{"name":"send_email"}]}}'
        raise AssertionError("unexpected method")

    import connector.local_check as check

    monkeypatch.setattr(check, "_post", fake_post)
    summary = initialize_and_list("http://127.0.0.1:9/mcp", "DUMMY-ENDPOINT-AUTH-SECRET")
    assert calls == ["initialize", "tools/list"]
    assert summary["names"] == ["list_folders", "send_email"]
    text = open(os.path.join(ROOT, "scripts", "proton-mail-mcp-check.py"), encoding="utf-8").read()
    assert '"method": "tools/call"' not in text
    helper = open(os.path.join(ROOT, "scripts", "windows", "new-http-auth.ps1"), encoding="utf-8").read()
    assert "--generate http-auth" in helper
    assert "Read-Host" not in helper
    assert "Out-File" not in helper
    assert "Set-Content" not in helper
