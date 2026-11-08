"""Plan a private Tailscale Serve handover. This module does not run Tailscale.

The live Dell process can be a foreground ``tailscale serve`` while
``tailscale serve status`` still says there is no saved config. Applying a
background config is a separate operator step. Callers must not treat a plan
as permission to stop a process.
"""
from __future__ import annotations

import json
import re

ALLOWED_HOST = "dell-sean.tail545f1e.ts.net"
PUBLIC_HTTPS = f"https://{ALLOWED_HOST}/mcp"
BACKEND = "http://127.0.0.1:8765/mcp"
MOUNT = "/mcp"
APPLY_COMMAND = (
    "tailscale",
    "serve",
    "--bg",
    "--https=443",
    "--set-path=/mcp",
    BACKEND,
)
ROLLBACK_COMMAND = (
    "tailscale",
    "serve",
    "--https=443",
    "--set-path=/mcp",
    "off",
)
READ_STATUS_COMMAND = ("tailscale", "serve", "status")
READ_STATUS_JSON_COMMAND = ("tailscale", "serve", "status", "--json")
_ALLOWED_URLS = {
    f"https://{ALLOWED_HOST}",
    f"https://{ALLOWED_HOST}/",
    PUBLIC_HTTPS,
    "http://127.0.0.1:8765",
    "http://127.0.0.1:8765/",
    BACKEND,
}
_URLS = re.compile(r"https?://[^\s\"'<>]+")
_ROOT_MOUNT = re.compile(r"\|--\s+/\s")


class ServeHandoffError(ValueError):
    pass


