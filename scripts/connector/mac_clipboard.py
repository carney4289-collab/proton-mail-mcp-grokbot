"""Copy the bearer to the macOS pasteboard without printing it.

Opt-out uses the public pasteboard types clipboard managers honor, plus the
AppKit flag that keeps the copy on this Mac:

- public.utf8-plain-text holds ``Bearer`` and the token
- org.nspasteboard.ConcealedType marks it as a secret
- org.nspasteboard.TransientType asks managers not to record it
- NSPasteboardContentsCurrentHostOnly keeps it off Universal Clipboard

If those cannot be set and read back, the pasteboard is cleared. There is
no copy without the opt-out.
"""
from __future__ import annotations

import sys

from connector.clipboard_auth import ClipboardHandoffError, authorization_value
from connector.secrets import tokens_equal

TYPE_TEXT = "public.utf8-plain-text"
TYPE_CONCEALED = "org.nspasteboard.ConcealedType"
TYPE_TRANSIENT = "org.nspasteboard.TransientType"
MARKER_TYPES = (TYPE_CONCEALED, TYPE_TRANSIENT)
# NSPasteboardContentsCurrentHostOnly
CURRENT_HOST_ONLY = 1


def commit_mac_clipboard(driver: object, value: str) -> None:
    """Clear, restrict to this Mac, then set the text and the two marker types."""
    prefix = "Bearer "
    token = value[len(prefix) :] if value.startswith(prefix) else ""
    if value != authorization_value(token):
        raise ClipboardHandoffError("http-auth token is missing or invalid")
    driver.clear()  # type: ignore[attr-defined]
    try:
        driver.prepare_current_host_only()  # type: ignore[attr-defined]
        driver.set_string(value, TYPE_TEXT)  # type: ignore[attr-defined]
        for name in MARKER_TYPES:
            driver.set_string("1", name)  # type: ignore[attr-defined]
        if not driver.opt_out_ok(value):  # type: ignore[attr-defined]
            raise ClipboardHandoffError("clipboard opt-out is not available")
    except ClipboardHandoffError:
        driver.clear()  # type: ignore[attr-defined]
        raise ClipboardHandoffError(
            "clipboard opt-out is not available",
            clipboard_cleared=True,
        ) from None
    except Exception:
        driver.clear()  # type: ignore[attr-defined]
        raise ClipboardHandoffError(
            "clipboard opt-out is not available",
            clipboard_cleared=True,
        ) from None


def unchanged_outcome(current: str | None, expected: str) -> str:
    if not isinstance(current, str) or not tokens_equal(current, expected):
        return "preserved"
    return "cleared"


class MacPasteboard:
    """NSPasteboard owner. Constructed only on macOS, and only after --confirm."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise ClipboardHandoffError("clipboard handoff is only supported on macOS")
        self._appkit = None
        self._objc = None
        self._pasteboard = None
        self._ready = False

    def prepare(self) -> None:
        import ctypes

        self._objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        objc = self._objc
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        pasteboard_class = objc.objc_getClass(b"NSPasteboard")
        if not pasteboard_class:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        general = self._msg(ctypes.c_void_p, [], pasteboard_class, "generalPasteboard")
        if not general:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        self._pasteboard = general
        if not self._responds("prepareForNewContentsWithOptions:"):
            raise ClipboardHandoffError("clipboard opt-out is not available")
        if not self._responds("setString:forType:"):
            raise ClipboardHandoffError("clipboard opt-out is not available")
        self._ready = True

    def close(self) -> None:
        self._ready = False
        self._pasteboard = None

    def place(self, value: str) -> None:
        if not self._ready:
            raise ClipboardHandoffError("clipboard opt-out is not available")
        commit_mac_clipboard(_AppKitDriver(self), value)

    def clear_if_unchanged(self, expected: str) -> str:
        if not self._ready:
            raise ClipboardHandoffError("clipboard could not be verified")
        current = self._read(TYPE_TEXT)
        outcome = unchanged_outcome(current, expected)
        if outcome == "cleared":
            self._clear()
        return outcome

    def _clear(self) -> None:
        import ctypes

        self._msg(ctypes.c_long, [], self._pasteboard, "clearContents")

    def _responds(self, name: str) -> bool:
        import ctypes

        return bool(
            self._msg(
                ctypes.c_bool,
                [ctypes.c_void_p],
                self._pasteboard,
                "respondsToSelector:",
                self._sel(name),
            )
        )

    def _sel(self, name: str) -> object:
        return self._objc.sel_registerName(name.encode("utf-8"))

    def _msg(self, restype: object, argtypes: list[object], receiver: object, name: str, *args: object) -> object:
        import ctypes

        prototype = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
        function = prototype(("objc_msgSend", self._objc))
        return function(receiver, self._sel(name), *args)

    def _nsstring(self, text: str) -> object:
        import ctypes

        cls = self._objc.objc_getClass(b"NSString")
        return self._msg(
            ctypes.c_void_p,
            [ctypes.c_char_p],
            cls,
            "stringWithUTF8String:",
            text.encode("utf-8"),
        )

    def _read(self, paste_type: str) -> str | None:
        import ctypes

        value = self._msg(
            ctypes.c_void_p,
            [ctypes.c_void_p],
            self._pasteboard,
            "stringForType:",
            self._nsstring(paste_type),
        )
        if not value:
            return None
        raw = self._msg(ctypes.c_char_p, [], value, "UTF8String")
        if not raw:
            return None
        return raw.decode("utf-8")


class _AppKitDriver:
    def __init__(self, board: MacPasteboard) -> None:
        self._board = board

    def clear(self) -> None:
        self._board._clear()

    def prepare_current_host_only(self) -> None:
        import ctypes

        self._board._msg(
            ctypes.c_long,
            [ctypes.c_ulong],
            self._board._pasteboard,
            "prepareForNewContentsWithOptions:",
            CURRENT_HOST_ONLY,
        )

    def set_string(self, text: str, paste_type: str) -> None:
        import ctypes

        ok = self._board._msg(
            ctypes.c_bool,
            [ctypes.c_void_p, ctypes.c_void_p],
            self._board._pasteboard,
            "setString:forType:",
            self._board._nsstring(text),
            self._board._nsstring(paste_type),
        )
        if not ok:
            raise ClipboardHandoffError("clipboard opt-out is not available")

    def opt_out_ok(self, expected: str) -> bool:
        current = self._board._read(TYPE_TEXT)
        if not isinstance(current, str) or not tokens_equal(current, expected):
            return False
        return all(self._board._read(name) == "1" for name in MARKER_TYPES)
