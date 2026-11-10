"""Login-keychain store for the Mac connector.

Uses the legacy Security framework so the item stays in the user login
keychain and is not written with SecItemAdd, which targets the iCloud data
protection keychain. The password is never a command-line argument.

The login keychain is the trust boundary: any process of this user can read
the item while the keychain is unlocked. That matches the Windows Credential
Manager entry for the signed-in user. The value is not a file in the repo.
"""
from __future__ import annotations

import sys

from connector.secrets import LOGICAL_NAMES, WINDOWS_TARGETS, SecretStoreError

ACCOUNT = "proton-mail-mcp"
ERR_ITEM_NOT_FOUND = -25300
ERR_USER_CANCELED = -128
ERR_AUTH_FAILED = -25293
ERR_INTERACTION_NOT_ALLOWED = -25308


class KeychainStore:
    """Logical names only. ``backend`` is a test double or the Security framework."""

    def __init__(self, backend: object) -> None:
        self._backend = backend
        self.unattended = True

    def get(self, logical_name: str) -> str | None:
        service = _service(logical_name)
        try:
            return self._backend.get(service, ACCOUNT)  # type: ignore[attr-defined]
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError("keychain read failed") from None

    def put(self, logical_name: str, secret: str) -> None:
        if logical_name not in LOGICAL_NAMES and logical_name != "ci-dummy":
            raise SecretStoreError("unknown secret name")
        if not secret or any(ch in secret for ch in "\r\n\x00"):
            raise SecretStoreError("refusing to store an empty or multiline secret")
        service = _service(logical_name)
        try:
            unattended = self._backend.put(service, ACCOUNT, secret)  # type: ignore[attr-defined]
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError("keychain write failed") from None
        self.unattended = bool(unattended)

    def delete(self, logical_name: str) -> None:
        service = _service(logical_name)
        try:
            self._backend.delete(service, ACCOUNT)  # type: ignore[attr-defined]
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError("keychain delete failed") from None


def _service(logical_name: str) -> str:
    service = WINDOWS_TARGETS.get(logical_name)
    if service is None:
        raise SecretStoreError("unknown secret name")
    return service


class MacKeychainStore(KeychainStore):
    """Default login keychain. Constructed only on macOS."""

    def __init__(self, keychain_path: str | None = None, unlock_password: str | None = None) -> None:
        if sys.platform != "darwin":
            raise SecretStoreError("macOS Keychain is only available on macOS")
        super().__init__(_SecurityBackend(keychain_path, unlock_password))


