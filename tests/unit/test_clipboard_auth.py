"""Clipboard handoff: one bearer value, opt-out formats, no secret output."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from connector.clipboard_auth import (  # noqa: E402
    CF_UNICODETEXT,
    DEFAULT_SECONDS,
    FORMAT_CLOUD,
    FORMAT_EXCLUDE,
    FORMAT_HISTORY,
    ClipboardHandoffError,
    authorization_value,
    commit_clipboard,
    control_event_should_clear,
    parse_cli,
    run_handoff,
    token_ok,
    windows_supports_clipboard_opt_out,
)
from connector.secrets import MemorySecretStore, generate_token, tokens_equal  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BRIDGE = "BRIDGE-SECRET-DO-NOT-READ"


class SpyStore(MemorySecretStore):
    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.gets: list[str] = []
        self.writes: list[str] = []

    def get(self, logical_name: str) -> str | None:
        self.gets.append(logical_name)
        return super().get(logical_name)

    def put(self, logical_name: str, secret: str) -> None:
        self.writes.append(logical_name)
        raise AssertionError("credential write")

    def delete(self, logical_name: str) -> None:
        self.writes.append("delete")
        raise AssertionError("credential delete")


class FakeClipboard:
    def __init__(self, *, fail_place: bool = False) -> None:
        self.fail_place = fail_place
        self.text: str | None = None
        self.prepared = False
        self.closed = False
        self.formats: dict[str, object] = {}

    def prepare(self) -> None:
        self.prepared = True

    def place(self, value: str) -> None:
        if not self.prepared:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        if self.fail_place:
            raise ClipboardHandoffError("clipboard opt-out is not available", clipboard_cleared=True)
        self.text = value
        self.formats = {FORMAT_EXCLUDE: True, FORMAT_HISTORY: 0, FORMAT_CLOUD: 0}

    def clear_if_unchanged(self, expected: str) -> str:
        if self.text is None or not tokens_equal(self.text, expected):
            return "preserved"
        self.text = None
        self.formats = {}
        return "cleared"

    def close(self) -> None:
        self.closed = True

    def overwrite(self, text: str) -> None:
        self.text = text


class MemoryDriver:
    def __init__(self, *, explode: bool = False, reject_opt_out: bool = False) -> None:
        self.explode = explode
        self.reject_opt_out = reject_opt_out
        self.text: str | None = None
        self.exclude = False
        self.dwords: dict[str, int] = {}

    def empty(self) -> None:
        self.text = None
        self.exclude = False
        self.dwords = {}

    def set_exclude(self) -> None:
        self.exclude = True

    def set_dword(self, name: str, value: int) -> None:
        self.dwords[name] = value

    def set_text(self, value: str) -> None:
        self.text = value
        if self.explode:
            raise RuntimeError(value)

    def opt_out_ok(self) -> bool:
        if self.reject_opt_out:
            return False
        return (
            self.exclude
            and self.dwords.get(FORMAT_HISTORY) == 0
            and self.dwords.get(FORMAT_CLOUD) == 0
            and isinstance(self.text, str)
        )


def _token() -> str:
    return generate_token()


def _silent() -> tuple[io.StringIO, io.StringIO]:
    return io.StringIO(), io.StringIO()


def _assert_hidden(secret: str, *chunks: str) -> None:
    for chunk in chunks:
        if secret and secret in chunk:
            raise AssertionError("secret appeared in output")


def test_documented_opt_out_format_names_and_windows_floor():
    assert FORMAT_EXCLUDE == "ExcludeClipboardContentFromMonitorProcessing"
    assert FORMAT_HISTORY == "CanIncludeInClipboardHistory"
    assert FORMAT_CLOUD == "CanUploadToCloudClipboard"
    assert windows_supports_clipboard_opt_out((10, 0, 17763)) is True
    assert windows_supports_clipboard_opt_out((10, 0, 26100)) is True
    assert windows_supports_clipboard_opt_out((10, 0, 17762)) is False
    assert windows_supports_clipboard_opt_out((10, 0, 10240)) is False
    assert windows_supports_clipboard_opt_out((6, 3, 9600)) is False
    assert control_event_should_clear(0) is False
    assert control_event_should_clear(1) is False
    assert control_event_should_clear(2) is True
    assert control_event_should_clear(5) is True
    assert control_event_should_clear(6) is True


def test_generated_token_is_accepted_and_invalid_tokens_are_refused():
    token = _token()
    if not token_ok(token):
        raise AssertionError("generated token was rejected")
    value = authorization_value(token)
    if not value.startswith("Bearer ") or len(value) != len("Bearer ") + len(token):
        raise AssertionError("payload shape mismatch")
    leaked = "LEAKED-TOKEN"
    refused = [
        "",
        "x" * 42,
        "x" * 44,
        leaked,
        "A" * 42 + "\n",
        "A" * 42 + " ",
        "A" * 42 + "+",
        "Bearer " + "A" * 36,
        None,
    ]
    for item in refused:
        try:
            authorization_value(item)
            raise AssertionError("invalid token was accepted")
        except ClipboardHandoffError as exc:
            _assert_hidden(leaked, str(exc))
            assert exc.clipboard_cleared is False


def test_cli_rejects_missing_confirm_and_does_not_echo_extra_arguments():
    planted = "LEAKED-ARGUMENT"
    try:
        parse_cli([])
        raise AssertionError("missing confirm was accepted")
    except ClipboardHandoffError as exc:
        assert "confirmation required" in str(exc)
    try:
        parse_cli(["--confirm", "--token", planted])
        raise AssertionError("extra argument was accepted")
    except ClipboardHandoffError as exc:
        _assert_hidden(planted, str(exc))
        assert "arguments rejected" in str(exc)
    assert parse_cli(["--confirm"]) == DEFAULT_SECONDS
    assert parse_cli(["--confirm", "--seconds", "15"]) == 15
    assert parse_cli(["--confirm", "--seconds", "90"]) == 90
    for raw in ("14", "91", "045", "15 "):
        try:
            parse_cli(["--confirm", "--seconds", raw])
            raise AssertionError("seconds accepted: " + raw)
        except ClipboardHandoffError as exc:
            assert "arguments rejected" in str(exc)


def test_handoff_copies_bearer_clears_it_and_does_not_touch_bridge():
    token = _token()
    store = SpyStore({"http-auth": token, "bridge-imap": BRIDGE})
    clip = FakeClipboard()
    out, err = _silent()
    seen: dict[str, object] = {}

    def sleep(seconds: int) -> None:
        seen["seconds"] = seconds
        seen["text"] = clip.text
        seen["formats"] = dict(clip.formats)

    code = run_handoff(store, clip, 15, sleep, out, err)
    if code != 0:
        raise AssertionError("handoff failed")
    if not isinstance(seen.get("text"), str) or not tokens_equal(seen["text"], "Bearer " + token):
        raise AssertionError("payload mismatch")
    assert seen["formats"] == {FORMAT_EXCLUDE: True, FORMAT_HISTORY: 0, FORMAT_CLOUD: 0}
    assert seen["seconds"] == 15
    assert clip.text is None
    assert clip.formats == {}
    assert clip.closed is True
    assert store.gets == ["http-auth"]
    assert store.writes == []
    assert store.get("bridge-imap") == BRIDGE
    store.gets.clear()
    assert "Clipboard cleared." in out.getvalue()
    assert "tools/call" not in out.getvalue()
    _assert_hidden(token, out.getvalue(), err.getvalue())
    _assert_hidden(BRIDGE, out.getvalue(), err.getvalue())


def test_newer_clipboard_content_is_preserved():
    token = _token()
    store = SpyStore({"http-auth": token, "bridge-imap": BRIDGE})
    clip = FakeClipboard()
    out, err = _silent()

    def sleep(_seconds: int) -> None:
        clip.overwrite("NEWER-CLIPBOARD-CONTENT")

    code = run_handoff(store, clip, 45, sleep, out, err)
    if code != 0:
        raise AssertionError("handoff failed")
    assert clip.text == "NEWER-CLIPBOARD-CONTENT"
    assert "left in place" in out.getvalue()
    _assert_hidden(token, out.getvalue(), err.getvalue())
    assert store.writes == []


def test_failed_opt_out_leaves_no_payload_and_no_secret_in_the_error():
    token = _token()
    value = authorization_value(token)
    ok = MemoryDriver()
    commit_clipboard(ok, value)
    if not isinstance(ok.text, str) or not tokens_equal(ok.text, value):
        raise AssertionError("payload mismatch")
    assert ok.exclude is True
    assert ok.dwords[FORMAT_HISTORY] == 0
    assert ok.dwords[FORMAT_CLOUD] == 0
    driver = MemoryDriver(explode=True)
    try:
        commit_clipboard(driver, value)
        raise AssertionError("opt-out failure was accepted")
    except ClipboardHandoffError as exc:
        _assert_hidden(token, str(exc))
        assert exc.clipboard_cleared is True
    assert driver.text is None
    assert driver.exclude is False
    rejected = MemoryDriver(reject_opt_out=True)
    try:
        commit_clipboard(rejected, value)
        raise AssertionError("rejected opt-out was accepted")
    except ClipboardHandoffError as exc:
        _assert_hidden(token, str(exc))
    assert rejected.text is None
    store = SpyStore({"http-auth": token, "bridge-imap": BRIDGE})
    clip = FakeClipboard(fail_place=True)
    out, err = _silent()
    code = run_handoff(store, clip, 15, lambda _seconds: None, out, err)
    assert code == 2
    assert clip.text is None
    assert "not left on it" in err.getvalue()
    _assert_hidden(token, out.getvalue(), err.getvalue())


def test_store_errors_and_invalid_tokens_are_not_echoed():
    leaked = "LEAKED-TOKEN-FROM-STORE"

    class Boom:
        def get(self, _name: str) -> str:
            raise RuntimeError(leaked)

    clip = FakeClipboard()
    out, err = _silent()
    code = run_handoff(Boom(), clip, 15, lambda _seconds: None, out, err)
    assert code == 2
    assert clip.text is None
    _assert_hidden(leaked, out.getvalue(), err.getvalue())
    assert "not available" in err.getvalue()
    bad = "LEAKED-INVALID-TOKEN-VALUE-NOT-COPIED"
    store = SpyStore({"http-auth": bad, "bridge-imap": BRIDGE})
    out, err = _silent()
    code = run_handoff(store, FakeClipboard(), 15, lambda _seconds: None, out, err)
    assert code == 2
    assert store.gets == ["http-auth"]
    assert store.writes == []
    _assert_hidden(bad, out.getvalue(), err.getvalue())
    _assert_hidden(BRIDGE, out.getvalue(), err.getvalue())


def test_scripts_do_not_read_the_bridge_secret_or_take_a_token_argument():
    cli = open(os.path.join(ROOT, "scripts", "proton-mail-mcp-clipboard-auth.py"), encoding="utf-8").read()
    helper = open(os.path.join(ROOT, "scripts", "connector", "clipboard_auth.py"), encoding="utf-8").read()
    ps1 = open(os.path.join(ROOT, "scripts", "windows", "copy-http-auth.ps1"), encoding="utf-8").read()
    assert "bridge-imap" not in cli.lower()
    assert "BRIDGE_IMAP" not in cli
    assert ".put(" not in cli
    assert "urllib" not in helper and "http.client" not in helper and "socket" not in helper
    assert "bridge-imap" not in ps1.lower()
    assert "Read-Host" not in ps1
    assert "Set-Clipboard" not in ps1
    assert "--confirm" in ps1
    planted = "LEAKED-ARGUMENT"
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "proton-mail-mcp-clipboard-auth.py"), "--confirm", planted],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    _assert_hidden(planted, proc.stdout, proc.stderr)
    assert "arguments rejected" in proc.stderr


def test_windows_clipboard_opts_out_clears_and_preserves_newer_text():
    if sys.platform != "win32":
        pytest.skip("Win32 clipboard is tested on Windows")
    from connector.clipboard_auth import WindowsClipboard

    token = _token()
    value = authorization_value(token)
    expected_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
    newer = "NEWER-CLIPBOARD-CONTENT"
    newer_hash = hashlib.sha256(newer.encode("utf-8")).hexdigest()
    clip = WindowsClipboard()
    try:
        clip.prepare()
        clip.place(value)
        snap = clip.snapshot()
        if snap["exclude"] is not True or snap["history"] != 0 or snap["cloud"] != 0:
            raise AssertionError(
                "opt-out formats missing "
                + str((snap["exclude"], snap["history"], snap["cloud"], clip.last_error))
            )
        if snap["text_sha256"] != expected_hash:
            raise AssertionError("clipboard payload mismatch")
        clip._open()
        try:
            clip.empty()
            clip._set_bytes(CF_UNICODETEXT, newer.encode("utf-16-le") + b"\x00\x00")
        finally:
            clip._close_clipboard()
        if clip.clear_if_unchanged(value) != "preserved":
            raise AssertionError("newer clipboard content was removed")
        if clip.snapshot()["text_sha256"] != newer_hash:
            raise AssertionError("newer clipboard content was not left in place")
        clip.place(value)
        if clip.clear_if_unchanged(value) != "cleared":
            raise AssertionError("unchanged authorization value was not cleared")
        if clip.snapshot()["text_sha256"] == expected_hash:
            raise AssertionError("authorization value remained on the clipboard")
        clip.close()
        fresh = WindowsClipboard()
        try:
            store = SpyStore({"http-auth": token, "bridge-imap": BRIDGE})
            out, err = _silent()
            seen: dict[str, object] = {}

            def sleep(_seconds: int) -> None:
                seen["snap"] = fresh.snapshot()

            code = run_handoff(store, fresh, 15, sleep, out, err)
            if code != 0:
                raise AssertionError("handoff failed " + str(fresh.last_error))
            held = seen.get("snap")
            if not isinstance(held, dict) or held.get("text_sha256") != expected_hash:
                raise AssertionError("clipboard payload mismatch")
            if held.get("exclude") is not True or held.get("history") != 0 or held.get("cloud") != 0:
                raise AssertionError("opt-out formats missing during handoff")
            _assert_hidden(token, out.getvalue(), err.getvalue())
            _assert_hidden(BRIDGE, out.getvalue(), err.getvalue())
            assert store.gets == ["http-auth"]
            assert store.writes == []
            assert "Clipboard cleared." in out.getvalue()
        finally:
            try:
                if fresh._hwnd:
                    fresh._open()
                    fresh.empty()
                    fresh._close_clipboard()
            except Exception:
                pass
            fresh.close()
    finally:
        try:
            if clip._hwnd:
                clip._open()
                clip.empty()
                clip._close_clipboard()
        except Exception:
            pass
        clip.close()


def test_powershell_refuses_unconfirmed_or_unbounded_runs_on_windows():
    if sys.platform != "win32":
        pytest.skip("PowerShell clipboard wrapper is tested on Windows")
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("powershell.exe is not available")
    script = os.path.join(ROOT, "scripts", "windows", "copy-http-auth.ps1")
    plain = subprocess.run(
        [powershell, "-NoProfile", "-File", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert plain.returncode != 0
    assert "without -Confirm" in (plain.stderr + plain.stdout)
    env = dict(os.environ)
    env["PYTHON_EXE"] = r"C:\missing\python-not-used.exe"
    bounded = subprocess.run(
        [powershell, "-NoProfile", "-File", script, "-Confirm", "-Seconds", "1"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert bounded.returncode != 0
    assert "15 through 90" in (bounded.stderr + bounded.stdout)
    assert "python-not-used" not in (bounded.stderr + bounded.stdout)
