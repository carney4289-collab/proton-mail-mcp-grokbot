#!/usr/bin/env python3
"""Download the pinned proton-mail-mcp commit, apply patches, and npm ci.

No git and no patch(1). The tarball URL is the pinned commit. Secrets are
not read.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_pinned_mcp import PATCHES, PIN  # noqa: E402
from connector.unified_diff import UnifiedDiffError, apply_unified_diff  # noqa: E402

ARCHIVE = f"https://github.com/sethbang/proton-mail-mcp/archive/{PIN}.tar.gz"
FOLDER = f"proton-mail-mcp-{PIN}"


def _stamp() -> str:
    digest = hashlib.sha256()
    digest.update(PIN.encode("utf-8"))
    digest.update((ROOT / "patches" / "harden.ts").read_bytes())
    for name in PATCHES:
        digest.update((ROOT / "patches" / name).read_bytes())
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "proton-mail-mcp-macos"})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _extract(tarball: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as archive:
        _safe_extract(archive, dest.parent)
    extracted = dest.parent / FOLDER
    if not extracted.is_dir():
        raise SystemExit("pinned source archive did not contain the expected folder")
    extracted.rename(dest)


def _safe_extract(archive: tarfile.TarFile, target: Path) -> None:
    root = target.resolve()
    for member in archive.getmembers():
        name = member.name
        if member.issym() or member.islnk() or name.startswith("/") or ".." in Path(name).parts:
            raise SystemExit("archive path is not inside the tree")
        destination = (root / name).resolve()
        if root != destination and root not in destination.parents:
            raise SystemExit("archive path is not inside the tree")
    kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
    archive.extractall(root, **kwargs)


def _apply_patches(dest: Path) -> None:
    shutil.copyfile(ROOT / "patches" / "harden.ts", dest / "src" / "harden.ts")
    for name in PATCHES:
        try:
            apply_unified_diff(dest, (ROOT / "patches" / name).read_text(encoding="utf-8"))
        except UnifiedDiffError as exc:
            raise SystemExit(f"could not apply {name}: {exc}") from None


def _npm_ci(dest: Path, node: Path, npm: Path) -> None:
    env = dict(os.environ)
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    subprocess.check_call([str(npm), "ci", "--no-audit", "--no-fund"], cwd=dest, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--npm", required=True)
    parser.add_argument("--tarball", default="")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    dest = Path(args.dest)
    node = Path(args.node)
    npm = Path(args.npm)
    if not node.is_file() or not npm.is_file():
        sys.stderr.write("proton-mail-mcp-macos: Node runtime was not found\n")
        return 2
    index = dest / "build" / "index.js"
    stamp_path = dest / ".proton-mcp-stamp"
    stamp = _stamp()
    if index.is_file() and stamp_path.is_file() and stamp_path.read_text(encoding="utf-8").strip() == stamp:
        if os.environ.get("PROTON_MCP_REBUILD") != "1":
            sys.stderr.write(f"up to date: {index}\n")
            return 0
    if args.tarball:
        tarball = Path(args.tarball)
        if not tarball.is_file():
            sys.stderr.write("proton-mail-mcp-macos: source archive was not found\n")
            return 2
        _extract(tarball, dest)
    else:
        with tempfile.TemporaryDirectory(prefix="proton-mcp-") as temporary:
            downloaded = Path(temporary) / "source.tar.gz"
            try:
                _download(ARCHIVE, downloaded)
            except OSError:
                sys.stderr.write("proton-mail-mcp-macos: could not download the pinned MCP source\n")
                return 2
            _extract(downloaded, dest)
    _apply_patches(dest)
    try:
        _npm_ci(dest, node, npm)
    except (OSError, subprocess.CalledProcessError):
        sys.stderr.write("proton-mail-mcp-macos: npm ci failed\n")
        return 2
    if not index.is_file():
        sys.stderr.write("proton-mail-mcp-macos: build/index.js was not produced\n")
        return 2
    stamp_path.write_text(stamp + "\n", encoding="utf-8")
    sys.stderr.write(f"{index}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
