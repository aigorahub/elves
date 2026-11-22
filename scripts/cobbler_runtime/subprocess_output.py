"""Bound output while reading it, rather than after a subprocess exits.

These helpers bound host-side capture, not all resources a child can use.
Async callers retain ownership of their existing containment boundary. The
synchronous helper owns a process group on POSIX and closed stdin; native-worker
line iteration leaves process cleanup to its supervisor.
"""
from __future__ import annotations

import asyncio
import math
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

CHUNK_BYTES = 64 * 1024
DIAGNOSTIC_TAIL_BYTES = 64 * 1024
DEFAULT_OUTPUT_BYTES = 16 * 1024 * 1024


class OutputLimitExceeded(subprocess.SubprocessError):
    """Capture failed; bounded output is diagnostic only, never a valid result."""

    def __init__(self, stream: str, limit: int, *, stdout: bytes = b"", stderr: bytes = b""):
        self.stream = stream
        self.limit = limit
        self.stdout = self.output = stdout
        self.stderr = stderr
        super().__init__(f"subprocess_output_limit: {stream} exceeded {limit} bytes")


def _positive_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("output byte limits must be positive integers")
    return value


class ByteCapture:
    """Keep complete small output, then only a rolling diagnostic tail."""

    def __init__(self, limit: int):
        self.limit = _positive_limit(limit)
        self.total = 0
        self.exceeded = False
        self._data = bytearray()

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        self.exceeded = self.exceeded or self.total > self.limit
        if self.exceeded:
            tail = min(self.limit, DIAGNOSTIC_TAIL_BYTES)
            if len(chunk) >= tail:
                self._data = bytearray(chunk[-tail:])
            else:
                del self._data[:max(0, len(self._data) + len(chunk) - tail)]
                self._data.extend(chunk)
        else:
            self._data.extend(chunk)

    def value(self) -> bytes:
        return bytes(self._data)


class AsyncCapture:
    """Concurrent pipe drains with an overflow signal for the owning supervisor."""

    def __init__(self, stdout_limit: int, stderr_limit: int):
        self.stdout = ByteCapture(stdout_limit)
        self.stderr = ByteCapture(stderr_limit)
        self.overflow = asyncio.Event()

    def error(self) -> OutputLimitExceeded | None:
        for name in ("stdout", "stderr"):
            capture = getattr(self, name)
            if capture.exceeded:
                return OutputLimitExceeded(name, capture.limit,
                                           stdout=self.stdout.value(), stderr=self.stderr.value())
        return None

    async def communicate(self, proc: Any, input: bytes | None = None) -> tuple[bytes, bytes]:
        async def drain(stream: Any, capture: ByteCapture) -> None:
            if stream is None:
                return
            while True:
                chunk = await stream.read(CHUNK_BYTES)
                if not chunk:
                    return
                capture.feed(chunk)
                if capture.exceeded:
                    self.overflow.set()
                # Continue draining during the owner's containment cleanup, but
                # retain only the bounded tail. Never restart an unbounded read.

        async def feed_stdin() -> None:
            if proc.stdin is None:
                return
            try:
                if input:
                    proc.stdin.write(input)
                    await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.stdin.close()

        tasks = [asyncio.create_task(drain(proc.stdout, self.stdout)),
                 asyncio.create_task(drain(proc.stderr, self.stderr)),
                 asyncio.create_task(feed_stdin())]
        try:
            await asyncio.gather(*tasks)
            await proc.wait()
            return self.stdout.value(), self.stderr.value()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_for_exit(self, exit_awaitable: Any) -> Any:
        """Wake on overflow even when a producer never exits on its own."""
        exited = asyncio.ensure_future(exit_awaitable)
        overflowed = asyncio.create_task(self.overflow.wait())
        try:
            await asyncio.wait((exited, overflowed), return_when=asyncio.FIRST_COMPLETED)
            error = self.error()
            if error is not None:
                raise error
            return await exited
        finally:
            for task in (exited, overflowed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(exited, overflowed, return_exceptions=True)


def _pipe_chunks(proc: Any, *, deadline: float | None = None,
                 timeout: float | None = None) -> Iterator[tuple[str, bytes]]:
    """Read fixed-size binary chunks fairly from both pipes on supported POSIX hosts."""
    with selectors.DefaultSelector() as selector:
        for name in ("stdout", "stderr"):
            stream = getattr(proc, name)
            if stream is not None:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            for key, _ in selector.select(0.2 if remaining is None else min(0.2, remaining)):
                try:
                    chunk = os.read(key.fd, CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                yield key.data, chunk


def iter_bounded_lines(proc: Any, *, max_line_bytes: int,
                       max_stream_bytes: int) -> Iterator[tuple[str, str]]:
    """Incremental UTF-8 lines: no blocking readline and no partial event parsing."""
    _positive_limit(max_line_bytes)
    _positive_limit(max_stream_bytes)
    pending = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"stdout": 0, "stderr": 0}
    for name, chunk in _pipe_chunks(proc):
        totals[name] += len(chunk)
        if totals[name] > max_stream_bytes:
            raise OutputLimitExceeded(name, max_stream_bytes)
        buffer = pending[name]
        buffer.extend(chunk)
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                if len(buffer) > max_line_bytes:
                    raise OutputLimitExceeded(f"{name} line", max_line_bytes)
                if not chunk and buffer:
                    yield name, bytes(buffer).decode("utf-8")
                    buffer.clear()
                break
            if newline + 1 > max_line_bytes:
                raise OutputLimitExceeded(f"{name} line", max_line_bytes)
            line = bytes(buffer[:newline + 1])
            del buffer[:newline + 1]
            yield name, line.decode("utf-8").replace("\r\n", "\n")


def run_bounded(argv: Sequence[str], *, timeout: float, cwd: str | None = None,
                env: Mapping[str, str] | None = None, text: bool = False,
                max_stdout: int = DEFAULT_OUTPUT_BYTES,
                max_stderr: int = DEFAULT_OUTPUT_BYTES) -> subprocess.CompletedProcess:
    """Closed-stdin POSIX helper with bounded capture, deadline, and failure cleanup."""
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    captures = {"stdout": ByteCapture(max_stdout), "stderr": ByteCapture(max_stderr)}
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(list(argv), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True, bufsize=0)
    try:
        for name, chunk in _pipe_chunks(proc, deadline=deadline, timeout=timeout):
            captures[name].feed(chunk)
            if captures[name].exceeded:
                raise OutputLimitExceeded(name, captures[name].limit,
                                          stdout=captures["stdout"].value(),
                                          stderr=captures["stderr"].value())
        proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        out, err = captures["stdout"].value(), captures["stderr"].value()
        if text:
            out, err = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        return subprocess.CompletedProcess(list(argv), proc.returncode, out, err)
    except BaseException as exc:
        # This helper created the process group. Do not signal a caller's group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            proc.wait(timeout=5)
        if isinstance(exc, subprocess.TimeoutExpired):
            exc.output = captures["stdout"].value()
            exc.stderr = captures["stderr"].value()
        raise
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
