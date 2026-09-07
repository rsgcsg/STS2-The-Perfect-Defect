"""Cross-OS regression: evidence writers must emit the bytes that they hash."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from test_human_evidence_v2 import _v2_bundle


def test_fixture_export_and_payloads_are_exact_utf8_lf(tmp_path: Path) -> None:
    bundle = _v2_bundle(tmp_path)
    export = (bundle / "export/decisions.jsonl").read_bytes()
    assert b"\r" not in export
    assert export == (bundle / "raw/run-0001.jsonl").read_bytes()
    for path in (bundle / "raw/blobs/sha256").rglob("*.json"):
        raw = path.read_bytes()
        assert b"\r" not in raw
        assert hashlib.sha256(raw).hexdigest() == path.stem


def test_artifact_logical_parent_uses_posix_not_host_separators() -> None:
    logical = "features/" + "a" * 64 + "/manifest.json"
    prefix = PurePosixPath(logical).parent.as_posix()
    assert f"{prefix}/features.npy" == "features/" + "a" * 64 + "/features.npy"
