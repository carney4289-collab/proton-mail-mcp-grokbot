"""Logon startup planning stays private, and the task helpers do not launch mail."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.serve_handoff import (  # noqa: E402
    APPLY_COMMAND,
    BACKEND,
    PUBLIC_HTTPS,
    ROLLBACK_COMMAND,
    ServeHandoffError,
    format_plan,
    plan_serve_handoff,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WINDOWS = os.path.join(ROOT, "scripts", "windows")
HOST = "dell-sean.tail545f1e.ts.net"
PLANTED = "secret-token-value"


def _read(name: str) -> str:
    with open(os.path.join(WINDOWS, name), encoding="utf-8") as handle:
        return handle.read()


def _powershell() -> str:
    found = shutil.which("powershell")
    if not found:
        pytest.skip("powershell.exe is not available")
    return found


def _run_ps(script: str, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_powershell(), "-NoProfile", "-File", os.path.join(WINDOWS, script), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_serve_plan_is_exact_and_does_not_publish():
    assert APPLY_COMMAND == (
        "tailscale",
        "serve",
        "--bg",
        "--https=443",
        "--set-path=/mcp",
        "http://127.0.0.1:8765/mcp",
    )
    assert ROLLBACK_COMMAND == (
        "tailscale",
        "serve",
        "--https=443",
        "--set-path=/mcp",
        "off",
    )
    assert "funnel" not in " ".join(APPLY_COMMAND + ROLLBACK_COMMAND)
    assert "reset" not in " ".join(APPLY_COMMAND + ROLLBACK_COMMAND)
    assert "--yes" not in APPLY_COMMAND
    empty = plan_serve_handoff("No serve config", "{}")
    text = format_plan(empty)
    assert "apply: tailscale serve --bg --https=443 --set-path=/mcp http://127.0.0.1:8765/mcp" in text
    assert "rollback: tailscale serve --https=443 --set-path=/mcp off" in text
    assert "read: tailscale serve status" in text
    assert "read: tailscale serve status --json" in text
    assert "does not reset other Serve handlers" in text
    assert "serve reset" not in text.lower()
    assert "does not stop a process" in text
    assert PUBLIC_HTTPS in text
    assert BACKEND in text
    persistent = "\n".join(
        [
            f"https://{HOST}",
            f"|-- /mcp proxy {BACKEND}",
        ]
    )
    saved = plan_serve_handoff(
        persistent,
        '{"TCP":{},"Web":{"dell-sean.tail545f1e.ts.net:443":{"Handlers":{"/mcp":{"Proxy":"http://127.0.0.1:8765/mcp"}}}},"AllowFunnel":{}}',
    )
    assert saved["action"] == "already-persistent"
    assert saved["apply"] is None
    refused = [
        ("tailscale funnel is on", "{}"),
        ("No serve config", '{"AllowFunnel":{"dell-sean.tail545f1e.ts.net:443":true}}'),
        ("https://other.example.ts.net\n|-- /mcp proxy http://127.0.0.1:8765/mcp", "{}"),
        (f"https://{HOST}\n|-- / proxy http://127.0.0.1:8765/mcp", "{}"),
        ("No serve config", '{"Web":{"x":1}}'),
        ("not json", "{"),
    ]
    for status_text, status_json in refused:
        try:
            plan_serve_handoff(status_text, status_json)
            raise AssertionError("serve plan was accepted")
        except ServeHandoffError as exc:
            if PLANTED in str(exc) or "funnel is on" in str(exc):
                raise AssertionError("serve status was copied into the error") from exc


def test_serve_plan_cli_hides_status_text():
    script = os.path.join(ROOT, "scripts", "proton-mail-mcp-serve-plan.py")
    proc = subprocess.run(
        [
            sys.executable,
            script,
            "--status-text",
            f"tailscale funnel {PLANTED}",
            "--status-json",
            "{}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    if PLANTED in proc.stdout or PLANTED in proc.stderr:
        raise AssertionError("status text was written to the output")
    assert "not a private mount" in proc.stderr


def test_startup_scripts_do_not_kill_processes_or_widen_the_network():
    combined = "\n".join(
        _read(name)
        for name in (
            "startup-common.ps1",
            "run-at-logon.ps1",
            "install-logon-task.ps1",
            "remove-logon-task.ps1",
            "check-startup.ps1",
            "plan-serve-handoff.ps1",
        )
    )
    lowered = combined.lower()
    for banned in (
        "stop-process",
        "taskkill",
        "tailscale funnel",
        "-password",
        "schtasks",
        " -executionpolicy",
        "unblock-file",
        "set-executionpolicy",
    ):
        if banned in lowered:
            raise AssertionError("startup helper contains " + banned)
    if " bypass" in lowered:
        raise AssertionError("startup helper contains a policy bypass")
    assert "LogonType Interactive" in combined
    assert "RunLevel Limited" in combined
    assert "IgnoreNew" in combined
    assert "PT45S" in combined
    assert "PT0S" in combined
    assert 'BIND_HOST must be 127.0.0.1' in combined
    assert "8765" in combined
    assert HOST in combined
    assert "proton-mail-mcp:bridge-imap" not in lowered
    assert "tools/call" not in lowered


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), 0.2):
            return True
    except OSError:
        return False


def test_logon_wrapper_does_not_start_python_on_windows(tmp_path):
    if sys.platform != "win32":
        pytest.skip("logon wrapper is tested on Windows")
    marker = tmp_path / "started.txt"
    writer = tmp_path / "marker-python.py"
    writer.write_text("from pathlib import Path\nPath(r'%s').write_text('started')\n" % marker, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHON_EXE"] = str(writer)
    env["PROTON_MCP_BRIDGE_WAIT_SECONDS"] = "0"
    if not _port_open(8765):
        refused = _run_ps("run-at-logon.ps1", [], env)
        assert refused.returncode == 1
        assert "were not both open" in refused.stdout
        assert not marker.exists()
        if PLANTED in refused.stdout or PLANTED in refused.stderr:
            raise AssertionError("secret appeared in logon output")
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 8765))
    except OSError:
        pytest.skip("127.0.0.1:8765 is already in use")
    listener.listen(1)
    try:
        duplicate = _run_ps("run-at-logon.ps1", [], env)
    finally:
        listener.close()
    assert duplicate.returncode == 0
    assert "already open" in duplicate.stdout
    assert not marker.exists()


def test_logon_task_install_check_and_remove_on_windows():
    if sys.platform != "win32":
        pytest.skip("scheduled task registration is tested on Windows")
    env_path = os.path.join(ROOT, "config", "windows.env")
    previous = None
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as handle:
            previous = handle.read()
    fixture_user = "fixture-user-not-printed"
    fixture = "\n".join(
        [
            "BIND_HOST=127.0.0.1",
            "BIND_PORT=8765",
            f"PROTON_MCP_EXTRA_HOSTS={HOST}",
            "NODE_BIN=C:\\Windows\\System32",
            "MCP_JS=C:\\missing\\index.js",
            f"PROTONMAIL_USERNAME={fixture_user}",
            "IMAP_HOST=127.0.0.1",
            "IMAP_PORT=1143",
            "PROTONMAIL_HOST=127.0.0.1",
            "PROTONMAIL_PORT=1025",
            "",
        ]
    )
    powershell = _powershell()
    cleanup = (
        "Unregister-ScheduledTask -TaskName 'ProtonMailMCP-Loopback' "
        "-Confirm:$false -ErrorAction SilentlyContinue"
    )
    subprocess.run([powershell, "-NoProfile", "-Command", cleanup], check=False, capture_output=True, text=True)
    try:
        with open(env_path, "w", encoding="utf-8") as handle:
            handle.write(fixture)
        installed = _run_ps("install-logon-task.ps1", [])
        assert installed.returncode == 0, installed.stderr
        assert "logon task installed" in installed.stdout
        assert "Bridge Open on startup was not checked" in installed.stdout
        assert "does not change Bridge" in installed.stdout
        if fixture_user in installed.stdout or fixture_user in installed.stderr:
            raise AssertionError("config value appeared in install output")
        again = _run_ps("install-logon-task.ps1", [])
        assert again.returncode == 0
        assert "already installed" in again.stdout
        checked = _run_ps("check-startup.ps1", [])
        assert checked.returncode == 0, checked.stderr
        for line in (
            "installed: yes",
            "logon: Interactive",
            "run-level: Limited",
            "delay: PT45S",
            "multiple-instances: IgnoreNew",
            "restart-count: 3",
            "execution-limit: PT0S",
            "user: current-user",
            "bridge-autostart: not-verified",
            "serve-handoff: not changed",
            "https://dell-sean.tail545f1e.ts.net/mcp",
        ):
            assert line in checked.stdout
        assert "execution-policy: " in checked.stdout
        if fixture_user in checked.stdout or "Bearer" in checked.stdout:
            raise AssertionError("check output was not sanitized")
        exported = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                "Export-ScheduledTask -TaskName 'ProtonMailMCP-Loopback'",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        xml = exported.stdout
        assert "<Password>" not in xml
        assert "<UserId>SYSTEM</UserId>" not in xml
        assert "ExecutionPolicy" not in xml
        assert "Bypass" not in xml
        assert fixture_user not in xml
        assert "funnel" not in xml.lower()
        removed = _run_ps("remove-logon-task.ps1", [])
        assert removed.returncode == 0
        assert "logon task removed" in removed.stdout
        gone = _run_ps("check-startup.ps1", [])
        assert gone.returncode == 0
        assert "installed: no" in gone.stdout
        identity = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                "[System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        plant = (
            "$action = New-ScheduledTaskAction -Execute $env:SystemRoot\\System32\\cmd.exe -Argument '/c exit 0'; "
            "$trigger = New-ScheduledTaskTrigger -AtLogOn -User '%s'; "
            "$principal = New-ScheduledTaskPrincipal -UserId '%s' -LogonType Interactive -RunLevel Limited; "
            "Register-ScheduledTask -TaskName 'ProtonMailMCP-Loopback' -Action $action -Trigger $trigger "
            "-Principal $principal | Out-Null"
        ) % (identity, identity)
        planted = subprocess.run(
            [powershell, "-NoProfile", "-Command", plant],
            check=False,
            capture_output=True,
            text=True,
        )
        assert planted.returncode == 0, planted.stderr
        refused_install = _run_ps("install-logon-task.ps1", [])
        assert refused_install.returncode != 0
        assert "refusing to replace" in refused_install.stderr
        refused_remove = _run_ps("remove-logon-task.ps1", [])
        assert refused_remove.returncode != 0
        assert "refusing to remove" in refused_remove.stderr
        still = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                "(Get-ScheduledTask -TaskName 'ProtonMailMCP-Loopback').Actions[0].Execute",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert "cmd.exe" in still.stdout.lower()
    finally:
        subprocess.run([powershell, "-NoProfile", "-Command", cleanup], check=False, capture_output=True, text=True)
        if previous is None:
            if os.path.exists(env_path):
                os.remove(env_path)
        else:
            with open(env_path, "w", encoding="utf-8") as handle:
                handle.write(previous)


def test_serve_plan_script_on_windows_does_not_call_tailscale():
    if sys.platform != "win32":
        pytest.skip("PowerShell serve plan wrapper is tested on Windows")
    env = dict(os.environ)
    env["PYTHON_EXE"] = sys.executable
    proc = _run_ps(
        "plan-serve-handoff.ps1",
        ["-StatusText", "No serve config", "-StatusJson", "{}"],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "apply: tailscale serve --bg --https=443 --set-path=/mcp http://127.0.0.1:8765/mcp" in proc.stdout
    assert "saved serve status" not in proc.stdout
    missing = _run_ps("plan-serve-handoff.ps1", [], env)
    assert missing.returncode != 0
