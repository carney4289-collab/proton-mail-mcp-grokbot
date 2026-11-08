"""windows.env is found from the package root and keeps paths with spaces."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.launch import node_argv  # noqa: E402
from connector.runtime_env import ConfigError, child_environment  # noqa: E402
from connector.windows_env import apply_windows_env, package_root_from_script  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _write_env(directory: str) -> str:
    config = os.path.join(directory, "config")
    os.makedirs(config)
    path = os.path.join(config, "windows.env")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            textwrap.dedent(
                """\
                # non-secret installed config
                PROTONMAIL_USERNAME=from-file@example.invalid
                NODE_BIN=C:\\Program Files\\nodejs\\node.exe
                MCP_JS=C:\\Package Root\\proton-mail-mcp\\build\\index.js
                IMAP_HOST=127.0.0.1
                IMAP_PORT=1143
                PROTONMAIL_HOST=127.0.0.1
                PROTONMAIL_PORT=1025
                IMAP_SECURE=false
                PROTONMAIL_SECURE=false
                PROTONMAIL_ALLOW_SEND=true
                ALLOW_EMPTY_FOLDER=true
                PROTONMAIL_ALLOWED_FOLDERS=*
                PROTONMAIL_ALLOWED_ACTIONS=send_email,save_draft
                """
            )
        )
    return path


def test_file_fills_username_and_spaced_node_path_without_using_cwd(tmp_path, monkeypatch):
    package = tmp_path / "package root" / "proton-mail-mcp-windows-c28b7da"
    scripts = package / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "proton-mail-mcp-check.py"
    script.write_text("# marker\n", encoding="utf-8")
    env_path = _write_env(str(package))
    assert package_root_from_script(str(script)) == package
    monkeypatch.chdir(tmp_path)
    source: dict[str, str] = {}
    apply_windows_env(source, Path(env_path))
    assert source["PROTONMAIL_USERNAME"] == "from-file@example.invalid"
    assert source["NODE_BIN"] == r"C:\Program Files\nodejs\node.exe"
    assert " " in source["NODE_BIN"]
    argv = node_argv(source["NODE_BIN"], source["MCP_JS"], "nt")
    assert argv[0] == r"C:\Program Files\nodejs\node.exe"
    child = child_environment(source, "DUMMY-BRIDGE-SECRET-VALUE")
    assert child["PROTONMAIL_USERNAME"] == "from-file@example.invalid"
    assert child["IMAP_PORT"] == "1143"
    assert child["PROTONMAIL_PORT"] == "1025"
    assert child["PROTONMAIL_ALLOW_SEND"] == "true"


def test_process_value_wins_and_secret_lines_are_refused(tmp_path):
    package = tmp_path / "pkg"
    path = _write_env(str(package))
    source = {"PROTONMAIL_USERNAME": "from-process@example.invalid"}
    apply_windows_env(source, Path(path))
    assert source["PROTONMAIL_USERNAME"] == "from-process@example.invalid"
    assert source["NODE_BIN"].endswith("node.exe")
    secret_file = package / "config" / "bad.env"
    secret_file.write_text("IMAP_PASSWORD=not-allowed\n", encoding="utf-8")
    try:
        apply_windows_env({}, secret_file)
        raise AssertionError("secret line was accepted")
    except ConfigError as exc:
        assert "IMAP_PASSWORD" in str(exc)
        assert "not-allowed" not in str(exc)


def test_powershell51_check_sees_windows_env_not_cwd(tmp_path):
    if sys.platform != "win32":
        pytest.skip("PowerShell 5.1 handoff is tested on Windows")
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("powershell.exe is not available")
    package = tmp_path / "Grok Bot Package" / "proton-mail-mcp-windows-c28b7da"
    windows = package / "scripts" / "windows"
    windows.mkdir(parents=True)
    for name in ("load-windows-env.ps1", "check-local.ps1"):
        shutil.copyfile(ROOT + "/scripts/windows/" + name, windows / name)
    _write_env(str(package))
    probe = package / "scripts" / "show_env.py"
    probe.write_text(
        "import os, sys\n"
        "user = os.environ.get('PROTONMAIL_USERNAME', '')\n"
        "node = os.environ.get('NODE_BIN', '')\n"
        "if not user:\n"
        "    sys.stderr.write('PROTONMAIL_USERNAME is not set\\n')\n"
        "    raise SystemExit(2)\n"
        "sys.stdout.write(user + '\\n' + node + '\\n')\n",
        encoding="utf-8",
    )
    launcher = windows / "run-probe.ps1"
    launcher.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)\n"
        ". (Join-Path $PSScriptRoot 'load-windows-env.ps1')\n"
        "Import-ProtonWindowsEnv -Path (Join-Path $Root 'config\\windows.env')\n"
        "& $env:PYTHON_EXE -u (Join-Path $Root 'scripts\\show_env.py')\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PROTONMAIL_USERNAME", None)
    env["PYTHON_EXE"] = sys.executable
    env["PATH"] = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"
    proc = subprocess.run(
        [powershell, "-NoProfile", "-File", str(launcher)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PROTONMAIL_USERNAME is not set" not in proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines[-2] == "from-file@example.invalid"
    assert lines[-1] == r"C:\Program Files\nodejs\node.exe"
