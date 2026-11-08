#!/usr/bin/env python3
"""Loopback HTTP MCP connector. Secrets come from the OS store, never argv."""
from __future__ import annotations

import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector.backend import StdioBackend  # noqa: E402
from connector.http_gateway import McpHttpGateway, validate_extra_hosts  # noqa: E402
from connector.launch import node_argv  # noqa: E402
from connector.runtime_env import ConfigError, child_environment  # noqa: E402
from connector.secrets import (  # noqa: E402
    BRIDGE_IMAP,
    HTTP_AUTH,
    PassSecretStore,
    SecretStoreError,
    WindowsCredentialStore,
    tokens_equal,
)


def _store():
    kind = os.environ.get("PROTON_MCP_SECRET_STORE", "").strip().lower()
    if not kind:
        kind = "windows" if os.name == "nt" else "pass"
    if kind == "windows":
        return WindowsCredentialStore()
    if kind == "pass":
        return PassSecretStore()
    sys.stderr.write("proton-mail-mcp-http: secret store must be windows or pass\n")
    return None


def _fail(message: str) -> int:
    sys.stderr.write(f"proton-mail-mcp-http: {message}\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        return _fail("this program takes no arguments; secrets are not accepted on the command line")
    try:
        store = _store()
    except SecretStoreError as exc:
        return _fail(str(exc))
    if store is None:
        return 2
    bridge = store.get(BRIDGE_IMAP)
    auth = store.get(HTTP_AUTH)
    if not bridge:
        return _fail("bridge IMAP credential is not in the secret store")
    if not auth:
        return _fail("endpoint auth secret is not in the secret store")
    if len(auth) < 16:
        return _fail("endpoint auth secret is too short")
    if tokens_equal(auth, bridge):
        return _fail("endpoint auth secret and bridge credential must be different")
    source = dict(os.environ)
    source.pop("IMAP_PASSWORD", None)
    source.pop("PROTONMAIL_PASSWORD", None)
    try:
        child_env = child_environment(source, bridge)
        extra_hosts = validate_extra_hosts(os.environ.get("PROTON_MCP_EXTRA_HOSTS"))
        bind_host = os.environ.get("BIND_HOST", "127.0.0.1")
        bind_port = int(os.environ.get("BIND_PORT", "8765"))
        argv_node = node_argv(os.environ.get("NODE_BIN", ""), os.environ.get("MCP_JS", ""))
    except (ConfigError, ValueError, SecretStoreError) as exc:
        return _fail(str(exc))
    policy_env = {
        key: value
        for key, value in child_env.items()
        if key not in {"IMAP_PASSWORD", "PROTONMAIL_PASSWORD"}
    }
    secrets = (bridge, auth)

    def factory() -> StdioBackend:
        return StdioBackend(argv_node, child_env, secrets=secrets, log=lambda line: sys.stderr.write(line + "\n"))

    try:
        gateway = McpHttpGateway(
            auth_token=auth,
            backend_factory=factory,
            policy_env=policy_env,
            bind_host=bind_host,
            bind_port=bind_port,
            extra_hosts=extra_hosts,
            secrets=secrets,
            log=lambda line: sys.stderr.write(line + "\n"),
        )
    except Exception as exc:
        return _fail(str(exc) if str(exc) else type(exc).__name__)

    def _stop(_signum: int, _frame: object) -> None:
        gateway.shutdown()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    sys.stderr.write(
        f"proton-mail-mcp-http: listening on {gateway.endpoint} (loopback only)\n"
    )
    gateway.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
