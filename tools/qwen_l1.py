#!/usr/bin/env python3
"""Explicit online/offline entry points for the STPD Qwen L1 gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.qwen.l1 import (  # noqa: E402
    QwenL1Error,
    QwenL1Pin,
    cache_snapshot_path,
    discover_repo_revision,
    discovery_timestamp,
    fetch_metadata_tokenizer,
    inspect_cache,
    load_pin,
    profile_jsonl,
)


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _write_or_print(value: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


def _pin(args: argparse.Namespace) -> QwenL1Pin:
    return load_pin(_path(args.pin) if args.pin else None)


def command_discover(args: argparse.Namespace) -> int:
    pin = _pin(args) if args.pin else None
    value = discover_repo_revision(
        args.model_id,
        args.revision,
        token=os.environ.get("HF_TOKEN"),
        pinned_revision=pin.repo_revision if pin else None,
    )
    value["observed_at"] = discovery_timestamp()
    _write_or_print(value, _path(args.output) if args.output else None)
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    pin = _pin(args)
    cache_dir = _path(args.cache_dir)
    artifact = fetch_metadata_tokenizer(cache_dir, pin, token=os.environ.get("HF_TOKEN"))
    value = artifact.to_dict()
    value["cache_snapshot"] = str(cache_snapshot_path(cache_dir, pin))
    value["manifest_path"] = str(
        cache_dir / "manifests" / f"{pin.model_id.replace('/', '--')}-{pin.repo_revision}.json"
    )
    _write_or_print(value, _path(args.output) if args.output else None)
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    pin = _pin(args)
    artifact = inspect_cache(_path(args.cache_dir), pin)
    value = artifact.to_dict()
    value["cache_snapshot"] = str(cache_snapshot_path(_path(args.cache_dir), pin))
    _write_or_print(value, _path(args.output) if args.output else None)
    return 0


def command_profile(args: argparse.Namespace) -> int:
    pin = _pin(args)
    if args.tokenizer_file:
        tokenizer_path = _path(args.tokenizer_file)
    else:
        cache_dir = _path(args.cache_dir)
        inspect_cache(cache_dir, pin)
        tokenizer_path = cache_snapshot_path(cache_dir, pin) / "tokenizer.json"
    report = profile_jsonl(tokenizer_path, _path(args.input), pin=pin)
    _write_or_print(report, _path(args.output) if args.output else None)
    return 0 if report["passed"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="online revision discovery only")
    discover.add_argument("--model-id", default="Qwen/Qwen3-0.6B-Base")
    discover.add_argument("--revision", default="main")
    discover.add_argument("--pin")
    discover.add_argument("--output")
    discover.set_defaults(handler=command_discover)

    for name, handler, help_text in (
        ("fetch", command_fetch, "online allow-listed metadata/tokenizer fetch"),
        ("inspect", command_inspect, "offline cache identity and weight check"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--pin")
        command.add_argument(
            "--cache-dir",
            default=os.environ.get("STPD_QWEN_L1_CACHE", "~/.cache/stpd/qwen-l1"),
        )
        command.add_argument("--output")
        command.set_defaults(handler=handler)

    profile = subparsers.add_parser("profile", help="offline JSONL token length profiling")
    profile.add_argument("--pin")
    profile.add_argument("--input", required=True)
    profile.add_argument("--tokenizer-file")
    profile.add_argument(
        "--cache-dir",
        default=os.environ.get("STPD_QWEN_L1_CACHE", "~/.cache/stpd/qwen-l1"),
    )
    profile.add_argument("--output")
    profile.set_defaults(handler=command_profile)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        handler = cast(Callable[[argparse.Namespace], int], args.handler)
        return handler(args)
    except QwenL1Error as exc:
        print(f"qwen-l1: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
