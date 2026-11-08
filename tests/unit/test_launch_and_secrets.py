import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.launch import node_argv, resolve_node_executable  # noqa: E402
from connector.redact import redact  # noqa: E402
from connector.runtime_env import ConfigError, child_environment  # noqa: E402
from connector.secrets import (  # noqa: E402
    MemorySecretStore,
    decode_credential_blob,
    tokens_equal,
)
from proton_mail_mcp_policy import full_function_env  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DUMMY_BRIDGE = "DUMMY-BRIDGE-SECRET-VALUE"
DUMMY_AUTH = "DUMMY-ENDPOINT-AUTH-SECRET"


def test_windows_npm_cmd_is_started_through_cmd_exe_without_shell():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from build_pinned_mcp import tool_command

    argv = tool_command(r"C:\Program Files\nodejs\npm.cmd", ["ci", "--no-audit", "--no-fund"], "nt")
    assert argv[:4] == ["cmd.exe", "/d", "/s", "/c"]
    assert "npm.cmd" in argv[4]
    assert "ci" in argv[4]
    assert "--no-fund" in argv[4]
    assert tool_command("/usr/bin/npm", ["ci"], "posix") == ["/usr/bin/npm", "ci"]


def test_node_directory_and_executable_on_both_platforms():
    assert resolve_node_executable(r"C:\Program Files\nodejs", "nt") == r"C:\Program Files\nodejs\node.exe"
    assert resolve_node_executable(r"C:\Program Files\nodejs\node.exe", "nt") == r"C:\Program Files\nodejs\node.exe"
    assert resolve_node_executable("/usr/local/bin", "posix") == "/usr/local/bin/node"
    assert resolve_node_executable("/usr/local/bin/node", "posix") == "/usr/local/bin/node"
    argv = node_argv(r"C:\Program Files\nodejs", r"C:\Users\box\mcp\build\index.js", "nt")
    assert argv[0].endswith("node.exe")
    assert argv[1].endswith("index.js")
    assert len(argv) == 2


def test_child_env_rejects_remote_mail_hosts_and_keeps_password_out_of_argv_shape():
    source = full_function_env()
    source["IMAP_HOST"] = "imap.example.invalid"
    try:
        child_environment(source, DUMMY_BRIDGE)
        raise AssertionError("remote IMAP host was accepted")
    except ConfigError as exc:
        assert "loopback" in str(exc)
        assert DUMMY_BRIDGE not in str(exc)
    env = child_environment(full_function_env(), DUMMY_BRIDGE)
    assert env["IMAP_HOST"] == "127.0.0.1"
    assert env["PROTONMAIL_HOST"] == "127.0.0.1"
    assert env["IMAP_PASSWORD"] == DUMMY_BRIDGE
    assert "DUMMY-ENDPOINT" not in env["IMAP_PASSWORD"]


def test_child_env_ignores_password_planted_in_the_parent_map():
    source = full_function_env()
    source["IMAP_PASSWORD"] = "PLANTED-PARENT-PASSWORD"
    source["PROTONMAIL_PASSWORD"] = "PLANTED-PARENT-PASSWORD"
    env = child_environment(source, DUMMY_BRIDGE)
    assert env["IMAP_PASSWORD"] == DUMMY_BRIDGE
    assert env["PROTONMAIL_PASSWORD"] == DUMMY_BRIDGE


def test_defaults_do_not_enable_send():
    env = child_environment({"PROTONMAIL_USERNAME": "fake-user@example.invalid"}, DUMMY_BRIDGE)
    assert env["PROTONMAIL_ALLOW_SEND"] == "false"
    assert env["ALLOW_EMPTY_FOLDER"] == "false"
    assert "send_email" not in env["PROTONMAIL_ALLOWED_ACTIONS"].split(",")


def test_redact_and_token_compare():
    text = f"Authorization: Bearer {DUMMY_AUTH} pw={DUMMY_BRIDGE}"
    cleaned = redact(text, (DUMMY_BRIDGE, DUMMY_AUTH))
    assert DUMMY_BRIDGE not in cleaned
    assert DUMMY_AUTH not in cleaned
    assert "[REDACTED]" in cleaned
    assert tokens_equal(DUMMY_AUTH, DUMMY_AUTH)
    assert not tokens_equal(DUMMY_AUTH, DUMMY_BRIDGE)
    assert not tokens_equal("short", "different-length-secret")


