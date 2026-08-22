from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stpd.headless_client import activate_headless_client


class HeadlessClientTest(unittest.TestCase):
    def test_requires_the_explicit_checkout_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                activate_headless_client(root)

            package = root / "consumers" / "python" / "sts2_headless"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            self.assertEqual(
                activate_headless_client(root),
                root.resolve() / "consumers" / "python",
            )


if __name__ == "__main__":
    unittest.main()
