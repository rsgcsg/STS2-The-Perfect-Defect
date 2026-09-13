"""Emulate POSIX chmod only in Windows fixtures; production remains Linux-only."""

from __future__ import annotations

import os
import stat
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

EMULATE_POSIX_PERMISSIONS = os.name == "nt"


class PosixPermissionFixture(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        if not EMULATE_POSIX_PERMISSIONS:
            return  # Linux qualification exercises real chmod/stat without mocks.
        stack = ExitStack()
        self.addCleanup(stack.close)
        modes: dict[Path, int] = {}
        native_chmod, native_stat, native_replace = Path.chmod, Path.stat, Path.replace

        def chmod(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
            native_chmod(path, mode, follow_symlinks=follow_symlinks)
            modes[path.absolute()] = mode

        def read_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            result = native_stat(path, follow_symlinks=follow_symlinks)
            mode = modes.get(path.absolute())
            if mode is None:
                return result
            # Preserve the actual file kind; emulate only POSIX permission bits.
            return os.stat_result((stat.S_IFMT(result.st_mode) | mode, *result[1:]))

        def replace(path: Path, target: str | Path) -> Path:
            result = native_replace(path, target)
            mode = modes.pop(path.absolute(), None)
            modes.pop(Path(target).absolute(), None)
            if mode is not None:
                modes[Path(target).absolute()] = mode
            return result

        stack.enter_context(patch.object(Path, "chmod", chmod))
        stack.enter_context(patch.object(Path, "stat", read_stat))
        stack.enter_context(patch.object(Path, "replace", replace))
