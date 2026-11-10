"""macOS launch, keychain, and Serve helpers. No live tailnet and no real secrets."""
from __future__ import annotations

import json
import os
import plistlib
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.keychain_macos import ACCOUNT, KeychainStore  # noqa: E402
from connector.mac_clipboard import (  # noqa: E402
    MARKER_TYPES,
    TYPE_TEXT,
    commit_mac_clipboard,
    unchanged_outcome,
)
from connector.macos_agent import THROTTLE_SECONDS, render_plist  # noqa: E402
from connector.macos_config import (  # noqa: E402
    EXTRA_HOSTS,
    LABEL,
    assert_launch_config,
    load_macos_config,
    valid_username,
)
from connector.macos_endpoint import (  # noqa: E402
    ALLOWED_ENDPOINT,
    EndpointError,
    format_ok,
    interpret_unauth,
    validate_mac_endpoint,
)
from connector.macos_ports import bridge_ready, parse_wait_seconds, tcp_open  # noqa: E402
from connector.macos_serve import (  # noqa: E402
    APP_CLI,
    WORKAROUND,
    argv_for,
    argv_for_apply,
    confirm_applied,
    gui_failure,
    plan_mac_apply,
    plan_rollback,
    resolve_tailscale,
)
from connector.runtime_env import ConfigError  # noqa: E402
from connector.secrets import (  # noqa: E402
    MemorySecretStore,
    SecretStoreError,
    generate_token,
    store_generated_token,
)
from connector.serve_handoff import (  # noqa: E402
    APPLY_COMMAND,
    BACKEND,
    MAC_HOST,
    PUBLIC_HTTPS,
    ROLLBACK_COMMAND,
    ServeHandoffError,
    format_plan,
    plan_serve_handoff,
)
from connector.unified_diff import UnifiedDiffError, apply_unified_diff  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MACOS = ROOT / "scripts" / "macos"
PLANTED = "planted-bridge-password"
HOST = MAC_HOST


class MemoryKeychain:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.unattended = True

    def get(self, service: str, account: str) -> str | None:
        return self.items.get((service, account))

    def put(self, service: str, account: str, secret: str) -> bool:
        self.items[(service, account)] = secret
        return self.unattended

    def delete(self, service: str, account: str) -> None:
        self.items.pop((service, account), None)


class BoomKeychain(MemoryKeychain):
    def put(self, service: str, account: str, secret: str) -> bool:
        raise RuntimeError(secret)


class Pasteboard:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[str, str] = {}
        self.host_only = False

    def clear(self) -> None:
        self.values = {}
        self.host_only = False

    def prepare_current_host_only(self) -> None:
        if self.fail:
            raise RuntimeError("no pasteboard")
        self.host_only = True

    def set_string(self, text: str, paste_type: str) -> None:
        self.values[paste_type] = text

    def opt_out_ok(self, expected: str) -> bool:
        return (
            self.host_only
            and self.values.get(TYPE_TEXT) == expected
            and all(self.values.get(name) == "1" for name in MARKER_TYPES)
        )


def test_windows_serve_plan_stays_on_the_dell_host():
    plan = plan_serve_handoff("No serve config", "{}")
    text = format_plan(plan)
    assert plan["endpoint"] == PUBLIC_HTTPS
    assert "dell-sean.tail545f1e.ts.net" in text
    assert MAC_HOST not in text
    assert plan["apply"] == APPLY_COMMAND


def test_mac_serve_plan_uses_the_mini_and_the_same_command():
    empty = plan_mac_apply("No serve config", "{}")
    text = format_plan(empty)
    assert empty["endpoint"] == f"https://{HOST}/mcp"
    assert empty["apply"] == APPLY_COMMAND
    assert "apply: tailscale serve --bg --https=443 --set-path=/mcp http://127.0.0.1:8765/mcp" in text
    assert "funnel" not in " ".join(APPLY_COMMAND).lower()
    argv = argv_for_apply("/usr/local/bin/tailscale", empty)
    assert argv == ["/usr/local/bin/tailscale", *APPLY_COMMAND[1:]]
    assert "reset" not in " ".join(argv)
    foreground = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {f"{HOST}:443": {"Handlers": {"/mcp": {"Proxy": BACKEND}}}},
    }
    owned = plan_mac_apply("No serve config", json.dumps({"Foreground": {"session-1": foreground}}))
    assert owned["action"] == "foreground-to-background"
    saved = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {f"{HOST}:443": {"Handlers": {"/mcp": {"Proxy": BACKEND}}}},
    }
    assert confirm_applied(json.dumps(saved))
    try:
        plan_serve_handoff("No serve config", "{}", host=PLANTED)
        raise AssertionError("unknown serve host was accepted")
    except ServeHandoffError as exc:
        assert PLANTED not in str(exc)


