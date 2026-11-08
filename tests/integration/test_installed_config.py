"""The installed package root's windows.env reaches initialize and tools/list.

The Dell failure was check-local.ps1 starting Python without loading
config/windows.env, so PROTONMAIL_USERNAME was empty even though the file
had it. Mail ports in this test are closed. No tools/call is sent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from connector.backend import StdioBackend  # noqa: E402
from connector.http_gateway import McpHttpGateway  # noqa: E402
from connector.launch import node_argv  # noqa: E402
from connector.local_check import initialize_and_list  # noqa: E402
from connector.runtime_env import child_environment  # noqa: E402
from connector.windows_env import apply_windows_env  # noqa: E402
from proton_mail_mcp_policy import FULL_ACTION_LIST  # noqa: E402

DUMMY_BRIDGE = "DUMMY-BRIDGE-SECRET-VALUE"


def _mcp_js() -> str:
    path = os.environ.get("PROTON_MCP_JS", "")
    if not path or not os.path.isfile(path):
        pytest.skip("patched proton-mail-mcp build is not present")
    return path


def _installed_env(directory: str, mcp_js: str, node_bin: str) -> str:
    config = os.path.join(directory, "config")
    os.makedirs(config, exist_ok=True)
    path = os.path.join(config, "windows.env")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    "PROTONMAIL_USERNAME=from-file@example.invalid",
                    f"NODE_BIN={node_bin}",
                    f"MCP_JS={mcp_js}",
                    "IMAP_HOST=127.0.0.1",
                    "IMAP_PORT=1",
                    "PROTONMAIL_HOST=127.0.0.1",
                    "PROTONMAIL_PORT=1",
                    "IMAP_SECURE=false",
                    "PROTONMAIL_SECURE=false",
                    "READONLY=false",
                    "PROTONMAIL_ALLOW_SEND=true",
                    "ALLOW_EMPTY_FOLDER=true",
                    "PROTONMAIL_ALLOWED_FOLDERS=*",
                    f"PROTONMAIL_ALLOWED_ACTIONS={FULL_ACTION_LIST}",
                    "",
                ]
            )
        )
    return path


def test_tools_list_uses_username_from_windows_env_file(tmp_path):
    package = tmp_path / "package root"
    package.mkdir()
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH in this test process")
    env_path = _installed_env(str(package), os.path.abspath(_mcp_js()), node)
    source: dict[str, str] = {}
    apply_windows_env(source, Path(env_path))
    assert source["PROTONMAIL_USERNAME"] == "from-file@example.invalid"
    child = child_environment(source, DUMMY_BRIDGE)
    gateway = McpHttpGateway(
        auth_token="DUMMY-ENDPOINT-AUTH-SECRET",
        backend_factory=lambda: StdioBackend(
            node_argv(source["NODE_BIN"], source["MCP_JS"]),
            child,
            secrets=(DUMMY_BRIDGE, "DUMMY-ENDPOINT-AUTH-SECRET"),
            timeout=20,
        ),
        policy_env={key: value for key, value in child.items() if "PASSWORD" not in key},
        bind_host="127.0.0.1",
        bind_port=0,
        secrets=(DUMMY_BRIDGE, "DUMMY-ENDPOINT-AUTH-SECRET"),
    )
    gateway.start()
    try:
        summary = initialize_and_list(gateway.endpoint, "DUMMY-ENDPOINT-AUTH-SECRET")
    finally:
        gateway.shutdown()
    names = [name for name in summary["names"] if isinstance(name, str)]
    assert summary["protocol"] == "2025-03-26"
    assert len(names) == 32
    assert "send_email" in names and "empty_folder" in names


def test_check_local_ps1_loads_package_windows_env(tmp_path):
    if sys.platform != "win32":
        pytest.skip("the installed PowerShell handoff is tested on Windows")
    powershell = shutil.which("powershell")
    node = shutil.which("node")
    if not powershell or not node:
        pytest.skip("powershell.exe or node is not available")
    package = tmp_path / "Grok Bot Package" / "proton-mail-mcp-windows-c28b7da"
    shutil.copytree(os.path.join(ROOT, "scripts"), package / "scripts")
    _installed_env(str(package), os.path.abspath(_mcp_js()), node)
    from connector.secrets import WindowsCredentialStore

    store = WindowsCredentialStore()
    previous_bridge = store.get("bridge-imap")
    previous_auth = store.get("http-auth")
    store.delete("bridge-imap")
    store.delete("http-auth")
    store.put("bridge-imap", DUMMY_BRIDGE)
    store.put("http-auth", "DUMMY-ENDPOINT-AUTH-SECRET")
    env = os.environ.copy()
    env.pop("PROTONMAIL_USERNAME", None)
    env.pop("NODE_BIN", None)
    env.pop("MCP_JS", None)
    env["PYTHON_EXE"] = sys.executable
    system_root = env.get("SystemRoot", r"C:\Windows")
    env["PATH"] = system_root + r"\System32"
    try:
        proc = subprocess.run(
            [powershell, "-NoProfile", "-File", str(package / "scripts" / "windows" / "check-local.ps1")],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert "PROTONMAIL_USERNAME is not set" not in proc.stderr
        assert proc.returncode == 0, proc.stderr
        assert "tools 32" in proc.stdout
        assert "tools/call was not sent" in proc.stdout
        assert "send_email" in proc.stdout
        if DUMMY_BRIDGE in proc.stdout or DUMMY_BRIDGE in proc.stderr:
            raise AssertionError("bridge credential appeared in check output")
        if "DUMMY-ENDPOINT-AUTH-SECRET" in proc.stdout or "DUMMY-ENDPOINT-AUTH-SECRET" in proc.stderr:
            raise AssertionError("http token appeared in check output")
    finally:
        if previous_bridge:
            store.put("bridge-imap", previous_bridge)
        else:
            store.delete("bridge-imap")
        if previous_auth:
            store.put("http-auth", previous_auth)
        else:
            store.delete("http-auth")
