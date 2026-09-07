"""Byte identity must retain POSIX ordering on case-insensitive Windows paths."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath

from stpd.package_identity import directory_sha256


def test_os_path_order_is_not_an_artifact_identity() -> None:
    names = ("Alpha.js", "zeta.js", "Beta.js", "alpha/part.js")
    assert [str(p) for p in sorted(map(PurePosixPath, names))] != [
        p.as_posix() for p in sorted(map(PureWindowsPath, names))
    ]
    for path_type in (PurePosixPath, PureWindowsPath):
        ordered = sorted(map(path_type, names), key=lambda p: p.as_posix())
        assert [p.as_posix() for p in ordered] == sorted(names)


def test_package_hash_matches_exact_sorted_relative_paths(tmp_path: Path) -> None:
    files = {"Alpha.js": b"A\r\n", "zeta.js": b"z\n", "Beta.js": b"B", "alpha/part.js": b"p"}
    for relative, payload in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    reference = hashlib.sha256()
    for relative in sorted(files):
        reference.update(relative.encode("utf-8") + b"\0" + files[relative] + b"\0")
    expected = reference.hexdigest()
    assert directory_sha256(tmp_path) == expected
    (tmp_path / "Alpha.js").write_bytes(b"A\n")
    assert directory_sha256(tmp_path) != expected
