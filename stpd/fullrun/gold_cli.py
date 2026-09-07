"""Collect label-free Gold tasks and explicit annotations without source edits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..json_boundary import BoundaryError, array, decode_json
from ..workbench.control import open_store, source_identity
from .campaign import default_harness_config
from .gold_store import decode_annotation, gold_report, load_tasks, publish_labels, publish_tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("tasks", "export", "labels", "report", "harness"))
    parser.add_argument("--store", default=".local/research-store")
    parser.add_argument("--dataset")
    parser.add_argument("--artifact")
    parser.add_argument("--split", choices=("gold_dev", "gold_test"), default="gold_dev")
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--synthetic-fixture", action="store_true")
    parser.add_argument("--mode", choices=("coverage", "tuning", "evaluation"), default="coverage")
    parser.add_argument("--protocol")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result: object
        if args.command == "harness":
            result = default_harness_config().to_dict()
        else:
            store = open_store(args.store)
            if args.command == "tasks":
                if not args.dataset:
                    raise BoundaryError("gold.cli", "exact_dataset_required")
                manifest = publish_tasks(
                    store,
                    args.dataset,
                    source_identity(Path.cwd()),
                    gold_split=args.split,
                    count=args.count,
                    seed=args.seed,
                )
                result = {"artifact_id": manifest.artifact_id}
            elif not args.artifact:
                raise BoundaryError("gold.cli", "exact_artifact_required")
            elif args.command == "export":
                _, tasks = load_tasks(store, args.artifact)
                result = {
                    "tasks": [task.to_dict() for task in tasks],
                    "annotation_templates": [
                        {
                            "schema": "stpd/fullrun-gold-annotation-v1",
                            "annotation_id": None,
                            "task_id": task.task_id,
                            "annotator_id": None,
                            "gold_split": task.gold_split,
                            "candidate_action_keys": list(task.action_keys),
                            "candidate_display_order": list(task.candidate_display_order),
                            "disposition": None,
                            "acceptable_actions": [],
                            "best_action": None,
                            "confidence": None,
                            "origin": None,
                            "state_hash": task.state_hash,
                        }
                        for task in tasks
                    ],
                    "instructions": "Fill explicit annotations; templates contain no labels.",
                }
            elif args.command == "labels":
                if args.annotations is None:
                    raise BoundaryError("gold.cli", "annotation_file_required")
                labels = tuple(
                    decode_annotation(v)
                    for v in array(decode_json(args.annotations.read_bytes()), "gold.annotations")
                )
                manifest = publish_labels(
                    store,
                    args.artifact,
                    labels,
                    source_identity(Path.cwd()),
                    allow_synthetic=args.synthetic_fixture,
                )
                result = {"artifact_id": manifest.artifact_id}
            else:
                result = gold_report(
                    store, args.artifact, mode=args.mode, protocol_id=args.protocol
                )
        rendered = json.dumps(result, sort_keys=True, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
        else:
            print(rendered)
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
