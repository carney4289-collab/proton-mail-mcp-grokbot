"""Load config/windows.env from the package root. No secrets, no cwd guess."""
from __future__ import annotations

import re
from pathlib import Path

from connector.runtime_env import ConfigError

_SECRET_NAME = re.compile(r"PASSWORD|SECRET|TOKEN|AUTH")


def package_root_from_script(script_path: str) -> Path:
    """scripts/<file>.py -> the folder that contains scripts and config."""
    return Path(script_path).resolve().parent.parent


def apply_windows_env(environ: dict[str, str], path: Path) -> None:
    """Fill empty keys from windows.env. A non-empty process value wins.

    The path is the file itself. Callers locate it from the package root,
    not from the current directory. Values keep internal spaces.
    """
    text = path.read_text(encoding="utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError("invalid env line")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise ConfigError("invalid env line")
        if _SECRET_NAME.search(name):
            raise ConfigError(f"refusing to load a secret from the env file: {name}")
        if not environ.get(name):
            environ[name] = value
