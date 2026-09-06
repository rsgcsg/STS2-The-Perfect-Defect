"""Deterministic multi-surface engineering evidence; explicitly not a Platform schema."""

from __future__ import annotations

import hashlib
from typing import Any

from ..canonical import semantic_hash
from ..json_boundary import (
    BoundaryError,
    FrozenObject,
    array,
    decode_json,
    digest,
    json_bytes,
    object_fields,
    text,
    unsigned,
)
from .contracts import (
    AdmittedRead,
    EvidenceLink,
    ResearchTransitionV1,
    SemanticAction,
    SemanticState,
    SourceProjection,
)

SYNTHETIC_SCHEMA = "stpd/synthetic-fullrun-source-v1"
SURFACE_EXAMPLES = ("combat", "generated_choice", "reward", "potion", "shop", "shop_removal",
                    "rest", "event", "nested_selector", "map", "act_transition", "run_terminal")


def synthetic_bundle(*, runs: int = 12, seed: int = 0) -> bytes:
    unsigned(runs, "fixture.runs")
    unsigned(seed, "fixture.seed")
    if runs < 3:
        raise BoundaryError("fixture", "at_least_three_runs_required")
    records: list[dict[str, Any]] = []
    proofs = {}
    for run_index in range(runs):
        run_id = f"synthetic-{seed}-{run_index}"
        for step, surface in enumerate(SURFACE_EXAMPLES):
            run = FrozenObject.of({"character": "fixture", "act": step // 4 + 1, "floor": step,
                                   "hp": 50 + run_index, "max_hp": 80, "gold": 30 + run_index,
                                   "deck": [{"definition": "fixture-card", "count": 3}]})
            actions = tuple(SemanticAction(
                key=f"opaque-action-{run_index}-{step}-{index}", kind="choose_option",
                subject=FrozenObject.of({"definition": f"fixture-option-{index}"}),
                arguments=FrozenObject.of({"visible_cost": index, "visible_effect": index + step % 2}),
            ) for index in range(2 + step % 2))
            read = AdmittedRead("run_deck", FrozenObject.of({"cards": ["fixture-card"]}),
                                semantic_hash([run_id, step, "read"]))
            state = SemanticState(run, FrozenObject.of({"surface": surface, "domain": "gameplay"}),
                                  tuple(action.subject for action in actions), (read,))
            successor = SemanticState(run, FrozenObject.of({"resolved": True, "floor": step}), (), ())
            records.append({
                "record_id": f"record-{run_index}-{step}", "run_id": run_id,
                "episode_id": run_id, "step_index": step, "domain": "gameplay",
                "family": "synthetic_choice", "surface": surface, "state": state.to_dict(),
                "actions": [action.to_dict() for action in actions], "catalog_complete": True,
                "catalog_count": len(actions), "chosen_key": actions[-1].key,
                "successor": successor.to_dict(), "terminal": step == len(SURFACE_EXAMPLES) - 1,
                "disposition": "committed",
            })
        proofs[run_id] = {"started_ref": semantic_hash([run_id, "start"]),
                          "terminal_ref": semantic_hash([run_id, "end"]),
                          "record_count": len(SURFACE_EXAMPLES)}
    return json_bytes({"schema": SYNTHETIC_SCHEMA, "environment_identity": semantic_hash(
        {"kind": "synthetic-engineering", "version": 1, "seed": seed}),
        "run_proofs": proofs, "records": records})


class SyntheticSourceAdapter:
    adapter_id = "stpd-synthetic-fullrun-adapter-v1"

    def project(self, raw: bytes) -> SourceProjection:
        obj = object_fields(decode_json(raw), {"schema", "environment_identity", "run_proofs", "records"},
                            "synthetic_source")
        if obj["schema"] != SYNTHETIC_SCHEMA:
            raise BoundaryError("source_adapter", "final_platform_adapter_not_installed")
        environment = digest(obj["environment_identity"], "source.environment")
        if not isinstance(obj["run_proofs"], dict):
            raise BoundaryError("source", "missing_run_proofs")
        bundle_id = hashlib.sha256(raw).hexdigest()
        records = []
        seen = set()
        for raw_record in array(obj["records"], "source.records"):
            record = object_fields(raw_record, {
                "record_id", "run_id", "episode_id", "step_index", "domain", "family", "surface",
                "state", "actions", "catalog_complete", "catalog_count", "chosen_key", "successor",
                "terminal", "disposition",
            }, "source.record")
            record_id = text(record["record_id"], "source.record_id")
            if record_id in seen:
                raise BoundaryError("source", "duplicate_record_id")
            seen.add(record_id)
            committed = record["disposition"] == "committed"
            provenance = EvidenceLink(
                bundle_id, record_id, environment, "engineering",
                semantic_hash([self.adapter_id, bundle_id]), f"synthetic-root-{record_id}",
                semantic_hash([bundle_id, record_id, "catalog"]),
                semantic_hash([bundle_id, record_id, "commit"]) if committed else None,
                semantic_hash([bundle_id, record_id, "successor"]) if committed else None,
            )
            transition = ResearchTransitionV1(
                record["run_id"], record["episode_id"], record["step_index"], record["domain"],
                record["family"], record["surface"], SemanticState.decode(record["state"]),
                tuple(SemanticAction.decode(a) for a in array(record["actions"], "source.actions")),
                record["catalog_complete"], record["catalog_count"], record["chosen_key"],
                SemanticState.decode(record["successor"]) if record["successor"] is not None else None,
                record["terminal"], record["disposition"], provenance,
            )
            records.append(transition)
        run_ids = {record.run_id for record in records}
        if set(obj["run_proofs"]) != run_ids:
            raise BoundaryError("source", "run_proof_inventory_mismatch")
        for run_id in run_ids:
            proof = object_fields(obj["run_proofs"][run_id],
                                  {"started_ref", "terminal_ref", "record_count"}, "run_proof")
            digest(proof["started_ref"], "run.start")
            digest(proof["terminal_ref"], "run.terminal")
            run_records = sorted((r for r in records if r.run_id == run_id), key=lambda r: r.step_index)
            count = unsigned(proof["record_count"], "run.record_count")
            if count != len(run_records) or [r.step_index for r in run_records] != list(range(count)):
                raise BoundaryError("source", "missing_or_duplicate_disposition")
            if not run_records or not run_records[-1].terminal or any(r.terminal for r in run_records[:-1]):
                raise BoundaryError("source", "inconsistent_run_continuity")
        return SourceProjection(self.adapter_id, bundle_id, "engineering",
                                FrozenObject.of(obj["run_proofs"]), tuple(records))
