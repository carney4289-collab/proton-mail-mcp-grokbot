#!/usr/bin/env python3
"""Print a private Serve handover plan. Does not run Tailscale or read secrets."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector.serve_handoff import ServeHandoffError, format_plan, plan_serve_handoff  # noqa: E402


def _read_arg(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    index = args.index(flag)
    if index + 1 >= len(args):
        raise ServeHandoffError("arguments rejected")
    return args[index + 1]


def _load(args: list[str], flag: str, file_flag: str) -> str:
    text = _read_arg(args, flag)
    path = _read_arg(args, file_flag)
    if text is not None and path is not None:
        raise ServeHandoffError("arguments rejected")
    if path is None:
        return text or ""
    if not os.path.isfile(path):
        raise ServeHandoffError("serve status file was not found")
    with open(path, encoding="utf-8-sig") as handle:
        return handle.read()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    allowed = {
        "--status-text",
        "--status-json",
        "--status-text-file",
        "--status-json-file",
    }
    index = 0
    while index < len(args):
        flag = args[index]
        if flag not in allowed or index + 1 >= len(args):
            sys.stderr.write("proton-mail-mcp-serve-plan: arguments rejected\n")
            return 2
        index += 2
    if ("--status-text" not in args and "--status-text-file" not in args) or (
        "--status-json" not in args and "--status-json-file" not in args
    ):
        sys.stderr.write("proton-mail-mcp-serve-plan: arguments rejected\n")
        return 2
    try:
        text = _load(args, "--status-text", "--status-text-file")
        raw_json = _load(args, "--status-json", "--status-json-file")
        sys.stdout.write(format_plan(plan_serve_handoff(text, raw_json)))
    except ServeHandoffError as exc:
        sys.stderr.write(f"proton-mail-mcp-serve-plan: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
