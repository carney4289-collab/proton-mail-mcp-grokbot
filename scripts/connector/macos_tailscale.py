"""Run a fixed tailscale argument list. No shell."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from connector.macos_serve import WORKAROUND, gui_failure, resolve_tailscale
from connector.serve_handoff import ServeHandoffError


def tailscale_binary() -> str:
    override = os.environ["TAILSCALE_BIN"] if "TAILSCALE_BIN" in os.environ else None

    def exists(path: str) -> bool:
        return os.path.isfile(path) and os.access(path, os.X_OK)

    return resolve_tailscale(override, exists)


def run_tailscale(argv: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def require_tailscale() -> str:
    try:
        return tailscale_binary()
    except ServeHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        sys.stderr.write(WORKAROUND)
        return ""


def status_pair(binary: str) -> tuple[str, str] | None:
    code, text, err = run_tailscale([binary, "serve", "status"])
    if code != 0:
        if gui_failure(err):
            sys.stderr.write(WORKAROUND)
        else:
            sys.stderr.write("proton-mail-mcp-macos: tailscale serve status failed\n")
        return None
    code, raw, err = run_tailscale([binary, "serve", "status", "--json"])
    if code != 0:
        if gui_failure(err):
            sys.stderr.write(WORKAROUND)
        else:
            sys.stderr.write("proton-mail-mcp-macos: tailscale serve status failed\n")
        return None
    return text, raw


def save_status(package_root: Path, text: str, raw: str) -> None:
    state = package_root / "state"
    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (state / f"serve-status-{stamp}.txt").write_text(text, encoding="utf-8")
    (state / f"serve-status-{stamp}.json").write_text(raw, encoding="utf-8")
    sys.stdout.write("saved serve status under state/\n")
