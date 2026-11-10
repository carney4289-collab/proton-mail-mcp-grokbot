#!/usr/bin/env python3
"""Remove only the /mcp Serve handler when it points at this connector."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.macos_serve import WORKAROUND, argv_for, gui_failure, plan_rollback  # noqa: E402
from connector.macos_tailscale import require_tailscale, run_tailscale, save_status, status_pair  # noqa: E402
from connector.serve_handoff import ServeHandoffError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    if sys.argv[1:]:
        sys.stderr.write("proton-mail-mcp-macos: this program takes no arguments\n")
        return 2
    binary = require_tailscale()
    if not binary:
        return 2
    pair = status_pair(binary)
    if pair is None:
        return 2
    text, raw = pair
    save_status(ROOT, text, raw)
    try:
        plan = plan_rollback(raw)
    except ServeHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    if plan["action"] == "already-off":
        sys.stdout.write("The /mcp handler is already absent. Other Serve handlers were not changed.\n")
        return 0
    rollback = plan["rollback"]
    if not isinstance(rollback, tuple):
        sys.stderr.write("proton-mail-mcp-macos: serve plan is incomplete\n")
        return 2
    try:
        argv = argv_for(binary, rollback)
    except ServeHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    sys.stdout.write("Removing only the /mcp handler.\n")
    code, _out, err = run_tailscale(argv)
    if code != 0:
        if gui_failure(err):
            sys.stderr.write(WORKAROUND)
        else:
            sys.stderr.write("proton-mail-mcp-macos: tailscale serve rollback failed\n")
        return 2
    again = status_pair(binary)
    if again is None:
        return 2
    try:
        after = plan_rollback(again[1])
    except ServeHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    if after["action"] != "already-off":
        sys.stderr.write("proton-mail-mcp-macos: the /mcp handler is still present. Other handlers were not changed.\n")
        return 2
    sys.stdout.write("Removed only the /mcp handler. Other Serve handlers were not changed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
