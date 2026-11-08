"""Node executable resolution. No shell, no secrets on argv."""
from __future__ import annotations

import os


def resolve_node_executable(node_bin: str, platform_name: str | None = None) -> str:
    """Return the node binary path.

    ``node_bin`` may be the directory that contains Node (``NODE_BIN`` in the
    Linux wrapper) or the executable itself. On Windows the file is
    ``node.exe``. A directory is never joined twice.
    """
    if not node_bin or node_bin.strip() != node_bin or any(c in node_bin for c in "\r\n"):
        raise ValueError("NODE_BIN is empty or contains a newline")
    expanded = os.path.expanduser(node_bin)
    plat = platform_name if platform_name is not None else os.name
    exe_name = "node.exe" if plat == "nt" else "node"
    base = os.path.basename(expanded.rstrip("\\/"))
    if base == "node" or base.lower() == "node.exe":
        return expanded
    if platform_name is None and os.path.isdir(expanded):
        return os.path.join(expanded, exe_name)
    # Missing directory, or a platform we are only quoting for tests.
    if platform_name is not None and not expanded.lower().endswith(exe_name):
        return os.path.join(expanded, exe_name) if not os.path.basename(expanded) == exe_name else expanded
    if os.path.isdir(expanded) or not os.path.splitext(base)[1]:
        return os.path.join(expanded, exe_name)
    return expanded


def node_argv(node_bin: str, mcp_js: str, platform_name: str | None = None) -> list[str]:
    """Argv for subprocess with shell=False. Neither value is a secret."""
    if not mcp_js or any(c in mcp_js for c in "\r\n"):
        raise ValueError("MCP_JS is empty or contains a newline")
    return [resolve_node_executable(node_bin, platform_name), mcp_js]
