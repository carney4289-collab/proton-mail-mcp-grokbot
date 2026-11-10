"""Apply or roll back only the private /mcp Tailscale Serve handler.

The command lists are the same fixed tuples the Windows plan prints. This
module runs them only after the status JSON matches that plan. It does not
enable Funnel, reset Serve, or stop a process.
"""
from __future__ import annotations

from connector.serve_handoff import (
    APPLY_COMMAND,
    BACKEND,
    MAC_HOST,
    MOUNT,
    ROLLBACK_COMMAND,
    ServeHandoffError,
    _field,
    _load_object,
    _refuse_public,
    plan_serve_handoff,
    saved_private_mount,
)

APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
STANDALONE_CANDIDATES = (
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
)
GUI_MARKERS = (
    "The Tailscale GUI failed to start",
    "Tailscale.CLIError error 3",
)
WORKAROUND = (
    "The Tailscale app CLI could not start from this shell.\n"
    "Open Terminal.app on the Mac itself, not an SSH session, and run the same command there.\n"
    "If it still fails, click the Tailscale icon in the menu bar and choose Install CLI.\n"
    "That installs /usr/local/bin/tailscale. macOS may ask for your Mac login password.\n"
    "That password is not the Proton account password and not the Bridge password.\n"
    "Then run this command again.\n"
)


def resolve_tailscale(override: str | None, exists) -> str:
    """Prefer the standalone CLI. The app binary is last because SSH cannot start the GUI."""
    if override is not None:
        if override == "" or any(ch in override for ch in "\r\n") or override.strip() != override:
            raise ServeHandoffError("TAILSCALE_BIN was not found")
        if not exists(override):
            raise ServeHandoffError("TAILSCALE_BIN was not found")
        return override
    for path in STANDALONE_CANDIDATES:
        if exists(path):
            return path
    if exists(APP_CLI):
        return APP_CLI
    raise ServeHandoffError("tailscale was not found")


def gui_failure(stderr: str) -> bool:
    text = stderr or ""
    return any(marker in text for marker in GUI_MARKERS)


def argv_for(binary: str, command: tuple[str, ...]) -> list[str]:
    if command not in (APPLY_COMMAND, ROLLBACK_COMMAND):
        raise ServeHandoffError("refusing to run that serve command")
    if not binary or any(ch in binary for ch in "\r\n") or binary.strip() != binary:
        raise ServeHandoffError("tailscale binary is not allowed")
    return [binary, *command[1:]]


def argv_for_apply(binary: str, plan: dict[str, object]) -> list[str]:
    if plan.get("action") not in {"needs-handoff", "foreground-to-background"}:
        raise ServeHandoffError("refusing to apply")
    if plan.get("apply") != APPLY_COMMAND:
        raise ServeHandoffError("refusing to apply")
    if plan.get("endpoint") != f"https://{MAC_HOST}/mcp":
        raise ServeHandoffError("refusing to apply")
    return argv_for(binary, APPLY_COMMAND)


def plan_mac_apply(status_text: str, status_json: str) -> dict[str, object]:
    return plan_serve_handoff(status_text, status_json, MAC_HOST)


def confirm_applied(status_json: str) -> bool:
    return saved_private_mount(status_json, MAC_HOST)


def plan_rollback(status_json: str) -> dict[str, object]:
    """Remove /mcp only when every /mcp proxy is this connector and Funnel is off."""
    raw = status_json or ""
    _refuse_public(raw)
    if raw.strip() in {"", "{}", "[]", "null"}:
        return {"action": "already-off", "rollback": None}
    value = _load_object(raw)
    if not isinstance(value, dict):
        raise ServeHandoffError("serve status json could not be read")
    if _funnel_present(value):
        raise ServeHandoffError("serve status is not a private mount")
    proxies = _mcp_proxies(value, MAC_HOST)
    if not proxies:
        return {"action": "already-off", "rollback": None}
    if any(proxy != BACKEND for proxy in proxies):
        raise ServeHandoffError("the /mcp handler is not this connector; it was not changed")
    return {"action": "remove-mcp", "rollback": ROLLBACK_COMMAND}


def _funnel_present(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() == "allowfunnel" and item:
                return True
            if _funnel_present(item):
                return True
    elif isinstance(value, list):
        return any(_funnel_present(item) for item in value)
    return False


def _mcp_proxies(value: dict, host: str) -> list[str]:
    found: list[str] = []
    _collect(value, host, found)
    foreground = _field(value, "Foreground")
    if isinstance(foreground, dict):
        for session in foreground.values():
            if isinstance(session, dict):
                _collect(session, host, found)
    return found


def _collect(config: dict, host: str, found: list[str]) -> None:
    web = _field(config, "Web")
    if not isinstance(web, dict):
        return
    site = web.get(f"{host}:443")
    if not isinstance(site, dict):
        return
    handlers = _field(site, "Handlers")
    if not isinstance(handlers, dict) or MOUNT not in handlers:
        return
    handler = handlers[MOUNT]
    if isinstance(handler, dict) and isinstance(handler.get("Proxy"), str):
        found.append(handler["Proxy"])
