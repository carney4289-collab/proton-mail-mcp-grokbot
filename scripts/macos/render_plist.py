#!/usr/bin/env python3
"""Print the LaunchAgent plist. Paths are arguments. Secrets are not."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from connector.macos_agent import render_plist  # noqa: E402


def _value(argv: list[str], flag: str) -> str:
    if flag not in argv:
        raise ValueError("arguments rejected")
    index = argv.index(flag)
    if index + 1 >= len(argv):
        raise ValueError("arguments rejected")
    return argv[index + 1]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        text = render_plist(
            package_root=_value(args, "--package-root"),
            python_exe=_value(args, "--python"),
            home=_value(args, "--home"),
        )
    except ValueError as exc:
        sys.stderr.write(f"proton-mail-mcp-macos: {exc}\n")
        return 2
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
