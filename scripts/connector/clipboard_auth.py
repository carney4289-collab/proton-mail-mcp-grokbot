"""Copy the HTTP bearer to the Windows clipboard without history or cloud sync.

The token is supplied by the caller. This module does not print it, write it
to a file, or accept it as a command-line argument. Opt-out uses the formats
documented under "Cloud Clipboard and Clipboard History Formats":

- ExcludeClipboardContentFromMonitorProcessing with real data
- CanIncludeInClipboardHistory as a DWORD 0
- CanUploadToCloudClipboard as a DWORD 0

If those formats cannot be registered, set, and read back, the clipboard is
emptied and the copy fails. There is no copy without the opt-out.
"""
from __future__ import annotations

import sys
import time
from collections.abc import Callable

from connector.secrets import HTTP_AUTH, tokens_equal

FORMAT_EXCLUDE = "ExcludeClipboardContentFromMonitorProcessing"
FORMAT_HISTORY = "CanIncludeInClipboardHistory"
FORMAT_CLOUD = "CanUploadToCloudClipboard"
OPT_OUT_FORMATS = (FORMAT_EXCLUDE, FORMAT_HISTORY, FORMAT_CLOUD)
MIN_SECONDS = 15
MAX_SECONDS = 90
DEFAULT_SECONDS = 45
# Clipboard history and the cloud clipboard formats shipped in Windows 10 1809.
MIN_WINDOWS_BUILD = 17763
TOKEN_LENGTH = 43
_TOKEN_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
# CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT.
_CLEAR_ON_CONTROL = frozenset({2, 5, 6})
CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_GMEM_ZEROINIT = 0x0040
_ERROR_CLASS_ALREADY_EXISTS = 1410


class ClipboardHandoffError(Exception):
    def __init__(self, message: str, *, clipboard_cleared: bool = False) -> None:
        super().__init__(message)
        self.clipboard_cleared = clipboard_cleared


def token_ok(token: object) -> bool:
    if not isinstance(token, str) or len(token) != TOKEN_LENGTH:
        return False
    return all(char in _TOKEN_ALPHABET for char in token)


def authorization_value(token: object) -> str:
    if not token_ok(token):
        raise ClipboardHandoffError("http-auth token is missing or invalid")
    return "Bearer " + str(token)


def windows_supports_clipboard_opt_out(version: tuple[int, int, int]) -> bool:
    major, minor, build = version
    return major > 10 or (major == 10 and minor == 0 and build >= MIN_WINDOWS_BUILD)


def control_event_should_clear(ctrl_type: int) -> bool:
    return ctrl_type in _CLEAR_ON_CONTROL


def parse_cli(argv: list[str]) -> int:
    """Accept only --confirm and an optional bounded --seconds. Never echo argv."""
    if not argv or argv[0] != "--confirm":
        raise ClipboardHandoffError("confirmation required")
    rest = argv[1:]
    if not rest:
        return DEFAULT_SECONDS
    if len(rest) != 2 or rest[0] != "--seconds" or not rest[1].isdigit():
        raise ClipboardHandoffError("arguments rejected")
    seconds = int(rest[1])
    if str(seconds) != rest[1] or seconds < MIN_SECONDS or seconds > MAX_SECONDS:
        raise ClipboardHandoffError("arguments rejected")
    return seconds


def commit_clipboard(driver: object, value: str) -> None:
    """Empty, set opt-out, then text. Any failure empties again and leaves no text."""
    driver.empty()  # type: ignore[attr-defined]
    try:
        driver.set_exclude()  # type: ignore[attr-defined]
        driver.set_dword(FORMAT_HISTORY, 0)  # type: ignore[attr-defined]
        driver.set_dword(FORMAT_CLOUD, 0)  # type: ignore[attr-defined]
        driver.set_text(value)  # type: ignore[attr-defined]
        if not driver.opt_out_ok():  # type: ignore[attr-defined]
            raise ClipboardHandoffError("clipboard opt-out is not available")
    except Exception:
        driver.empty()  # type: ignore[attr-defined]
        raise ClipboardHandoffError(
            "clipboard opt-out is not available",
            clipboard_cleared=True,
        ) from None
    except BaseException:
        driver.empty()  # type: ignore[attr-defined]
        raise


