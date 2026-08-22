"""Load the strategy-free Headless Python client from one explicit checkout."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType


def activate_headless_client(headless: Path) -> Path:
    package_root = headless.resolve() / "consumers" / "python"
    package = package_root / "sts2_headless" / "__init__.py"
    if not package.is_file():
        raise FileNotFoundError(
            f"Headless checkout does not contain its Python client: {package}"
        )

    loaded: ModuleType | None = sys.modules.get("sts2_headless")
    if loaded is not None:
        loaded_file = getattr(loaded, "__file__", None)
        if loaded_file is None or package_root not in Path(loaded_file).resolve().parents:
            raise RuntimeError("sts2_headless was already imported from a different checkout.")

    rendered = str(package_root)
    if rendered not in sys.path:
        sys.path.insert(0, rendered)
    return package_root
