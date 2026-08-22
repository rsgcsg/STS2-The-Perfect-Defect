#!/usr/bin/env python3
"""Register HumanSessionBundles and build/freeze deterministic Human corpora."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from stpd.data.human_corpus import (
    CollectionCampaign,
    CollectionProfile,
    HumanCorpusError,
    build_human_corpus,
    freeze_smoke_handoff,
    inspect_corpus_snapshot,
    register_session_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def _source_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _assert_clean_source() -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise HumanCorpusError(
            "commit or remove STPD worktree changes before evidence corpus build"
        )


def _shared(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register")
    _shared(register)
    register.add_argument("--collection-root", type=Path, required=True)
    register.add_argument("--bundle", type=Path, required=True)
    register.add_argument("--registry", type=Path, required=True)

    build = commands.add_parser("build")
    _shared(build)
    build.add_argument("--collection-root", type=Path, required=True)
    build.add_argument("--registry", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--split-salt", required=True)
    build.add_argument("--tokenizer-file", type=Path)
    build.add_argument("--tokenizer-revision")
    build.add_argument("--stpd-source-revision", default=None)

    inspect = commands.add_parser("inspect")
    inspect.add_argument("snapshot", type=Path)

    freeze = commands.add_parser("freeze-smoke-handoff")
    freeze.add_argument("snapshot", type=Path)
    freeze.add_argument("--output-root", type=Path, required=True)
    freeze.add_argument("--minimum-records", type=int, default=1000)

    arguments = parser.parse_args()
    try:
        result: dict[str, Any]
        if arguments.command == "register":
            profile = CollectionProfile.load(arguments.profile)
            campaign = CollectionCampaign.load(arguments.campaign)
            entry, status = register_session_bundle(
                collection_root=arguments.collection_root,
                bundle_directory=arguments.bundle,
                registry_directory=arguments.registry,
                profile=profile,
                campaign=campaign,
            )
            result = {"status": status, "entry": entry.to_dict()}
        elif arguments.command == "build":
            _assert_clean_source()
            profile = CollectionProfile.load(arguments.profile)
            campaign = CollectionCampaign.load(arguments.campaign)
            built = build_human_corpus(
                collection_root=arguments.collection_root,
                registry_directory=arguments.registry,
                profile=profile,
                campaign=campaign,
                output_root=arguments.output_root,
                schema_root=ROOT / "schemas",
                stpd_source_revision=arguments.stpd_source_revision or _source_revision(),
                split_salt=arguments.split_salt,
                tokenizer_path=arguments.tokenizer_file,
                tokenizer_revision=arguments.tokenizer_revision,
            )
            result = {
                "status": built.status,
                "corpus_id": built.corpus_id,
                "snapshot_directory": str(built.snapshot_directory),
                "accepted_records": built.accepted_records,
                "sessions": built.sessions,
                "b0_verdict": built.b0_verdict,
            }
        elif arguments.command == "inspect":
            result = inspect_corpus_snapshot(arguments.snapshot)
        else:
            destination = freeze_smoke_handoff(
                snapshot_directory=arguments.snapshot,
                output_root=arguments.output_root,
                minimum_records=arguments.minimum_records,
            )
            result = {"status": "frozen", "handoff_directory": str(destination)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except HumanCorpusError as error:
        print(json.dumps({"status": "fail", "error": str(error)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