def run_handoff(
    store: object,
    clipboard: object,
    seconds: int,
    sleep: Callable[[int], None],
    stdout: object,
    stderr: object,
) -> int:
    if seconds < MIN_SECONDS or seconds > MAX_SECONDS:
        stderr.write("proton-mail-mcp-clipboard-auth: arguments rejected\n")  # type: ignore[attr-defined]
        return 2
    try:
        try:
            clipboard.prepare()  # type: ignore[attr-defined]
        except ClipboardHandoffError as exc:
            stderr.write(f"proton-mail-mcp-clipboard-auth: {exc}\n")  # type: ignore[attr-defined]
            return 2
        try:
            token = store.get(HTTP_AUTH)  # type: ignore[attr-defined]
        except Exception:
            stderr.write("proton-mail-mcp-clipboard-auth: http-auth token is not available\n")  # type: ignore[attr-defined]
            return 2
        try:
            value = authorization_value(token)
        except ClipboardHandoffError:
            stderr.write("proton-mail-mcp-clipboard-auth: http-auth token is missing or invalid\n")  # type: ignore[attr-defined]
            return 2
        try:
            clipboard.place(value)  # type: ignore[attr-defined]
        except ClipboardHandoffError as exc:
            stderr.write(f"proton-mail-mcp-clipboard-auth: {exc}\n")  # type: ignore[attr-defined]
            if exc.clipboard_cleared:
                stderr.write(
                    "proton-mail-mcp-clipboard-auth: The clipboard was cleared and the Authorization value was not left on it.\n"
                )  # type: ignore[attr-defined]
            return 2
        interrupted = False
        outcome = None
        try:
            arm = getattr(clipboard, "arm_process_exit_clear", None)
            if arm is not None:
                try:
                    arm(value)
                except Exception:
                    pass
            stdout.write("Authorization value is on the clipboard.\n")  # type: ignore[attr-defined]
            stdout.write(
                f"Paste it into the Authorization value field. It stays for {seconds} seconds.\n"
            )  # type: ignore[attr-defined]
            stdout.write("If you copy something else, that newer copy is left in place.\n")  # type: ignore[attr-defined]
            sleep(seconds)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            disarm = getattr(clipboard, "disarm_process_exit_clear", None)
            if disarm is not None:
                try:
                    disarm()
                except Exception:
                    pass
            try:
                outcome = clipboard.clear_if_unchanged(value)  # type: ignore[attr-defined]
            except Exception:
                stderr.write(
                    "proton-mail-mcp-clipboard-auth: clipboard could not be verified; clear it manually if the Authorization value is still there.\n"
                )  # type: ignore[attr-defined]
                return 2
        if outcome == "cleared":
            stdout.write("Clipboard cleared.\n")  # type: ignore[attr-defined]
        elif outcome == "preserved":
            stdout.write("Clipboard changed; left in place.\n")  # type: ignore[attr-defined]
        else:
            stderr.write("proton-mail-mcp-clipboard-auth: clipboard handoff failed\n")  # type: ignore[attr-defined]
            return 2
        return 2 if interrupted else 0
    finally:
        closer = getattr(clipboard, "close", None)
        if closer is not None:
            closer()


