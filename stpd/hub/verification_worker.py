"""Bounded verifier process: malformed evidence cannot take down the API process."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence


def constrain_worker() -> None:
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
        resource.setrlimit(resource.RLIMIT_FSIZE, (3 * 1024**3, 3 * 1024**3))


def run_verifier(
    arguments: Sequence[str], *, timeout: float = 150, shutdown: threading.Event | None = None
) -> bool:
    # The parent owns temporary storage so a killed child cannot leak expanded bundles.
    with tempfile.TemporaryDirectory(prefix="stpd-verifier-") as scratch:
        return _run_verifier(arguments, timeout, shutdown, scratch)


def _run_verifier(
    arguments: Sequence[str], timeout: float, shutdown: threading.Event | None, scratch: str
) -> bool:
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "stpd.hub", "verify", "--isolated", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "TMPDIR": scratch, "TEMP": scratch, "TMP": scratch},
        )
    except OSError:
        return False
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline and not (shutdown and shutdown.is_set()):
            try:
                return process.wait(timeout=min(0.2, max(0.01, deadline - time.monotonic()))) == 0
            except subprocess.TimeoutExpired:
                pass
        return False
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