def _compact(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _empty_text(text: str) -> bool:
    return _compact(text) in {"", "no serve config", "no serve config."}


def _load_object(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ServeHandoffError("serve status json could not be read") from None


def _empty_json(raw: str) -> bool:
    if raw.strip() == "":
        return True
    value = _load_object(raw)
    if value in (None, {}, []):
        return True
    if not isinstance(value, dict):
        return False
    normalized = {str(key).lower(): item for key, item in value.items()}
    allowed_keys = {"tcp", "web", "services", "allowfunnel"}
    if set(normalized) - allowed_keys:
        return False
    return all(not normalized[key] for key in normalized)


def _field(value: dict, name: str) -> object:
    if name in value:
        return value[name]
    lowered = name.lower()
    for key, item in value.items():
        if str(key).lower() == lowered:
            return item
    return None


def _exact_private_serve_config(config: object) -> bool:
    """One HTTPS/443 handler: /mcp proxied to the loopback MCP path."""
    if not isinstance(config, dict):
        return False
    if _field(config, "Foreground") or _field(config, "Services") or _field(config, "AllowFunnel"):
        return False
    tcp = _field(config, "TCP") or {}
    if not isinstance(tcp, dict) or set(tcp) != {"443"}:
        return False
    port = tcp["443"]
    if not isinstance(port, dict) or port.get("HTTPS") is not True:
        return False
    if port.get("TCPForward") or port.get("HTTP") or port.get("TerminateTLS"):
        return False
    web = _field(config, "Web") or {}
    host = f"{ALLOWED_HOST}:443"
    if not isinstance(web, dict) or set(web) != {host}:
        return False
    site = web[host]
    if not isinstance(site, dict):
        return False
    handlers = _field(site, "Handlers") or {}
    if not isinstance(handlers, dict) or set(handlers) != {MOUNT}:
        return False
    handler = handlers[MOUNT]
    if not isinstance(handler, dict) or handler.get("Proxy") != BACKEND:
        return False
    return not any(handler.get(name) for name in ("Path", "Text", "Redirect"))


def _exact_foreground_only(raw: str) -> bool:
    """Saved config empty, and exactly one foreground session with the private mount.

    ``tailscale serve`` without ``--bg`` stores the handler under Foreground
    and the human status stays "No serve config". That is not a persistent
    config and it is not permission to accept any other JSON.
    """
    if raw.strip() == "":
        return False
    value = _load_object(raw)
    if not isinstance(value, dict):
        return False
    for name in ("TCP", "Web", "Services", "AllowFunnel"):
        if _field(value, name):
            return False
    foreground = _field(value, "Foreground")
    if not isinstance(foreground, dict) or len(foreground) != 1:
        return False
    return _exact_private_serve_config(next(iter(foreground.values())))


def _refuse_public(blob: str) -> None:
    lowered = blob.lower()
    if "autogroup:internet" in lowered or "0.0.0.0" in lowered:
        raise ServeHandoffError("serve status is not a private mount")
    if re.search(r"(?<!allow)funnel", lowered):
        raise ServeHandoffError("serve status is not a private mount")


def _matches_private_mount(text: str, raw_json: str) -> bool:
    blob = text + "\n" + raw_json
    if ALLOWED_HOST not in blob or BACKEND not in blob or MOUNT not in blob:
        return False
    if _ROOT_MOUNT.search(text):
        return False
    for url in _URLS.findall(blob):
        trimmed = url.rstrip(".,)")
        if trimmed not in _ALLOWED_URLS:
            return False
    return True


def plan_serve_handoff(status_text: str, status_json: str) -> dict[str, object]:
    """Return a fixed command plan or refuse. Does not execute anything."""
    text = status_text or ""
    raw_json = status_json or ""
    _refuse_public(text + "\n" + raw_json)
    text_empty = _empty_text(text)
    json_empty = _empty_json(raw_json)
    if text_empty and _exact_foreground_only(raw_json):
        return {
            "action": "foreground-to-background",
            "apply": APPLY_COMMAND,
            "rollback": ROLLBACK_COMMAND,
            "endpoint": PUBLIC_HTTPS,
        }
    if text_empty != json_empty:
        raise ServeHandoffError(
            "serve status text and json disagree; other Serve handlers were not changed"
        )
    if text_empty and json_empty:
        return {
            "action": "needs-handoff",
            "apply": APPLY_COMMAND,
            "rollback": ROLLBACK_COMMAND,
            "endpoint": PUBLIC_HTTPS,
        }
    if _matches_private_mount(text, raw_json):
        return {
            "action": "already-persistent",
            "apply": None,
            "rollback": ROLLBACK_COMMAND,
            "endpoint": PUBLIC_HTTPS,
        }
    raise ServeHandoffError(
        "serve config is not the empty state or the exact private mount; other Serve handlers were not changed"
    )


def format_plan(plan: dict[str, object]) -> str:
    action = plan.get("action")
    rollback = plan.get("rollback")
    if not isinstance(rollback, tuple):
        raise ServeHandoffError("serve plan is incomplete")
    lines = [
        f"action: {action}",
        "endpoint: " + PUBLIC_HTTPS,
        "backend: " + BACKEND,
        "read: " + " ".join(READ_STATUS_COMMAND),
        "read: " + " ".join(READ_STATUS_JSON_COMMAND),
        "This plan does not change Tailscale, does not stop a process, and does not reset other Serve handlers.",
        "rollback: " + " ".join(rollback),
        "Rollback removes only the /mcp handler on HTTPS port 443.",
    ]
    apply = plan.get("apply")
    if action == "needs-handoff":
        if not isinstance(apply, tuple):
            raise ServeHandoffError("serve plan is incomplete")
        lines.insert(5, "apply: " + " ".join(apply))
        lines.append(
            "After apply, read status again. An unauthenticated request to the endpoint must still return 401 before the old foreground Serve window is closed."
        )
    elif action == "foreground-to-background":
        if not isinstance(apply, tuple):
            raise ServeHandoffError("serve plan is incomplete")
        lines.insert(5, "apply: " + " ".join(apply))
        lines.append("The human status is empty because this mount is only in Foreground.")
        lines.append(
            "After apply, read status again. The saved config must show only this /mcp proxy and must not show Funnel."
        )
        lines.append(
            "An unauthenticated request to the endpoint must return 401 before the foreground tailscale serve window is closed."
        )
        lines.append(
            "Close only that foreground serve window. Do not stop the Tailscale service, Bridge, or the connector."
        )
        lines.append("If 401 fails, run rollback and leave the foreground window running.")
    elif action == "already-persistent":
        lines.append("Saved Serve config already matches. Do not apply it again.")
    else:
        raise ServeHandoffError("serve plan is incomplete")
    text = "\n".join(lines) + "\n"
    lowered = text.lower()
    if "funnel " in lowered or "\nfunnel" in lowered or " serve reset" in lowered:
        raise ServeHandoffError("refusing to print a public or reset serve command")
    return text