class WindowsClipboard:
    """Win32 clipboard owner. Constructed only on Windows, and only after --confirm."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise ClipboardHandoffError("clipboard handoff is only supported on Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        self._bind()
        self._hwnd = None
        self._proc = None
        self._class_name = "ProtonMailMcpClipboardAuth"
        self._formats: dict[str, int] = {}
        self._expected: str | None = None
        self._handler = None
        self.last_error = 0

    def _bind(self) -> None:
        ctypes = self._ctypes
        wintypes = self._wintypes
        user32 = self._user32
        kernel32 = self._kernel32
        ntdll = self._ntdll
        user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClipboardFormatW.restype = wintypes.UINT
        user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClipboardFormatNameW.restype = ctypes.c_int
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        kernel32.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
        kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
        ntdll.RtlGetVersion.argtypes = [ctypes.c_void_p]
        ntdll.RtlGetVersion.restype = wintypes.LONG

    def prepare(self) -> None:
        version = self._windows_version()
        if not windows_supports_clipboard_opt_out(version):
            raise ClipboardHandoffError("clipboard opt-out is not available")
        self._formats = self._register_formats()
        if self._hwnd:
            self._user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        self._hwnd = self._create_owner_window()

    def close(self) -> None:
        self.disarm_process_exit_clear()
        hwnd = self._hwnd
        self._hwnd = None
        if hwnd:
            self._user32.DestroyWindow(hwnd)

    def place(self, value: str) -> None:
        prefix = "Bearer "
        token = value[len(prefix) :] if value.startswith(prefix) else ""
        if value != authorization_value(token):
            raise ClipboardHandoffError("http-auth token is missing or invalid")
        if not self._hwnd or len(self._formats) != 3:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        self._open()
        try:
            commit_clipboard(self, value)
        finally:
            self._close_clipboard()

    def empty(self) -> None:
        if not self._user32.EmptyClipboard():
            self.last_error = self._ctypes.get_last_error()
            raise ClipboardHandoffError("clipboard opt-out is not available")
        self._expected = None

    def set_exclude(self) -> None:
        self._set_bytes(self._formats[FORMAT_EXCLUDE], b"\x00")

    def set_dword(self, name: str, value: int) -> None:
        if name not in (FORMAT_HISTORY, FORMAT_CLOUD) or value != 0:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        self._set_bytes(self._formats[name], (0).to_bytes(4, "little"))

    def set_text(self, value: str) -> None:
        data = value.encode("utf-16-le") + b"\x00\x00"
        self._set_bytes(CF_UNICODETEXT, data)
        self._expected = value

    def opt_out_ok(self) -> bool:
        expected = self._expected
        if not isinstance(expected, str):
            return False
        if not self._user32.IsClipboardFormatAvailable(self._formats[FORMAT_EXCLUDE]):
            return False
        if self._read_dword(self._formats[FORMAT_HISTORY]) != 0:
            return False
        if self._read_dword(self._formats[FORMAT_CLOUD]) != 0:
            return False
        current = self._read_text(len(expected))
        return isinstance(current, str) and tokens_equal(current, expected)

    def clear_if_unchanged(self, expected: str) -> str:
        self._open()
        try:
            current = self._read_text(len(expected))
            if not isinstance(current, str) or not tokens_equal(current, expected):
                return "preserved"
            if not self._user32.EmptyClipboard():
                self.last_error = self._ctypes.get_last_error()
                raise ClipboardHandoffError("clipboard could not be cleared")
            self._expected = None
            return "cleared"
        finally:
            self._close_clipboard()

    def arm_process_exit_clear(self, expected: str) -> None:
        ctypes = self._ctypes
        wintypes = self._wintypes

        def handler(ctrl_type: int) -> bool:
            if not control_event_should_clear(int(ctrl_type)):
                return False
            try:
                self.clear_if_unchanged(expected)
            except Exception:
                return True
            return True

        routine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(handler)
        pointer = ctypes.cast(routine, ctypes.c_void_p)
        if not self._kernel32.SetConsoleCtrlHandler(pointer, True):
            self.last_error = ctypes.get_last_error()
            return
        self._handler = routine

    def disarm_process_exit_clear(self) -> None:
        handler = self._handler
        self._handler = None
        if handler is None:
            return
        try:
            pointer = self._ctypes.cast(handler, self._ctypes.c_void_p)
            self._kernel32.SetConsoleCtrlHandler(pointer, False)
        except Exception:
            return

    def snapshot(self) -> dict[str, object]:
        """Format flags and a hash of the text. The text itself is not returned."""
        import hashlib

        self._open()
        try:
            text = self._read_text(256)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if isinstance(text, str) else ""
            return {
                "exclude": bool(self._user32.IsClipboardFormatAvailable(self._formats[FORMAT_EXCLUDE])),
                "history": self._read_dword(self._formats[FORMAT_HISTORY]),
                "cloud": self._read_dword(self._formats[FORMAT_CLOUD]),
                "text_sha256": digest,
            }
        finally:
            self._close_clipboard()

    def _windows_version(self) -> tuple[int, int, int]:
        ctypes = self._ctypes
        wintypes = self._wintypes

        class OSVERSIONINFOW(ctypes.Structure):
            _fields_ = [
                ("dwOSVersionInfoSize", wintypes.DWORD),
                ("dwMajorVersion", wintypes.DWORD),
                ("dwMinorVersion", wintypes.DWORD),
                ("dwBuildNumber", wintypes.DWORD),
                ("dwPlatformId", wintypes.DWORD),
                ("szCSDVersion", wintypes.WCHAR * 128),
            ]

        info = OSVERSIONINFOW()
        info.dwOSVersionInfoSize = ctypes.sizeof(info)
        status = self._ntdll.RtlGetVersion(ctypes.byref(info))
        if status != 0:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        return (int(info.dwMajorVersion), int(info.dwMinorVersion), int(info.dwBuildNumber))

    def _register_formats(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for name in OPT_OUT_FORMATS:
            fmt = int(self._user32.RegisterClipboardFormatW(name) or 0)
            if fmt < 0xC000 or fmt > 0xFFFF:
                raise ClipboardHandoffError("clipboard opt-out is not available")
            buf = self._ctypes.create_unicode_buffer(256)
            length = int(self._user32.GetClipboardFormatNameW(fmt, buf, 256) or 0)
            if length <= 0 or buf.value.lower() != name.lower():
                raise ClipboardHandoffError("clipboard opt-out is not available")
            found[name] = fmt
        return found

    def _create_owner_window(self) -> object:
        ctypes = self._ctypes
        wintypes = self._wintypes

        def proc(hwnd, msg, wparam, lparam):  # type: ignore[no-untyped-def]
            return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )(proc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        instance = self._kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
        window_class.hInstance = instance
        window_class.lpszClassName = self._class_name
        atom = self._user32.RegisterClassW(ctypes.byref(window_class))
        if not atom and self._ctypes.get_last_error() != _ERROR_CLASS_ALREADY_EXISTS:
            self.last_error = self._ctypes.get_last_error()
            raise ClipboardHandoffError("clipboard opt-out is not available")
        hwnd = self._user32.CreateWindowExW(
            0x08000080,  # WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            self._class_name,
            "proton-mail-mcp",
            0x80000000,  # WS_POPUP, not visible
            0,
            0,
            0,
            0,
            None,
            None,
            instance,
            None,
        )
        if not hwnd:
            self.last_error = self._ctypes.get_last_error()
            raise ClipboardHandoffError("clipboard opt-out is not available")
        return hwnd

    def _open(self) -> None:
        if not self._hwnd:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        for _ in range(20):
            if self._user32.OpenClipboard(self._hwnd):
                return
            self.last_error = self._ctypes.get_last_error()
            time.sleep(0.05)
        raise ClipboardHandoffError("clipboard is busy")

    def _close_clipboard(self) -> None:
        self._user32.CloseClipboard()

    def _set_bytes(self, fmt: int, data: bytes) -> None:
        handle = self._kernel32.GlobalAlloc(_GMEM_MOVEABLE | _GMEM_ZEROINIT, len(data))
        if not handle:
            self.last_error = self._ctypes.get_last_error()
            raise ClipboardHandoffError("clipboard opt-out is not available")
        locked = self._kernel32.GlobalLock(handle)
        if not locked:
            self._kernel32.GlobalFree(handle)
            self.last_error = self._ctypes.get_last_error()
            raise ClipboardHandoffError("clipboard opt-out is not available")
        self._ctypes.memmove(locked, data, len(data))
        self._kernel32.GlobalUnlock(handle)
        if not self._user32.SetClipboardData(fmt, handle):
            self.last_error = self._ctypes.get_last_error()
            self._kernel32.GlobalFree(handle)
            raise ClipboardHandoffError("clipboard opt-out is not available")

    def _read_dword(self, fmt: int) -> int | None:
        if not self._user32.IsClipboardFormatAvailable(fmt):
            return None
        handle = self._user32.GetClipboardData(fmt)
        if not handle:
            return None
        locked = self._kernel32.GlobalLock(handle)
        if not locked:
            return None
        try:
            raw = self._ctypes.string_at(locked, 4)
        finally:
            self._kernel32.GlobalUnlock(handle)
        if len(raw) != 4:
            return None
        return int.from_bytes(raw, "little")

    def _read_text(self, limit: int) -> str | None:
        if limit < 0 or limit > 256:
            return None
        if not self._user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = self._user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        locked = self._kernel32.GlobalLock(handle)
        if not locked:
            return None
        try:
            size = int(self._kernel32.GlobalSize(handle) or 0)
            max_codes = min(limit + 1, size // 2)
            if max_codes <= 0:
                return None
            pointer = self._ctypes.cast(locked, self._ctypes.POINTER(self._ctypes.c_uint16))
            codes: list[int] = []
            for index in range(max_codes):
                code = int(pointer[index])
                if code == 0:
                    return "".join(chr(item) for item in codes)
                if len(codes) >= limit:
                    return None
                codes.append(code)
            return None
        finally:
            self._kernel32.GlobalUnlock(handle)
