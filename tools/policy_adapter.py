#!/usr/bin/env python3
"""Run the decision-only S1 policy adapter as an NDJSON child process."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.policy import DEFAULT_CONFIG, DEFAULT_MANIFEST, PolicyAdapter, serve_ndjson  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()
    adapter = PolicyAdapter(
        config_path=arguments.config,
        manifest_path=arguments.manifest,
    )
    return serve_ndjson(adapter)


if __name__ == "__main__":
    raise SystemExit(main())
