"""Node executable resolution. No shell, no secrets on argv."""
from __future__ import annotations

import os


def _basename(path: str) -> str:
    """Last path segment, accepting both separators on either host OS."""
    trimmed = path.rstrip("\\/")
    cut = max(trimmed.rfind("\\"), trimmed.rfind("/"))
    return trimmed if cut < 0 else trimmed[cut + 1 :]


def _join(directory: str, name: str, platform_name: str) -> str:
    """Join with the target platform's separator, not the machine running the test."""
    sep = "\\" if platform_name == "nt" else "/"
    return directory.rstrip("\\/") + sep + name


def resolve_node_executable(node_bin: str, platform_name: str | None = None) -> str:
    """Return the node binary path.

    ``node_bin`` may be the directory that contains Node (``NODE_BIN`` in the
    Linux wrapper) or the executable itself. On Windows the file is
    ``node.exe``. A directory is never joined twice. When ``platform_name`` is
    set, the separator follows that platform so a Windows test can describe a
    POSIX layout and the reverse.
    """
    if not node_bin or node_bin.strip() != node_bin or any(c in node_bin for c in "\r\n"):
        raise ValueError("NODE_BIN is empty or contains a newline")
    expanded = os.path.expanduser(node_bin)
    plat = platform_name if platform_name is not None else os.name
    exe_name = "node.exe" if plat == "nt" else "node"
    base = _basename(expanded)
    if base == "node" or base.lower() == "node.exe":
        return expanded
    if platform_name is None and os.path.isdir(expanded):
        return os.path.join(expanded, exe_name)
    return _join(expanded, exe_name, plat)


def node_argv(node_bin: str, mcp_js: str, platform_name: str | None = None) -> list[str]:
    """Argv for subprocess with shell=False. Neither value is a secret."""
    if not mcp_js or any(c in mcp_js for c in "\r\n"):
        raise ValueError("MCP_JS is empty or contains a newline")
    return [resolve_node_executable(node_bin, platform_name), mcp_js]
