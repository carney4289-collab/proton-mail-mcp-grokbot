"""Strip known secrets from anything that might be logged."""
from __future__ import annotations

import re

_BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+|bearer\s+)\S+")


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    out = text
    for secret in secrets:
        if secret and len(secret) >= 8:
            out = out.replace(secret, "[REDACTED]")
    return _BEARER.sub(r"\1[REDACTED]", out)