class _SecurityBackend:
    def __init__(self, keychain_path: str | None, unlock_password: str | None) -> None:
        import ctypes

        self._ctypes = ctypes
        self._security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self._core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self._bind()
        self._keychain = ctypes.c_void_p()
        if keychain_path:
            self._open(keychain_path, unlock_password)

    def _bind(self) -> None:
        ctypes = self._ctypes
        security = self._security
        core = self._core
        security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        security.SecKeychainItemModifyAttributesAndData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        security.SecKeychainItemDelete.restype = ctypes.c_int32
        security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        security.SecKeychainOpen.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        security.SecKeychainOpen.restype = ctypes.c_int32
        security.SecKeychainUnlock.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint8,
        ]
        security.SecKeychainUnlock.restype = ctypes.c_int32
        security.SecKeychainCreate.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint8,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainCreate.restype = ctypes.c_int32
        security.SecKeychainDelete.argtypes = [ctypes.c_void_p]
        security.SecKeychainDelete.restype = ctypes.c_int32
        core.CFRelease.argtypes = [ctypes.c_void_p]
        core.CFRelease.restype = None
        core.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        core.CFArrayGetCount.restype = ctypes.c_long
        core.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        core.CFArrayGetValueAtIndex.restype = ctypes.c_void_p

    def _open(self, path: str, password: str | None) -> None:
        status = self._security.SecKeychainOpen(path.encode("utf-8"), self._ctypes.byref(self._keychain))
        _check(status, "keychain open failed")
        if password is None:
            return
        encoded = password.encode("utf-8")
        buffer = self._ctypes.create_string_buffer(encoded)
        status = self._security.SecKeychainUnlock(
            self._keychain,
            len(encoded),
            self._ctypes.cast(buffer, self._ctypes.c_void_p),
            1,
        )
        _check(status, "keychain unlock failed")

    def _ref(self) -> object:
        return self._keychain if self._keychain else None

    def get(self, service: str, account: str) -> str | None:
        item, secret = self._find(service, account, keep_secret=True)
        if item:
            self._core.CFRelease(item)
        return secret

    def put(self, service: str, account: str, secret: str) -> bool:
        encoded = secret.encode("utf-8")
        item, _existing = self._find(service, account, keep_secret=False)
        try:
            if item is None:
                item = self._add(service, account, encoded)
            else:
                self._update(item, encoded)
            return self._allow_any_app(item)
        finally:
            if item:
                self._core.CFRelease(item)

    def delete(self, service: str, account: str) -> None:
        item, _existing = self._find(service, account, keep_secret=False)
        if item is None:
            return
        try:
            status = self._security.SecKeychainItemDelete(item)
            _check(status, "keychain delete failed")
        finally:
            self._core.CFRelease(item)

    def _find(self, service: str, account: str, *, keep_secret: bool) -> tuple[object | None, str | None]:
        ctypes = self._ctypes
        service_b = service.encode("utf-8")
        account_b = account.encode("utf-8")
        length = ctypes.c_uint32()
        data = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = self._security.SecKeychainFindGenericPassword(
            self._ref(),
            len(service_b),
            service_b,
            len(account_b),
            account_b,
            ctypes.byref(length),
            ctypes.byref(data),
            ctypes.byref(item),
        )
        if status == ERR_ITEM_NOT_FOUND:
            return None, None
        _check(status, "keychain read failed")
        secret = None
        if keep_secret and data.value and length.value:
            raw = ctypes.string_at(data.value, length.value)
            secret = raw.decode("utf-8")
        if data.value:
            self._security.SecKeychainItemFreeContent(None, data)
        return item, secret or None

    def _add(self, service: str, account: str, encoded: bytes) -> object:
        ctypes = self._ctypes
        service_b = service.encode("utf-8")
        account_b = account.encode("utf-8")
        buffer = ctypes.create_string_buffer(encoded)
        item = ctypes.c_void_p()
        status = self._security.SecKeychainAddGenericPassword(
            self._ref(),
            len(service_b),
            service_b,
            len(account_b),
            account_b,
            len(encoded),
            ctypes.cast(buffer, ctypes.c_void_p),
            ctypes.byref(item),
        )
        _check(status, "keychain write failed")
        if not item.value:
            raise SecretStoreError("keychain write failed")
        return item

    def _update(self, item: object, encoded: bytes) -> None:
        ctypes = self._ctypes
        buffer = ctypes.create_string_buffer(encoded)
        status = self._security.SecKeychainItemModifyAttributesAndData(
            item,
            None,
            len(encoded),
            ctypes.cast(buffer, ctypes.c_void_p),
        )
        _check(status, "keychain write failed")

    def _allow_any_app(self, item: object) -> bool:
        """Match ``security add-generic-password -A``. False means a prompt may remain."""
        ctypes = self._ctypes
        security = self._security

        class Prompt(ctypes.Structure):
            _fields_ = [("version", ctypes.c_uint16), ("flags", ctypes.c_uint16)]

        try:
            security.SecKeychainItemCopyAccess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            security.SecKeychainItemCopyAccess.restype = ctypes.c_int32
            security.SecAccessCopyACLList.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            security.SecAccessCopyACLList.restype = ctypes.c_int32
            security.SecKeychainItemSetAccess.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            security.SecKeychainItemSetAccess.restype = ctypes.c_int32
            security.SecACLCopySimpleContents.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(Prompt),
            ]
            security.SecACLCopySimpleContents.restype = ctypes.c_int32
            security.SecACLSetSimpleContents.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(Prompt),
            ]
            security.SecACLSetSimpleContents.restype = ctypes.c_int32
        except AttributeError:
            return False

        access = ctypes.c_void_p()
        status = security.SecKeychainItemCopyAccess(item, ctypes.byref(access))
        if status != 0 or not access.value:
            return False
        acl_list = ctypes.c_void_p()
        try:
            status = security.SecAccessCopyACLList(access, ctypes.byref(acl_list))
            if status != 0 or not acl_list.value:
                return False
            count = int(self._core.CFArrayGetCount(acl_list))
            for index in range(count):
                acl = self._core.CFArrayGetValueAtIndex(acl_list, index)
                apps = ctypes.c_void_p()
                description = ctypes.c_void_p()
                prompt = Prompt()
                copied = security.SecACLCopySimpleContents(
                    acl,
                    ctypes.byref(apps),
                    ctypes.byref(description),
                    ctypes.byref(prompt),
                )
                if copied != 0:
                    continue
                prompt.flags = 0
                updated = security.SecACLSetSimpleContents(acl, None, description, ctypes.byref(prompt))
                if apps.value:
                    self._core.CFRelease(apps)
                if description.value:
                    self._core.CFRelease(description)
                if updated != 0:
                    return False
            status = security.SecKeychainItemSetAccess(item, access)
            return status == 0
        finally:
            if acl_list.value:
                self._core.CFRelease(acl_list)
            self._core.CFRelease(access)


def _check(status: int, message: str) -> None:
    if status == 0:
        return
    if status == ERR_USER_CANCELED:
        raise SecretStoreError("keychain prompt was canceled")
    if status in (ERR_AUTH_FAILED, ERR_INTERACTION_NOT_ALLOWED):
        raise SecretStoreError("login keychain is locked; unlock it and try again")
    raise SecretStoreError(message)


def create_test_keychain(path: str, password: str) -> None:
    """Create an unlocked keychain file for tests. Not used by the connector."""
    if sys.platform != "darwin":
        raise SecretStoreError("macOS Keychain is only available on macOS")
    backend = _SecurityBackend(None, None)
    ctypes = backend._ctypes
    encoded = password.encode("utf-8")
    buffer = ctypes.create_string_buffer(encoded)
    ref = ctypes.c_void_p()
    status = backend._security.SecKeychainCreate(
        path.encode("utf-8"),
        len(encoded),
        ctypes.cast(buffer, ctypes.c_void_p),
        0,
        None,
        ctypes.byref(ref),
    )
    _check(status, "keychain open failed")
    if ref.value:
        backend._core.CFRelease(ref)
