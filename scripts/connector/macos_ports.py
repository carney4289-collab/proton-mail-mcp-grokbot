"""TCP checks for Bridge and the loopback connector. No IMAP or SMTP commands."""
from __future__ import annotations

import socket
import time

ALLOWED_PORTS = frozenset({1143, 1025, 8765})


def tcp_open(port: int, timeout: float = 0.4) -> bool:
    if port not in ALLOWED_PORTS:
        raise ValueError("refusing to probe that port")
    client = socket.socket()
    client.settimeout(timeout)
    try:
        client.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        client.close()


def wait_until(probe, seconds: int, sleep, clock) -> bool:
    if seconds < 0 or seconds > 120:
        raise ValueError("bridge wait must be from 0 through 120 seconds")
    deadline = clock() + seconds
    while True:
        if probe():
            return True
        if clock() >= deadline:
            return False
        sleep(1)


def bridge_ready(seconds: int, sleep=time.sleep, clock=time.monotonic, opener=tcp_open) -> bool:
    return wait_until(lambda: opener(1143) and opener(1025), seconds, sleep, clock)


def parse_wait_seconds(raw: str | None) -> int:
    if raw is None or raw == "":
        return 90
    if not raw.isdigit():
        raise ValueError("bridge wait must be from 0 through 120 seconds")
    value = int(raw)
    if str(value) != raw or value > 120:
        raise ValueError("bridge wait must be from 0 through 120 seconds")
    return value
