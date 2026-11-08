#!/usr/bin/env python3
"""Clone pinned sethbang/proton-mail-mcp, apply this repo's patches, and build.

The checkout lands in build/proton-mail-mcp, which is gitignored. No secrets.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

PIN = "db671d9592f85b3b4f4ae6c32a27021258332abc"
REPO = "https://github.com/sethbang/proton-mail-mcp.git"
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "build" / "proton-mail-mcp"
PATCHES = [
    "loopback-tls.patch",
    "harden-email-service.patch",
    "harden-imap-service.patch",
    "harden-index.patch",
    "harden-validation.patch",
]


def _run(argv: list[str], **kwargs) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.check_call(argv, **kwargs)


def _patch_bin() -> str | None:
    found = shutil.which("patch")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\usr\bin\patch.exe",
        r"C:\Program Files (x86)\Git\usr\bin\patch.exe",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def _apply(patch_path: Path) -> None:
    print(f"+ patch -p1 {patch_path.name}", flush=True)
    patch_bin = _patch_bin()
    if patch_bin:
        subprocess.run(
            [patch_bin, "-p1", "--forward", "--batch", "-i", str(patch_path)],
            cwd=DEST,
            check=True,
        )
        return
    # Git for Windows may not put `patch` on PATH. These files have a comment
    # header and sometimes no trailing newline, which `git apply` rejects.
    lines = patch_path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("--- ") or line.startswith("diff "))
    body = "".join(lines[start:])
    if not body.endswith("\n"):
        body += "\n"
    subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        input=body,
        text=True,
        cwd=DEST,
        check=True,
    )


def main() -> int:
    harden = (ROOT / "patches" / "harden.ts").read_bytes()
    stamp = hashlib.sha256(harden).hexdigest() + " " + PIN
    index = DEST / "build" / "index.js"
    stamp_path = DEST / ".proton-mcp-stamp"
    if index.is_file() and stamp_path.is_file() and stamp_path.read_text(encoding="utf-8").strip() == stamp:
        if os.environ.get("PROTON_MCP_REBUILD") != "1":
            print(f"up to date: {index}")
            return 0
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--filter=blob:none", "--no-checkout", REPO, str(DEST)])
    _run(["git", "-C", str(DEST), "fetch", "--depth", "1", "origin", PIN])
    _run(["git", "-C", str(DEST), "checkout", "--detach", "FETCH_HEAD"])
    head = subprocess.check_output(["git", "-C", str(DEST), "rev-parse", "HEAD"], text=True).strip()
    if head != PIN:
        sys.stderr.write(f"checked out {head}, expected {PIN}\n")
        return 1
    shutil.copyfile(ROOT / "patches" / "harden.ts", DEST / "src" / "harden.ts")
    for name in PATCHES:
        _apply(ROOT / "patches" / name)
    _run(["npm", "ci", "--no-audit", "--no-fund"], cwd=DEST)
    if not index.is_file():
        sys.stderr.write("build/index.js was not produced\n")
        return 1
    stamp_path.write_text(stamp + "\n", encoding="utf-8")
    print(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
