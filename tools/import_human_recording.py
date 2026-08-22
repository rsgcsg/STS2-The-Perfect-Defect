#!/usr/bin/env python3
"""Import an audited Human Annotator export into the canonical STPD data lane."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from stpd.data.human_annotator import import_human_recording
from stpd.data.manifest import DataSource
from stpd.data.pipeline import DatasetBuildError, build_canonical_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split-salt", required=True)
    arguments = parser.parse_args()

    report = import_human_recording(arguments.source)
    summary = {
        "source": str(arguments.source),
        "source_sha256": report.source_sha256,
        "accepted": report.accepted_count,
        "rejected": report.rejected_count,
        "rejection_counts": report.rejection_counts,
    }
    if report.rejected_count or not report.accepted_count:
        print(json.dumps({"status": "fail", **summary}, indent=2))
        return 1
    source_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        manifest, b0 = build_canonical_dataset(
            [item.transition.to_dict() for item in report.accepted],
            output_dir=arguments.output,
            schema_root=Path(__file__).parents[1] / "schemas",
            source=DataSource(
                source_id=f"human-annotator-{report.source_sha256[:16]}",
                kind="human_native_ui",
                source_revision=report.source_sha256,
                license_spdx="LicenseRef-Private-Human-Data",
                provenance_uri=f"file://{arguments.source.resolve()}",
            ),
            stpd_source_revision=source_revision,
            created_at=datetime.now(UTC).isoformat(),
            split_salt=arguments.split_salt,
        )
    except DatasetBuildError as error:
        print(json.dumps({"status": "fail", "error": str(error), **summary}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "pass",
                **summary,
                "manifest_id": manifest.manifest_id,
                "b0": b0.to_dict(),
                "non_claims": [
                    "B0 does not prove human policy quality.",
                    "One bounded recording does not qualify unseen UI families.",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
