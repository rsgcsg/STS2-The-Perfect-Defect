#!/usr/bin/env python3
"""Create a portable L2 rebuild manifest from current exact local evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.canonical import canonical_json  # noqa: E402
from stpd.l2_handoff import build_l2_handoff  # noqa: E402
from stpd.qwen.l1 import inspect_cache, load_pin  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen-cache", required=True, type=Path)
    parser.add_argument("--runtime-report", required=True, type=Path)
    parser.add_argument("--data-manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if status.strip():
        raise RuntimeError("L2 handoff requires a clean STPD checkout")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    runtime = json.loads(args.runtime_report.read_text(encoding="utf-8"))
    pin = load_pin()
    manifest = build_l2_handoff(
        source_revision=revision,
        uv_lock=ROOT / "uv.lock",
        qwen_pin=pin,
        qwen_l1=inspect_cache(args.qwen_cache.expanduser(), pin),
        environment=runtime["environment"],
        data_manifest=args.data_manifest,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    print(json.dumps({"status": "l2_handoff_ready", "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