def test_credential_blob_decoding():
    assert decode_credential_blob("plain-secret".encode("utf-8")) == "plain-secret"
    assert decode_credential_blob("wide-secret".encode("utf-16-le")) == "wide-secret"
    assert decode_credential_blob(b"") == ""


def test_windows_credential_manager_roundtrip_on_windows_only():
    if sys.platform != "win32":
        pytest.skip("Windows Credential Manager is not on this OS")
    from connector.secrets import WindowsCredentialStore

    store = WindowsCredentialStore()
    value = "DUMMY-CI-CREDENTIAL-VALUE"
    store.put("ci-dummy", value)
    try:
        assert store.get("ci-dummy") == value
    finally:
        store.delete("ci-dummy")


def test_memory_store_rejects_unknown_names():
    store = MemorySecretStore({"bridge-imap": DUMMY_BRIDGE, "http-auth": DUMMY_AUTH})
    assert store.get("bridge-imap") == DUMMY_BRIDGE
    try:
        store.get("anything")
        raise AssertionError("unknown name was accepted")
    except Exception as exc:
        assert "unknown" in str(exc)


def test_cli_rejects_arguments_so_secrets_cannot_be_passed():
    script = os.path.join(ROOT, "scripts", "proton-mail-mcp-http.py")
    proc = subprocess.run(
        [sys.executable, script, "--password", DUMMY_BRIDGE],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert DUMMY_BRIDGE not in proc.stderr
    assert DUMMY_BRIDGE not in proc.stdout


def test_store_cli_rejects_secret_on_argv():
    script = os.path.join(ROOT, "scripts", "proton-mail-mcp-store.py")
    proc = subprocess.run(
        [sys.executable, script, "http-auth", DUMMY_AUTH],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert DUMMY_AUTH not in proc.stderr


def test_windows_scripts_do_not_take_secrets_as_parameters():
    start = open(os.path.join(ROOT, "scripts", "windows", "start-proton-mail-mcp.ps1"), encoding="utf-8").read()
    store = open(os.path.join(ROOT, "scripts", "windows", "store-credential.ps1"), encoding="utf-8").read()
    example = open(os.path.join(ROOT, "config", "windows.env.example"), encoding="utf-8").read()
    assert "Invoke-Expression" not in start
    assert "127.0.0.1" in example
    assert "PASSWORD" not in example.split("PROTONMAIL_ALLOWED_ACTIONS")[0]
    assert "refusing to load a secret" in start
    assert "Read-Host -AsSecureString" in store
    assert "ValidateSet" in store
    assert "& $Python" in start
    for secret in (DUMMY_BRIDGE, DUMMY_AUTH, "BEGIN OPENSSH PRIVATE KEY"):
        assert secret not in start
        assert secret not in store
        assert secret not in example


def test_stdio_backend_redacts_stderr_and_keeps_secret_off_argv():
    from connector.backend import StdioBackend

    script = (
        "import json,sys,os\n"
        "sys.stderr.write('[Error] pw=' + os.environ['PROTONMAIL_PASSWORD'] + '\\n')\n"
        "sys.stderr.flush()\n"
        "for line in sys.stdin:\n"
        "    msg=json.loads(line)\n"
        "    if 'id' not in msg:\n"
        "        continue\n"
        "    sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'ok':True}})+'\\n')\n"
        "    sys.stdout.flush()\n"
    )
    logs: list[str] = []
    backend = StdioBackend(
        [sys.executable, "-c", script],
        {"PROTONMAIL_PASSWORD": DUMMY_BRIDGE, "PATH": os.environ.get("PATH", "")},
        secrets=(DUMMY_BRIDGE,),
        log=logs.append,
        timeout=5,
    )
    try:
        if os.path.exists(f"/proc/{backend.pid}/cmdline"):
            cmdline = open(f"/proc/{backend.pid}/cmdline", "rb").read().replace(b"\x00", b" ").decode()
            assert DUMMY_BRIDGE not in cmdline
        response = backend.exchange({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response["result"]["ok"] is True
    finally:
        backend.close()
    joined = "\n".join(logs)
    assert DUMMY_BRIDGE not in joined
    assert "[REDACTED]" in joined
    assert json.dumps({"ok": True})
