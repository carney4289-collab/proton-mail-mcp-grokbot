"""Non-secret macOS config. The bearer and Bridge password are not in the file."""
from __future__ import annotations

import os
from pathlib import Path

from connector.runtime_env import ConfigError
from connector.windows_env import apply_windows_env

MAC_HOST = "seans-mac-mini.tail545f1e.ts.net"
EXTRA_HOSTS = f"{MAC_HOST},{MAC_HOST}:443"
LABEL = "local.proton-mail-mcp.loopback"
SUPPORT_NAME = "ProtonMailMCP"
USERNAME_PLACEHOLDER = "REPLACE_WITH_PROTON_ACCOUNT_USERNAME"
_PATH_KEYS = ("NODE_BIN", "MCP_JS", "ALLOW_FILE_DOWNLOAD_DIR")


def support_dir(home: str) -> Path:
    return Path(home) / "Library" / "Application Support" / SUPPORT_NAME


def log_dir(home: str) -> Path:
    return Path(home) / "Library" / "Logs" / SUPPORT_NAME


def venv_python(home: str) -> Path:
    return support_dir(home) / "runtimes" / "venv" / "bin" / "python3"


def launch_agent_path(home: str) -> Path:
    return Path(home) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def expand_config_path(value: str, home: str) -> str:
    if value.startswith("$HOME/") or value.startswith("$HOME\\"):
        value = home + value[5:]
    return os.path.expanduser(value)


def load_macos_config(path: Path, environ: dict[str, str], home: str) -> None:
    """Fill empty keys from macos.env. A non-empty process value wins."""
    apply_windows_env(environ, path)
    for key in _PATH_KEYS:
        current = environ.get(key)
        if current:
            environ[key] = expand_config_path(current, home)


def assert_launch_config(environ: dict[str, str]) -> None:
    """Refuse a listener that is not loopback, or a Host list that is not this Mac."""
    if environ.get("BIND_HOST") != "127.0.0.1":
        raise ConfigError("BIND_HOST must be 127.0.0.1")
    if environ.get("BIND_PORT") != "8765":
        raise ConfigError("BIND_PORT must be 8765")
    if environ.get("PROTON_MCP_EXTRA_HOSTS") != EXTRA_HOSTS:
        raise ConfigError("PROTON_MCP_EXTRA_HOSTS must be the Mac mini Tailscale name")
    for key in ("IMAP_HOST", "PROTONMAIL_HOST"):
        if environ.get(key, "127.0.0.1") not in {"127.0.0.1", "localhost", "::1"}:
            raise ConfigError(f"{key} must stay on loopback")
    username = environ.get("PROTONMAIL_USERNAME", "")
    if (
        not username
        or username == USERNAME_PLACEHOLDER
        or any(ch.isspace() or ord(ch) < 32 for ch in username)
    ):
        raise ConfigError("PROTONMAIL_USERNAME is not set")
    kind = environ.get("PROTON_MCP_SECRET_STORE", "").strip().lower()
    if kind and kind != "keychain":
        raise ConfigError("Mac connector secret store must be keychain")


def valid_username(value: str) -> bool:
    if not value or len(value) > 200:
        return False
    if any(ch.isspace() or ord(ch) < 32 or ch in "=#\"'" for ch in value):
        return False
    return "@" in value and not value.startswith("@") and not value.endswith("@")
