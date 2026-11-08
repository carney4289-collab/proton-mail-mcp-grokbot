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


def _empty_json(raw: str) -> bool:
    if raw.strip() == "":
        return True
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ServeHandoffError("serve status json could not be read") from None
    if value in (None, {}, []):
        return True
    if not isinstance(value, dict):
        return False
    normalized = {str(key).lower(): item for key, item in value.items()}
    allowed_keys = {"tcp", "web", "services", "allowfunnel"}
    if set(normalized) - allowed_keys:
        return False
    return all(not normalized[key] for key in normalized)


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
    elif action == "already-persistent":
        lines.append("Saved Serve config already matches. Do not apply it again.")
    else:
        raise ServeHandoffError("serve plan is incomplete")
    text = "\n".join(lines) + "\n"
    lowered = text.lower()
    if "funnel " in lowered or "\nfunnel" in lowered or " serve reset" in lowered:
        raise ServeHandoffError("refusing to print a public or reset serve command")
    return text
