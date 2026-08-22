"""Audit the exact raw AgenticSTS subset without converting missing evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from stpd.data.agenticsts_audit import audit_agenticsts_snapshot, load_agenticsts_source_pin

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PIN = ROOT / "configs" / "v0" / "data" / "agenticsts-trajectories.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quantify raw AgenticSTS evidence against strict STPD rank admission."
    )
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--pin", type=Path, default=DEFAULT_PIN)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pin = load_agenticsts_source_pin(args.pin)
    report: dict[str, Any] = audit_agenticsts_snapshot(args.snapshot, pin)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite audit report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
