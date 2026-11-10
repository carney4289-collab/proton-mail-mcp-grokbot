#!/usr/bin/env python3
"""Save the private /mcp Serve handler, or leave an exact one in place.

Runs only `tailscale serve --bg --https=443 --set-path=/mcp http://127.0.0.1:8765/mcp`
after the status plan allows it. Does not enable Funnel or reset other handlers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.macos_serve import (  # noqa: E402
    WORKAROUND,
    argv_for_apply,
    confirm_applied,
    gui_failure,
    plan_mac_apply,
)
from connector.macos_tailscale import require_tailscale, run_tailscale, save_status, status_pair  # noqa: E402
from connector.serve_handoff import ServeHandoffError, format_plan  # noqa: E402

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
        plan = plan_mac_apply(text, raw)
        sys.stdout.write(format_plan(plan))
        if plan["action"] == "already-persistent":
            sys.stdout.write("Saved Serve config already matches. No change was made.\n")
            return 0
        argv = argv_for_apply(binary, plan)
    except ServeHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    sys.stdout.write("Applying the /mcp handler.\n")
    code, _out, err = run_tailscale(argv)
    if code != 0:
        if gui_failure(err):
            sys.stderr.write(WORKAROUND)
        else:
            sys.stderr.write("proton-mail-mcp-macos: tailscale serve apply failed\n")
        return 2
    again = status_pair(binary)
    if again is None:
        return 2
    _text, raw_after = again
    if not confirm_applied(raw_after):
        sys.stderr.write(
            "proton-mail-mcp-macos: saved Serve config is not the exact private /mcp mount.\n"
        )
        sys.stderr.write(
            "Other handlers were not changed. Run scripts/macos/rollback-serve.sh if this /mcp handler should be removed.\n"
        )
        return 2
    sys.stdout.write("Saved Serve config matches.\n")
    sys.stdout.write("Next, run scripts/macos/check-endpoint.sh. It must say unauth 401.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
