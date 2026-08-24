from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stpd.host_runtime_client import activate_host_runtime_client
from stpd.package_identity import PackageIdentityError, directory_sha256


def _package_fixture(root: Path, *, version: str = "1.1.0-rc.6") -> dict[str, str]:
    package = root / "consumers" / "python" / "sts2_headless"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    tools = root / "tools"
    tools.mkdir()
    for name in ("managed-pe-driver.mjs", "reference-pe-driver.mjs"):
        (tools / name).write_text("", encoding="utf-8")
    (root / "package.json").write_text(
        json.dumps({"name": "@rsgcsg/sts2-host-runtime", "version": version}),
        encoding="utf-8",
    )
    return {
        "package": "@rsgcsg/sts2-host-runtime",
        "version": "1.1.0-rc.6",
        "source_revision": "a" * 40,
        "component_tree_revision": "b" * 40,
        "release_asset_sha256": "c" * 64,
        "package_content_sha256": directory_sha256(root),
    }


class HeadlessClientTest(unittest.TestCase):
    def test_requires_the_exact_public_host_runtime_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PackageIdentityError):
                activate_host_runtime_client(root, {})

            expected = _package_fixture(root)
            self.assertEqual(
                activate_host_runtime_client(root, expected),
                root.resolve() / "consumers" / "python",
            )

            (root / "tools" / "managed-pe-driver.mjs").write_text(
                "// tampered\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(PackageIdentityError, "content differs"):
                activate_host_runtime_client(root, expected)

    def test_rejects_host_runtime_package_version_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = _package_fixture(root, version="9.9.9")
            with self.assertRaisesRegex(PackageIdentityError, "version differs"):
                activate_host_runtime_client(root, expected)


if __name__ == "__main__":
    unittest.main()
