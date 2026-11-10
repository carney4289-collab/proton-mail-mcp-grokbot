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
MAC_HOST = "seans-mac-mini.tail545f1e.ts.net"
KNOWN_SERVE_HOSTS = frozenset({ALLOWED_HOST, MAC_HOST})
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


def _serve_host(host: str | None) -> str:
    if host is None:
        return ALLOWED_HOST
    if host not in KNOWN_SERVE_HOSTS:
        raise ServeHandoffError("serve host is not allowed")
    return host


def _exact_private_serve_config(config: object, host: str = ALLOWED_HOST) -> bool:
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
    site_key = f"{host}:443"
    if not isinstance(web, dict) or set(web) != {site_key}:
        return False
    site = web[site_key]
    if not isinstance(site, dict):
        return False
    handlers = _field(site, "Handlers") or {}
    if not isinstance(handlers, dict) or set(handlers) != {MOUNT}:
        return False
    handler = handlers[MOUNT]
    if not isinstance(handler, dict) or handler.get("Proxy") != BACKEND:
        return False
    return not any(handler.get(name) for name in ("Path", "Text", "Redirect"))


def _exact_foreground_only(raw: str, host: str = ALLOWED_HOST) -> bool:
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
    return _exact_private_serve_config(next(iter(foreground.values())), host)


def _refuse_public(blob: str) -> None:
    lowered = blob.lower()
    if "autogroup:internet" in lowered or "0.0.0.0" in lowered:
        raise ServeHandoffError("serve status is not a private mount")
    if re.search(r"(?<!allow)funnel", lowered):
        raise ServeHandoffError("serve status is not a private mount")


def _allowed_urls(host: str) -> set[str]:
    public = f"https://{host}/mcp"
    return {
        f"https://{host}",
        f"https://{host}/",
        public,
        "http://127.0.0.1:8765",
        "http://127.0.0.1:8765/",
        BACKEND,
    }


def _matches_private_mount(text: str, raw_json: str, host: str = ALLOWED_HOST) -> bool:
    blob = text + "\n" + raw_json
    if host not in blob or BACKEND not in blob or MOUNT not in blob:
        return False
    if _ROOT_MOUNT.search(text):
        return False
    allowed = _allowed_urls(host)
    for url in _URLS.findall(blob):
        trimmed = url.rstrip(".,)")
        if trimmed not in allowed:
            return False
    return True


def saved_private_mount(status_json: str, host: str | None = None) -> bool:
    """True when saved JSON is only the private /mcp proxy for this host."""
    chosen = _serve_host(host)
    if not (status_json or "").strip():
        return False
    try:
        value = _load_object(status_json)
    except ServeHandoffError:
        return False
    return _exact_private_serve_config(value, chosen)


def plan_serve_handoff(
    status_text: str, status_json: str, host: str | None = None
) -> dict[str, object]:
    """Return a fixed command plan or refuse. Does not execute anything."""
    chosen = _serve_host(host)
    endpoint = f"https://{chosen}/mcp"
    text = status_text or ""
    raw_json = status_json or ""
    _refuse_public(text + "\n" + raw_json)
    text_empty = _empty_text(text)
    json_empty = _empty_json(raw_json)
    if text_empty and _exact_foreground_only(raw_json, chosen):
        return {
            "action": "foreground-to-background",
            "apply": APPLY_COMMAND,
            "rollback": ROLLBACK_COMMAND,
            "endpoint": endpoint,
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
            "endpoint": endpoint,
        }
    if _matches_private_mount(text, raw_json, chosen):
        return {
            "action": "already-persistent",
            "apply": None,
            "rollback": ROLLBACK_COMMAND,
            "endpoint": endpoint,
        }
    raise ServeHandoffError(
        "serve config is not the empty state or the exact private mount; other Serve handlers were not changed"
    )


def format_plan(plan: dict[str, object]) -> str:
    action = plan.get("action")
    rollback = plan.get("rollback")
    endpoint = plan.get("endpoint")
    known = {f"https://{name}/mcp" for name in KNOWN_SERVE_HOSTS}
    if not isinstance(endpoint, str) or endpoint not in known:
        raise ServeHandoffError("serve plan is incomplete")
    if not isinstance(rollback, tuple):
        raise ServeHandoffError("serve plan is incomplete")
    lines = [
        f"action: {action}",
        "endpoint: " + endpoint,
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
