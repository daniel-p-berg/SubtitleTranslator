"""Cooperative cancellation and cancellable local process execution."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Sequence


class OperationCancelled(RuntimeError):
    """Raised when the user cancels an in-progress operation."""

    def __init__(self, message: str = "Operation cancelled.") -> None:
        super().__init__(message)


class CancellationToken:
    """Thread-safe cancellation signal shared by pipeline helpers."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelled()

    def wait(self, seconds: float) -> None:
        """Wait for a retry delay, waking immediately when cancelled."""
        if self._event.wait(max(0.0, seconds)):
            raise OperationCancelled()


def run_process(
    command: Sequence[str],
    *,
    cancellation_token: CancellationToken | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a local command while allowing prompt, process-group cancellation."""
    token = cancellation_token
    if token:
        token.raise_if_cancelled()

    process = subprocess.Popen(  # noqa: S603
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = time.monotonic()
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if token and token.cancelled:
                    _terminate_process_group(process)
                    raise OperationCancelled()
                if timeout is not None and time.monotonic() - started >= timeout:
                    _terminate_process_group(process)
                    raise subprocess.TimeoutExpired(command, timeout)
    except BaseException:
        if process.poll() is None:
            _terminate_process_group(process)
        raise

    if token:
        token.raise_if_cancelled()
    return subprocess.CompletedProcess(
        list(command),
        process.returncode,
        stdout,
        stderr,
    )


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """Terminate the command and any helpers it started."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            process.terminate()
        except OSError:
            return
    try:
        process.communicate(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            return
    try:
        process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        pass
