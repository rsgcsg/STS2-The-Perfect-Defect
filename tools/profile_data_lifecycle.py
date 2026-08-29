#!/usr/bin/env python3
"""Verify and profile one immutable STPD canonical dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

from stpd.canonical import canonical_json
from stpd.data.lifecycle_profile import profile_canonical_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="directory containing manifest.json")
    parser.add_argument("--read-repeats", type=int, default=3)
    parser.add_argument("--skip-layout-probes", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = profile_canonical_dataset(
        arguments.dataset,
        read_repeats=arguments.read_repeats,
        probe_layouts=not arguments.skip_layout_probes,
    )
    encoded = canonical_json(report) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
