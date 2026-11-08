"""OS secret stores. HTTP handlers never choose the target name."""
from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

BRIDGE_IMAP = "bridge-imap"
HTTP_AUTH = "http-auth"
LOGICAL_NAMES = (BRIDGE_IMAP, HTTP_AUTH)

WINDOWS_TARGETS = {
    BRIDGE_IMAP: "proton-mail-mcp:bridge-imap",
    HTTP_AUTH: "proton-mail-mcp:http-auth",
    # Used only by the Windows CI round-trip. The HTTP server never reads it.
    "ci-dummy": "proton-mail-mcp:ci-dummy",
}
PASS_KEYS = {
    BRIDGE_IMAP: "proton-bridge/imap",
    HTTP_AUTH: "proton-mail-mcp/http-auth",
}

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class SecretStoreError(RuntimeError):
    pass


def decode_credential_blob(raw: bytes) -> str:
    """Decode a Windows CredentialBlob (cmdkey is UTF-16-LE; our writer is too)."""
    if not raw:
        return ""
    if len(raw) >= 2 and len(raw) % 2 == 0 and raw[1] == 0:
        return raw.decode("utf-16-le").rstrip("\x00")
    return raw.decode("utf-8").rstrip("\x00")


def tokens_equal(left: str, right: str) -> bool:
    import hashlib
    import hmac

    return hmac.compare_digest(
        hashlib.sha256(left.encode("utf-8")).digest(),
        hashlib.sha256(right.encode("utf-8")).digest(),
    )


class MemorySecretStore:
    """Test double. Not selectable from the CLI."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)

    def get(self, logical_name: str) -> str | None:
        if logical_name not in LOGICAL_NAMES:
            raise SecretStoreError("unknown secret name")
        value = self._values.get(logical_name)
        return value if value else None


class PassSecretStore:
    """Linux ``pass`` store. The key is a fixed string, never an HTTP input."""

    def get(self, logical_name: str) -> str | None:
        key = PASS_KEYS.get(logical_name)
        if key is None:
            raise SecretStoreError("unknown secret name")
        try:
            proc = subprocess.run(
                ["pass", key],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
        except (OSError, FileNotFoundError):
            return None
        if proc.returncode != 0:
            return None
        secret = proc.stdout[:-1] if proc.stdout.endswith("\n") else proc.stdout
        return secret or None


def _credential_struct():
    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", ctypes.c_wchar_p),
            ("Comment", ctypes.c_wchar_p),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]

    return CREDENTIALW


class WindowsCredentialStore:
    """Generic credentials in the Windows Credential Manager. No CLI secrets."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise SecretStoreError("Windows Credential Manager is only available on Windows")
        self._advapi = ctypes.WinDLL("advapi32")
        self._cred = _credential_struct()
        self._advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(self._cred)),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(self._cred), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    def _target(self, logical_name: str) -> str:
        target = WINDOWS_TARGETS.get(logical_name)
        if target is None:
            raise SecretStoreError("unknown secret name")
        return target

    def get(self, logical_name: str) -> str | None:
        target = self._target(logical_name)
        pointer = ctypes.POINTER(self._cred)()
        ok = self._advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer))
        if not ok or not pointer:
            return None
        try:
            size = int(pointer.contents.CredentialBlobSize)
            blob_ptr = pointer.contents.CredentialBlob
            raw = ctypes.string_at(blob_ptr, size) if blob_ptr and size else b""
            text = decode_credential_blob(raw)
            return text or None
        finally:
            self._advapi.CredFree(pointer)

    def put(self, logical_name: str, secret: str) -> None:
        if not secret or "\x00" in secret or "\r" in secret or "\n" in secret:
            raise SecretStoreError("refusing to store an empty or multiline secret")
        target = self._target(logical_name)
        blob = secret.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(blob)
        cred = self._cred()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "proton-mail-mcp"
        if not self._advapi.CredWriteW(ctypes.byref(cred), 0):
            raise SecretStoreError("Credential Manager rejected the write")

    def delete(self, logical_name: str) -> None:
        target = self._target(logical_name)
        self._advapi.CredDeleteW(target, CRED_TYPE_GENERIC, 0)
