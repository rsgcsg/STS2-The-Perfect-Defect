"""Capture local gate/E2E and exact GitHub CI receipts without changing repository source."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from stpd.json_boundary import BoundaryError, decode_json
from stpd.workbench.control import REPOSITORY, source_identity
from stpd.workbench.readiness import readiness

ROOT = Path(__file__).resolve().parents[1]


def github_json(arguments: list[str]) -> Any:
    try:
        raw = subprocess.check_output(["gh", *arguments], cwd=ROOT, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        raise BoundaryError("qualification", "github_read_failed") from None
    return decode_json(raw)


def capture(ci_run: int, output: Path) -> dict[str, Any]:
    runtime = source_identity(ROOT)
    run = github_json(["api", f"repos/{REPOSITORY}/actions/runs/{ci_run}"])
    jobs = github_json(["api", f"repos/{REPOSITORY}/actions/runs/{ci_run}/jobs?per_page=100"])
    expected = {name: "success" for name in ("linux-portable", "windows-portable", "locked-python")}
    observed = {job["name"]: job["conclusion"] for job in jobs["jobs"]}
    if (
        run["head_sha"] != runtime.source_revision
        or run["conclusion"] != "success"
        or run["status"] != "completed"
        or run["name"] != "ci"
        or observed != expected
        or jobs["total_count"] != 3
    ):
        raise BoundaryError("qualification", "exact_head_portable_ci_required")
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    with (local / "portable-closeout.log").open("wb") as log:
        outcome = subprocess.run(
            [sys.executable, "tools/project.py", "closeout"],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if outcome.returncode:
        raise BoundaryError("qualification", "portable_failed_see_local_closeout_log")
    if source_identity(ROOT) != runtime:
        raise BoundaryError("qualification", "source_changed_during_qualification")
    e2e = decode_json((local / "cpu-e2e.json").read_bytes())
    receipt = {
        "schema": "stpd/prefullrun-qualification-v1",
        "producer": runtime.to_dict(),
        "portable": "PASS",
        "e2e": e2e,
        "ci": {
            "head_sha": run["head_sha"],
            "run_id": ci_run,
            "url": run["html_url"],
            "conclusion": run["conclusion"],
            "jobs": observed,
        },
    }
    report = readiness(ROOT, receipt)
    if report["verdict"] != "STPD_PRE_FULLRUN_AI_ENGINEERING_READY":
        raise BoundaryError("qualification", "readiness_receipt_incomplete")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-run", required=True, type=int)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/qualification.json")
    args = parser.parse_args()
    try:
        print(json.dumps(capture(args.ci_run, args.output), indent=2, sort_keys=True))
        return 0
    except (BoundaryError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "verdict": "FAIL",
                    "code": error.code
                    if isinstance(error, BoundaryError)
                    else type(error).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
