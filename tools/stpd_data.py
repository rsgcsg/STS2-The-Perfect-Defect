#!/usr/bin/env python3
"""Build a canonical STPD dataset from explicit raw JSONL input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stpd.data import DataSource, build_canonical_dataset, read_raw_jsonl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--schema-root", type=Path, default=Path("schemas"))
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-kind", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--license-spdx", required=True)
    parser.add_argument("--provenance-uri", required=True)
    parser.add_argument("--stpd-source-revision", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--split-salt", required=True)
    args = parser.parse_args()
    source = DataSource(
        args.source_id,
        args.source_kind,
        args.source_revision,
        args.license_spdx,
        args.provenance_uri,
    )
    manifest, report = build_canonical_dataset(
        read_raw_jsonl(args.raw),
        output_dir=args.output,
        schema_root=args.schema_root,
        source=source,
        stpd_source_revision=args.stpd_source_revision,
        created_at=args.created_at,
        split_salt=args.split_salt,
    )
    print(json.dumps({"manifest": manifest.to_dict(), "b0": report.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