def test_rollback_removes_only_mcp_and_refuses_funnel_or_a_different_proxy():
    ours = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {
            f"{HOST}:443": {
                "Handlers": {
                    "/mcp": {"Proxy": BACKEND},
                    "/other": {"Proxy": "http://127.0.0.1:9/"},
                }
            }
        },
    }
    plan = plan_rollback(json.dumps(ours))
    assert plan["action"] == "remove-mcp"
    argv = argv_for("/Applications/Tailscale.app/Contents/MacOS/Tailscale", plan["rollback"])
    assert argv[1:] == list(ROLLBACK_COMMAND[1:])
    assert plan_rollback("{}")["action"] == "already-off"
    try:
        plan_rollback(json.dumps({"AllowFunnel": {f"{HOST}:443": True}, "Web": ours["Web"]}))
        raise AssertionError("funnel rollback was accepted")
    except ServeHandoffError as exc:
        assert "not a private mount" in str(exc)
    other = {
        "Web": {f"{HOST}:443": {"Handlers": {"/mcp": {"Proxy": "http://127.0.0.1:9/mcp"}}}},
    }
    try:
        plan_rollback(json.dumps(other))
        raise AssertionError("foreign /mcp handler was accepted")
    except ServeHandoffError as exc:
        assert "not this connector" in str(exc)
        assert "127.0.0.1:9" not in str(exc)


def test_tailscale_resolver_prefers_the_standalone_cli():
    def exists(path: str) -> bool:
        return path in {APP_CLI, "/usr/local/bin/tailscale"}

    assert resolve_tailscale(None, exists) == "/usr/local/bin/tailscale"
    assert resolve_tailscale("/opt/custom/tailscale", lambda path: path == "/opt/custom/tailscale") == (
        "/opt/custom/tailscale"
    )
    assert gui_failure("The Tailscale GUI failed to start: Tailscale.CLIError error 3")
    assert "Install CLI" in WORKAROUND
    assert "not the Proton" in WORKAROUND
    try:
        resolve_tailscale(None, lambda _path: False)
        raise AssertionError("missing tailscale was accepted")
    except ServeHandoffError as exc:
        assert "not found" in str(exc)


def test_launch_agent_plist_is_per_user_and_has_no_secrets():
    home = "/Users/seancarney"
    package = "/Users/seancarney/Library/Application Support/ProtonMailMCP/package"
    python = home + "/Library/Application Support/ProtonMailMCP/runtimes/venv/bin/python3"
    text = render_plist(package_root=package, python_exe=python, home=home)
    payload = plistlib.loads(text.encode("utf-8"))
    assert payload["Label"] == LABEL
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ThrottleInterval"] == THROTTLE_SECONDS
    assert payload["LimitLoadToSessionType"] == "Aqua"
    assert payload["ProgramArguments"][0] == "/bin/bash"
    assert payload["ProgramArguments"][1].endswith("/scripts/macos/run-at-login.sh")
    assert payload["StandardErrorPath"].endswith("/Library/Logs/ProtonMailMCP/connector.err.log")
    assert payload["EnvironmentVariables"]["PROTON_MCP_SECRET_STORE"] == "keychain"
    assert payload["EnvironmentVariables"]["PYTHON_EXE"] == python
    assert "Application Support" in text
    for banned in ("password", "bearer", "funnel", "sudo", PLANTED):
        assert banned not in text.lower()
    assert text.lower().count("secret") == text.lower().count("proton_mcp_secret_store")
    try:
        render_plist(package_root="relative", python_exe=python, home=home)
        raise AssertionError("relative path was accepted")
    except ValueError:
        pass


