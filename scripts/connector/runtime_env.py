"""Child environment for the Node MCP. Loopback mail only. No auth token."""
from __future__ import annotations

import os

from proton_mail_mcp_policy import DEFAULT_ALLOWED_ACTIONS, DEFAULT_ALLOWED_FOLDERS

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_KEEP_WINDOWS = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "COMSPEC",
    "PATHEXT",
)


class ConfigError(ValueError):
    pass


def _port(raw: str, name: str) -> str:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} is not a port") from exc
    if not 1 <= value <= 65535:
        raise ConfigError(f"{name} is not a port")
    return str(value)


def require_loopback(host: str, name: str) -> str:
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(f"{name} must stay on this computer's loopback")
    return host


def child_environment(source: dict[str, str], bridge_password: str) -> dict[str, str]:
    """Environment for the Node process. The bearer token is not copied."""
    if not bridge_password:
        raise ConfigError("bridge IMAP credential is missing")
    username = source.get("PROTONMAIL_USERNAME", "").strip()
    if not username:
        raise ConfigError("PROTONMAIL_USERNAME is not set")
    imap_host = require_loopback(source.get("IMAP_HOST", "127.0.0.1"), "IMAP_HOST")
    smtp_host = require_loopback(source.get("PROTONMAIL_HOST", "127.0.0.1"), "PROTONMAIL_HOST")
    # Same fail-closed defaults as the Linux stdio wrapper. A full tool
    # surface is what the Windows example sets on purpose, not an implicit default.
    env = {
        "READONLY": "false",
        "PROTONMAIL_ALLOW_SEND": "false",
        "PROTONMAIL_ALLOWED_ACTIONS": DEFAULT_ALLOWED_ACTIONS,
        "PROTONMAIL_ALLOWED_FOLDERS": DEFAULT_ALLOWED_FOLDERS,
        "ALLOW_EMPTY_FOLDER": "false",
        "RESTRICT_OUTBOUND_TO_SELF": "false",
        "IMAP_SECURE": "false",
        "PROTONMAIL_SECURE": "false",
    }
    for key, value in source.items():
        if key in {"IMAP_PASSWORD", "PROTONMAIL_PASSWORD"}:
            continue
        if key.startswith("PROTONMAIL_") or key.startswith("IMAP_") or key in {
            "READONLY",
            "ALLOW_EMPTY_FOLDER",
            "ALLOW_FILE_DOWNLOAD_DIR",
            "RESTRICT_OUTBOUND_TO_SELF",
        }:
            env[key] = value
    env["PROTONMAIL_USERNAME"] = username
    env["IMAP_HOST"] = imap_host
    env["PROTONMAIL_HOST"] = smtp_host
    env["IMAP_PORT"] = _port(env.get("IMAP_PORT", "1143"), "IMAP_PORT")
    env["PROTONMAIL_PORT"] = _port(env.get("PROTONMAIL_PORT", "1025"), "PROTONMAIL_PORT")
    env["IMAP_PASSWORD"] = bridge_password
    env["PROTONMAIL_PASSWORD"] = bridge_password
    env["PATH"] = os.environ.get("PATH", "")
    if os.name == "nt":
        for key in _KEEP_WINDOWS:
            if key in os.environ:
                env[key] = os.environ[key]
    elif "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    download = env.get("ALLOW_FILE_DOWNLOAD_DIR")
    if download:
        os.makedirs(os.path.expanduser(download), mode=0o700, exist_ok=True)
    return env
