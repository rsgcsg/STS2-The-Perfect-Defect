"""Bounded verifier process: malformed evidence cannot take down the API process."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence


def constrain_worker() -> None:
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
        resource.setrlimit(resource.RLIMIT_FSIZE, (3 * 1024**3, 3 * 1024**3))


def run_verifier(arguments: Sequence[str], *, timeout: int = 150) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "stpd.hub", "verify", "--isolated", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
