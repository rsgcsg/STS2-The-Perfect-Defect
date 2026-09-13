from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from stpd.hub.verification_worker import run_verifier


@pytest.mark.parametrize("cancel", [False, True])
def test_supervisor_reaps_actual_child_on_deadline_or_shutdown(cancel: bool) -> None:
    original = subprocess.Popen
    children = []
    scratches = []

    def spawn(*args: object, **kwargs: object) -> subprocess.Popen:
        scratch = Path(kwargs["env"]["TMPDIR"])
        (scratch / "expanded-partial").write_bytes(b"retained only during child lifetime")
        scratches.append(scratch)
        child = original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(child)
        return child

    shutdown = threading.Event()
    if cancel:
        shutdown.set()
    started = time.monotonic()
    with patch("stpd.hub.verification_worker.subprocess.Popen", side_effect=spawn):
        assert not run_verifier([], timeout=0.15, shutdown=shutdown)
    assert time.monotonic() - started < 5
    assert len(children) == 1 and children[0].poll() is not None
    assert all(not path.exists() for path in scratches)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux deployment process resource contract")
def test_linux_address_space_limit_rejects_oversized_allocation() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from stpd.hub.verification_worker import constrain_worker; "
            "constrain_worker(); bytearray(2 * 1024**3)",
        ],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0 and b"MemoryError" in result.stderr
