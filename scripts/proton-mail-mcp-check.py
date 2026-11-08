#!/usr/bin/env python3
"""Local initialize and tools/list. Does not call tools/call or print secrets."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector.backend import StdioBackend  # noqa: E402
from connector.http_gateway import McpHttpGateway  # noqa: E402
from connector.launch import node_argv  # noqa: E402
from connector.local_check import initialize_and_list  # noqa: E402
from connector.runtime_env import ConfigError, child_environment  # noqa: E402
from connector.windows_env import apply_windows_env, package_root_from_script  # noqa: E402
from connector.secrets import (  # noqa: E402
    BRIDGE_IMAP,
    HTTP_AUTH,
    SecretStoreError,
    WindowsCredentialStore,
    tokens_equal,
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        sys.stderr.write("proton-mail-mcp-check: this program takes no arguments\n")
        return 2
    try:
        store = WindowsCredentialStore()
    except SecretStoreError as exc:
        sys.stderr.write(f"proton-mail-mcp-check: {exc}\n")
        return 2
    bridge = store.get(BRIDGE_IMAP)
    auth = store.get(HTTP_AUTH)
    if not bridge:
        sys.stderr.write("proton-mail-mcp-check: bridge IMAP credential is not stored\n")
        return 2
    if not auth:
        sys.stderr.write("proton-mail-mcp-check: http-auth token is not stored\n")
        return 2
    if len(auth) < 16 or tokens_equal(auth, bridge):
        sys.stderr.write("proton-mail-mcp-check: stored http-auth token is not usable\n")
        return 2
    source = dict(os.environ)
    source.pop("IMAP_PASSWORD", None)
    source.pop("PROTONMAIL_PASSWORD", None)
    env_file = package_root_from_script(__file__) / "config" / "windows.env"
    if env_file.is_file():
        try:
            apply_windows_env(source, env_file)
        except ConfigError as exc:
            sys.stderr.write(f"proton-mail-mcp-check: {exc}\n")
            return 2
    try:
        child_env = child_environment(source, bridge)
        argv_node = node_argv(source.get("NODE_BIN", ""), source.get("MCP_JS", ""))
    except (ConfigError, ValueError) as exc:
        sys.stderr.write(f"proton-mail-mcp-check: {exc}\n")
        return 2
    policy_env = {
        key: value
        for key, value in child_env.items()
        if key not in {"IMAP_PASSWORD", "PROTONMAIL_PASSWORD"}
    }

    def factory() -> StdioBackend:
        return StdioBackend(argv_node, child_env, secrets=(bridge, auth))

    try:
        gateway = McpHttpGateway(
            auth_token=auth,
            backend_factory=factory,
            policy_env=policy_env,
            bind_host="127.0.0.1",
            bind_port=0,
            secrets=(bridge, auth),
        )
    except Exception:
        sys.stderr.write("proton-mail-mcp-check: could not listen on loopback\n")
        return 2
    gateway.start()
    try:
        summary = initialize_and_list(gateway.endpoint, auth)
    except Exception:
        sys.stderr.write("proton-mail-mcp-check: initialize or tools/list failed\n")
        return 2
    finally:
        gateway.shutdown()
    names = [name for name in summary["names"] if isinstance(name, str)]
    sys.stdout.write(
        f"protocol {summary['protocol']}\n"
        f"tools {len(names)}\n"
        + "\n".join(names)
        + "\n"
        "tools/call was not sent\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
