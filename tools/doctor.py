#!/usr/bin/env python3
"""Inspect a local pre-Qwen STPD checkout and optional exact environment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.host_runtime_client import DEFAULT_HOST_RUNTIME  # noqa: E402
from stpd.operations import run_doctor  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen-cache", type=Path)
    parser.add_argument("--require-qwen-cache", action="store_true")
    parser.add_argument("--host-runtime", type=Path, default=DEFAULT_HOST_RUNTIME)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_doctor(
        ROOT,
        qwen_cache=args.qwen_cache,
        require_qwen_cache=args.require_qwen_cache,
        host_runtime=args.host_runtime,
        candidate=args.candidate,
    )
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
