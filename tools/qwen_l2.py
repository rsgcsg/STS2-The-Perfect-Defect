#!/usr/bin/env python3
"""Explicit online fetch and offline inspection commands for pinned full Qwen L2."""

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

from stpd.qwen.l2 import (  # noqa: E402
    QwenL2Error,
    QwenL2Pin,
    default_l2_cache,
    discover_l2_pin,
    fetch_l2_snapshot,
    inspect_l2_cache,
    l2_snapshot_path,
    load_l2_pin,
)


def _write(value: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def _pin(args: argparse.Namespace) -> QwenL2Pin:
    return load_l2_pin(Path(args.pin).expanduser() if args.pin else None)


def _cache(args: argparse.Namespace) -> Path:
    return Path(args.cache_dir).expanduser()


def command_discover(args: argparse.Namespace) -> int:
    _write(
        discover_l2_pin(_pin(args), token=os.environ.get("HF_TOKEN")),
        Path(args.output).expanduser() if args.output else None,
    )
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    pin = _pin(args)
    artifact = fetch_l2_snapshot(_cache(args), pin, token=os.environ.get("HF_TOKEN"))
    value = artifact.to_dict()
    value["cache_snapshot"] = str(l2_snapshot_path(_cache(args), pin))
    _write(value, Path(args.output).expanduser() if args.output else None)
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    pin = _pin(args)
    artifact = inspect_l2_cache(_cache(args), pin)
    value = artifact.to_dict()
    value["cache_snapshot"] = str(l2_snapshot_path(_cache(args), pin))
    _write(value, Path(args.output).expanduser() if args.output else None)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler, help_text in (
        ("discover", command_discover, "verify pinned remote revision and LFS identity"),
        ("fetch", command_fetch, "download and hash the exact full-weight snapshot"),
        ("inspect", command_inspect, "offline full-weight snapshot verification"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--pin")
        command.add_argument("--cache-dir", default=str(default_l2_cache()))
        command.add_argument("--output")
        command.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        handler = cast(Callable[[argparse.Namespace], int], args.handler)
        return handler(args)
    except QwenL2Error as exc:
        print(f"qwen-l2: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
