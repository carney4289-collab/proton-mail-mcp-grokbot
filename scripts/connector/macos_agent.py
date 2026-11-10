"""Per-user LaunchAgent plist. No secrets are written into it."""
from __future__ import annotations

import plistlib
from pathlib import Path

from connector.macos_config import LABEL, log_dir

THROTTLE_SECONDS = 10


def render_plist(*, package_root: str, python_exe: str, home: str) -> str:
    root = _absolute(package_root, "package")
    python = _absolute(python_exe, "python")
    home_path = _absolute(home, "home")
    script = str(Path(root) / "scripts" / "macos" / "run-at-login.sh")
    logs = log_dir(home_path)
    payload = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/bash", script],
        "WorkingDirectory": root,
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": THROTTLE_SECONDS,
        "ProcessType": "Background",
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": str(logs / "connector.out.log"),
        "StandardErrorPath": str(logs / "connector.err.log"),
        "EnvironmentVariables": {
            "HOME": home_path,
            "PROTON_MCP_SECRET_STORE": "keychain",
            "PYTHON_EXE": python,
        },
    }
    text = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")
    lowered = text.lower()
    for banned in ("password", "bearer", "funnel", "sudo"):
        if banned in lowered:
            raise ValueError("plist contains a forbidden word")
    if lowered.count("secret") != lowered.count("proton_mcp_secret_store"):
        raise ValueError("plist contains a forbidden word")
    return text


def _absolute(value: str, name: str) -> str:
    if not value or not value.startswith("/") or value.strip() != value:
        raise ValueError(f"{name} path must be absolute")
    if any(ch in value for ch in "\r\n"):
        raise ValueError(f"{name} path contains a newline")
    return value
