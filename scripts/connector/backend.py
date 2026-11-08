"""One stdio JSON-RPC child. shell is never enabled."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections.abc import Callable

from connector.redact import redact

MAX_LINE = 10 * 1024 * 1024


class BackendError(RuntimeError):
    pass


class StdioBackend:
    def __init__(
        self,
        argv: list[str],
        env: dict[str, str],
        *,
        secrets: tuple[str, ...] = (),
        log: Callable[[str], None] | None = None,
        timeout: float = 120.0,
    ) -> None:
        if not argv or any(not isinstance(part, str) for part in argv):
            raise BackendError("argv must be a list of strings")
        self._secrets = secrets
        self._log = log or (lambda _message: None)
        self._timeout = timeout
        self._messages: queue.Queue[dict | None] = queue.Queue()
        self._write_lock = threading.Lock()
        self.closed = False
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                shell=False,
            )
        except OSError as exc:
            raise BackendError(type(exc).__name__) from exc
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    @property
    def argv(self) -> list[str]:
        return list(self._proc.args) if isinstance(self._proc.args, list) else []

    def _drain_stderr(self) -> None:
        stderr = self._proc.stderr
        if stderr is None:
            return
        while True:
            line = stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text.startswith(("[Error]", "[Warning]", "[Info]")):
                self._log(redact(text[:300], self._secrets))

    def _read_stdout(self) -> None:
        stdout = self._proc.stdout
        if stdout is None:
            self._messages.put(None)
            return
        buf = bytearray()
        fd = stdout.fileno()
        while True:
            # os.read returns whatever is already on the pipe. BufferedReader.read
            # would block until the requested size or EOF, which a JSON line never fills.
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                self._messages.put(None)
                return
            if not chunk:
                self._messages.put(None)
                return
            buf.extend(chunk)
            if len(buf) > MAX_LINE:
                self._log("backend line exceeded the size cap")
                self._messages.put(None)
                return
            while True:
                newline = buf.find(b"\n")
                if newline < 0:
                    break
                raw = bytes(buf[:newline])
                del buf[: newline + 1]
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                if not raw.strip():
                    continue
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, dict):
                    self._messages.put(parsed)

    def exchange(self, message: dict) -> dict | None:
        if self.closed or self._proc.poll() is not None:
            raise BackendError("backend is not running")
        payload = (json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        if len(payload) > MAX_LINE:
            raise BackendError("request is too large")
        stdin = self._proc.stdin
        if stdin is None:
            raise BackendError("backend pipes are closed")
        with self._write_lock:
            try:
                stdin.write(payload)
                stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise BackendError(type(exc).__name__) from exc
            if "id" not in message:
                return None
            wanted = message["id"]
            while True:
                try:
                    incoming = self._messages.get(timeout=self._timeout)
                except queue.Empty as exc:
                    raise BackendError("backend timed out") from exc
                if incoming is None:
                    raise BackendError("backend exited")
                if incoming.get("id") == wanted:
                    return incoming

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=3)
