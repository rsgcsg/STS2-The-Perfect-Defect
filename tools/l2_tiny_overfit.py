#!/usr/bin/env python3
"""Prepare or owner-run the bounded first real-data L2 tiny overfit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.experiments import prepare_l2_tiny_overfit, run_l2_tiny_overfit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="verify exact inputs and stop for the owner")
    prepare.add_argument("--dataset-manifest", required=True, type=Path)
    prepare.add_argument("--qwen-cache", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--config", type=Path)
    run = commands.add_parser("run", help="execute only with the exact owner acknowledgement")
    run.add_argument("--preparation", required=True, type=Path)
    run.add_argument("--attempt-id", required=True)
    run.add_argument("--owner-ack", required=True)
    args = parser.parse_args()

    if args.command == "prepare":
        kwargs = {
            "dataset_manifest": args.dataset_manifest,
            "qwen_cache": args.qwen_cache,
            "output": args.output,
        }
        if args.config is not None:
            kwargs["config_path"] = args.config
        result = prepare_l2_tiny_overfit(**kwargs)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    result = run_l2_tiny_overfit(
        preparation_path=args.preparation,
        attempt_id=args.attempt_id,
        owner_ack=args.owner_ack,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