def test_config_rejects_a_public_bind_and_expands_home(tmp_path):
    path = tmp_path / "macos.env"
    path.write_text(
        "\n".join(
            [
                "BIND_HOST=127.0.0.1",
                "BIND_PORT=8765",
                "PROTON_MCP_EXTRA_HOSTS=" + EXTRA_HOSTS,
                "NODE_BIN=$HOME/Library/Application Support/node/bin",
                "PROTONMAIL_USERNAME=person@example.com",
                "IMAP_HOST=127.0.0.1",
                "PROTONMAIL_HOST=127.0.0.1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    environ: dict[str, str] = {}
    load_macos_config(path, environ, "/Users/seancarney")
    assert_launch_config(environ)
    assert environ["NODE_BIN"] == "/Users/seancarney/Library/Application Support/node/bin"
    environ["BIND_HOST"] = "0.0.0.0"
    try:
        assert_launch_config(environ)
        raise AssertionError("public bind was accepted")
    except ConfigError as exc:
        assert "127.0.0.1" in str(exc)
        assert "person@example.com" not in str(exc)
    assert valid_username("person@example.com")
    assert not valid_username("not-an-email")
    assert not valid_username("has space@example.com")


def test_bridge_wait_does_not_probe_other_ports():
    calls: list[int] = []

    def opener(port: int) -> bool:
        calls.append(port)
        return port in {1143, 1025} and calls.count(port) > 0

    clock = {"now": 0.0}

    def now() -> float:
        return clock["now"]

    def sleep(seconds: int) -> None:
        clock["now"] += seconds

    assert bridge_ready(0, sleep=sleep, clock=now, opener=opener)
    assert calls == [1143, 1025]
    assert parse_wait_seconds(None) == 90
    try:
        tcp_open(22)
        raise AssertionError("an unrelated port was probed")
    except ValueError as exc:
        assert "refusing" in str(exc)
    try:
        parse_wait_seconds("121")
        raise AssertionError("a long wait was accepted")
    except ValueError:
        pass


def test_unauth_check_accepts_only_the_mini_and_only_401():
    assert validate_mac_endpoint(ALLOWED_ENDPOINT) == ALLOWED_ENDPOINT
    assert validate_mac_endpoint("https://Seans-Mac-Mini.tail545f1e.ts.net/mcp") == ALLOWED_ENDPOINT
    interpret_unauth(401)
    for status in (200, 301, 403, 404, 500):
        try:
            interpret_unauth(status)
            raise AssertionError(f"status {status} was accepted")
        except EndpointError:
            pass
    rejected = [
        "http://seans-mac-mini.tail545f1e.ts.net/mcp",
        "https://dell-sean.tail545f1e.ts.net/mcp",
        "https://seans-mac-mini.tail545f1e.ts.net/other",
        f"https://user:{PLANTED}@seans-mac-mini.tail545f1e.ts.net/mcp",
    ]
    for url in rejected:
        try:
            validate_mac_endpoint(url)
            raise AssertionError("accepted a bad url")
        except EndpointError as exc:
            assert PLANTED not in str(exc)
    text = format_ok()
    assert "unauth 401" in text
    assert "Authorization" not in text


def test_endpoint_cli_rejects_a_different_host_without_using_the_network():
    script = MACOS / "check_endpoint.py"
    proc = subprocess.run(
        [sys.executable, str(script), f"https://user:{PLANTED}@example.invalid/mcp"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert PLANTED not in proc.stdout
    assert PLANTED not in proc.stderr


def test_keychain_store_keeps_the_secret_out_of_errors_and_will_not_replace_the_token():
    backend = MemoryKeychain()
    store = KeychainStore(backend)
    store.put("bridge-imap", PLANTED)
    assert backend.items[("proton-mail-mcp:bridge-imap", ACCOUNT)] == PLANTED
    assert store.get("bridge-imap") == PLANTED
    first = store_generated_token(store, "http-auth")
    assert first not in "stored"
    try:
        store_generated_token(store, "http-auth")
        raise AssertionError("token was replaced")
    except SecretStoreError as exc:
        assert first not in str(exc)
        assert "not overwritten" in str(exc)
    try:
        store_generated_token(store, "bridge-imap")
        raise AssertionError("bridge generation was accepted")
    except SecretStoreError as exc:
        assert PLANTED not in str(exc)
    boom = KeychainStore(BoomKeychain())
    try:
        boom.put("http-auth", generate_token())
        raise AssertionError("backend failure was ignored")
    except SecretStoreError as exc:
        assert "keychain write failed" in str(exc)
        assert "http-auth" not in str(exc)


def test_store_bridge_cli_does_not_print_the_password():
    if sys.platform == "darwin":
        pytest.skip("this failure path would touch the login keychain")
    script = MACOS / "store_bridge.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=PLANTED + "\n" + PLANTED + "\n",
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert PLANTED not in proc.stdout
    assert PLANTED not in proc.stderr


def test_generate_cli_does_not_print_a_token_off_macos():
    if sys.platform == "darwin":
        pytest.skip("the failure path is the non-mac keychain")
    script = MACOS / "new_http_auth.py"
    proc = subprocess.run([sys.executable, str(script)], check=False, capture_output=True, text=True)
    assert proc.returncode == 2
    assert "macOS Keychain is only available on macOS" in proc.stderr
    copy = subprocess.run(
        [sys.executable, str(MACOS / "copy_http_auth.py"), "--confirm"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert copy.returncode == 2
    assert "Bearer " not in copy.stdout


def test_mac_clipboard_clears_when_opt_out_cannot_be_set():
    token = generate_token()
    value = "Bearer " + token
    board = Pasteboard()
    commit_mac_clipboard(board, value)
    assert board.values[TYPE_TEXT] == value
    assert board.values["org.nspasteboard.ConcealedType"] == "1"
    assert board.host_only
    assert unchanged_outcome(value, value) == "cleared"
    assert unchanged_outcome("newer", value) == "preserved"
    failed = Pasteboard(fail=True)
    try:
        commit_mac_clipboard(failed, value)
        raise AssertionError("opt-out failure still copied")
    except Exception as exc:
        assert token not in str(exc)
    assert failed.values == {}
    memory = MemorySecretStore({"http-auth": token, "bridge-imap": PLANTED})
    assert memory.get("bridge-imap") == PLANTED


def test_unified_diff_applies_and_rejects_a_mismatch(tmp_path):
    target = tmp_path / "src" / "note.txt"
    target.parent.mkdir()
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    diff = """comment that is not a hunk
--- a/src/note.txt
+++ b/src/note.txt
@@ -1,3 +1,3 @@
 alpha
-beta
+BETA
 gamma
"""
    apply_unified_diff(tmp_path, diff)
    assert target.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
    try:
        apply_unified_diff(tmp_path, diff)
        raise AssertionError("stale context was applied")
    except UnifiedDiffError as exc:
        assert "did not match" in str(exc)


def test_shell_scripts_are_syntax_clean_and_do_not_widen_access():
    shells = sorted(MACOS.glob("*.sh"))
    assert shells
    for path in shells:
        proc = subprocess.run(["bash", "-n", str(path)], check=False, capture_output=True, text=True)
        assert proc.returncode == 0, path.name + "\n" + proc.stderr
    combined = "\n".join(path.read_text(encoding="utf-8") for path in shells)
    lowered = combined.lower()
    for banned in ("tailscale funnel", "serve reset", "curl | sh", "curl | bash"):
        assert banned not in lowered
    for path in shells:
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]
            if "sudo" in code.split():
                raise AssertionError(path.name + " runs sudo")
    install = (MACOS / "install.sh").read_text(encoding="utf-8")
    assert '!= "arm64"' in install
    assert "id -u" in install
    assert "89c682593d76cd44233fa53b1563264e7de9cbb189cad169135c5b4fadfbc0a7" in install
    assert "0.13.7" in install
    assert "macos_refuse_xtrace" in (MACOS / "store-bridge.sh").read_text(encoding="utf-8")
    assert "read -r -s" in (MACOS / "store-bridge.sh").read_text(encoding="utf-8")
    plist = (MACOS / "run-at-login.sh").read_text(encoding="utf-8")
    assert "8765" in plist
    assert "1143" in plist
    assert "1025" in plist
    assert "exec " in plist


def test_write_config_does_not_print_the_email(tmp_path, monkeypatch):
    script = MACOS / "write_config.py"
    email = "person@example.com"
    destination = ROOT / "config" / "macos.env"
    previous = destination.read_text(encoding="utf-8") if destination.exists() else None
    payload = "\n".join(
        [
            email,
            "/Users/seancarney/Library/Application Support/ProtonMailMCP/runtimes/node/bin",
            "/Users/seancarney/Library/Application Support/ProtonMailMCP/package/build/index.js",
            "/Users/seancarney/Library/Application Support/ProtonMailMCP/attachments",
        ]
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=payload + "\n",
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert email not in proc.stdout
        assert email not in proc.stderr
        text = destination.read_text(encoding="utf-8")
        assert "PROTONMAIL_USERNAME=" + email in text
        assert "REPLACE_" not in text
        assert EXTRA_HOSTS in text
        mode = stat.S_IMODE(destination.stat().st_mode)
        assert mode == 0o600
    finally:
        if previous is None:
            destination.unlink(missing_ok=True)
        else:
            destination.write_text(previous, encoding="utf-8")


def test_http_launcher_uses_keychain_only_when_asked_off_windows():
    if sys.platform == "win32":
        pytest.skip("windows default is Credential Manager")
    if sys.platform == "darwin":
        pytest.skip("a real login keychain is not required for this failure")
    script = ROOT / "scripts" / "proton-mail-mcp-http.py"
    env = dict(os.environ)
    env["PROTON_MCP_SECRET_STORE"] = "keychain"
    proc = subprocess.run([sys.executable, str(script)], check=False, capture_output=True, text=True, env=env)
    assert proc.returncode == 2
    assert "macOS Keychain is only available on macOS" in proc.stderr


def test_live_keychain_round_trip_on_macos(tmp_path):
    if sys.platform != "darwin":
        pytest.skip("login keychain exists on macOS")
    import signal

    from connector.keychain_macos import MacKeychainStore, create_test_keychain

    def _timeout(_signum, _frame):
        raise TimeoutError("keychain call did not return")

    previous = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(30)
    path = tmp_path / "ci.keychain-db"
    password = "ci-keychain-pass"
    secret = "ci-dummy-secret-value"
    try:
        create_test_keychain(str(path), password)
        store = MacKeychainStore(str(path), password)
        store.put("ci-dummy", secret)
        assert store.get("ci-dummy") == secret
        assert secret not in "present"
        store.delete("ci-dummy")
        assert store.get("ci-dummy") is None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
