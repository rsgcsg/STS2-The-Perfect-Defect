#!/usr/bin/env python3
"""Prepare or owner-run the exact unified-Human S1 1K-2K smoke."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.experiments import prepare_s1_smoke, run_s1_smoke  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="verify exact inputs and stop for the owner")
    prepare.add_argument("--corpus-snapshot", required=True, type=Path)
    prepare.add_argument("--smoke-handoff", required=True, type=Path)
    prepare.add_argument("--qwen-cache", required=True, type=Path)
    prepare.add_argument("--pretrained-smoke", required=True, type=Path)
    prepare.add_argument("--random-smoke", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--config", type=Path)
    run = commands.add_parser("run", help="execute only with the exact owner acknowledgement")
    run.add_argument("--ready", required=True, type=Path)
    run.add_argument("--ready-sha256", required=True)
    run.add_argument("--owner-ack", required=True)
    arguments = parser.parse_args()

    if arguments.command == "prepare":
        kwargs = {
            "corpus_snapshot": arguments.corpus_snapshot,
            "smoke_handoff": arguments.smoke_handoff,
            "qwen_cache": arguments.qwen_cache,
            "pretrained_smoke": arguments.pretrained_smoke,
            "random_smoke": arguments.random_smoke,
            "output": arguments.output,
        }
        if arguments.config is not None:
            kwargs["config_path"] = arguments.config
        result = prepare_s1_smoke(**kwargs)
    else:
        result = run_s1_smoke(
            ready_path=arguments.ready,
            ready_sha256=arguments.ready_sha256,
            owner_ack=arguments.owner_ack,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
