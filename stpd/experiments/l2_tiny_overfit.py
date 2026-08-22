"""Fail-closed preparation and owner execution for the first real L2 tiny overfit."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import torch
from jsonschema import Draft202012Validator
from torch.nn import functional as F

from ..canonical import canonical_json, semantic_hash
from ..contracts import ContractError
from ..data import (
    DataFile,
    DataManifest,
    DataSource,
    SplitAssignment,
    read_transition_parquet,
    research_action_from_record,
    research_state_from_record,
    validate_b0,
)
from ..models import RankBatch, Scheme1Scorer
from ..qwen.l2 import inspect_l2_cache, l2_snapshot_path, load_l2_pin
from ..qwen.real_backend import CachingQwenBackend, RealQwenBackend
from ..representation import InputProfile, ModelSerializerV0
from ..training import CheckpointIdentity, CheckpointManager, TrainerState, V0Trainer

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "v0" / "experiments" / "l2-tiny-overfit.json"
OWNER_ACK = "I_AM_THE_OWNER_AND_AUTHORIZE_L2_TINY_OVERFIT"
PREPARATION_SCHEMA = "stpd/l2-tiny-overfit-preparation-v0"
RESULT_SCHEMA = "stpd/l2-tiny-overfit-result-v0"


class ExperimentPreparationError(ContractError):
    """An exact owner-training precondition was missing or had changed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentPreparationError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ExperimentPreparationError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], value)


def _git_identity() -> tuple[str, str]:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if status:
        raise ExperimentPreparationError("owner-training preparation requires a clean source")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ExperimentPreparationError("source revision is not an exact Git commit")
    return revision, "clean"


def _validate_config(value: Mapping[str, Any]) -> None:
    if value.get("schema") != "stpd/l2-tiny-overfit-config-v0":
        raise ExperimentPreparationError("unsupported L2 tiny-overfit config schema")
    expected = {
        "protocol_version": "stpd-v0-l2-2026-08-22",
        "architecture_id": "scheme1-linear-pretrained",
        "input_profile": InputProfile.STANDARD.value,
        "qwen_control": "pretrained",
        "seed": 20260822,
    }
    for key, required in expected.items():
        if value.get(key) != required:
            raise ExperimentPreparationError(
                f"tiny-overfit {key} must be {required!r}, got {value.get(key)!r}"
            )
    selection = _object(value.get("example_selection"), "example_selection")
    if selection.get("split") != "train" or selection.get("rank_eligible_only") is not True:
        raise ExperimentPreparationError("tiny-overfit requires rank-eligible train records")
    if selection.get("legal_action_completeness") != "complete":
        raise ExperimentPreparationError("tiny-overfit requires complete legal-action catalogs")
    if selection.get("order") != "transition_semantic_hash_ascending":
        raise ExperimentPreparationError("tiny-overfit record order must be semantic-hash sorted")
    maximum = _positive_int(selection.get("maximum_examples"), "maximum_examples")
    minimum = _positive_int(selection.get("minimum_examples"), "minimum_examples")
    if minimum > maximum:
        raise ExperimentPreparationError("minimum_examples exceeds maximum_examples")
    budget = _object(value.get("budget"), "budget")
    steps = _positive_int(budget.get("optimizer_steps"), "optimizer_steps")
    if steps > 64 or budget.get("checkpoint_steps") != [0, steps]:
        raise ExperimentPreparationError(
            "tiny-overfit budget must remain bounded at steps 0 and 64"
        )
    boundaries = _object(value.get("boundaries"), "boundaries")
    for forbidden in (
        "gold_dev_allowed",
        "gold_test_allowed",
        "b6_allowed",
        "scientific_claim_allowed",
    ):
        if boundaries.get(forbidden) is not False:
            raise ExperimentPreparationError(f"tiny-overfit boundary must forbid {forbidden}")
    if boundaries.get("owner_execution_required") is not True:
        raise ExperimentPreparationError("tiny-overfit must require owner execution")


def _manifest_from_value(value: Mapping[str, Any]) -> DataManifest:
    try:
        sources = tuple(
            DataSource(
                source_id=str(item["source_id"]),
                kind=str(item["kind"]),
                source_revision=str(item["source_revision"]),
                license_spdx=str(item["license_spdx"]),
                provenance_uri=str(item["provenance_uri"]),
            )
            for item in _objects(value["sources"], "sources")
        )
        files = tuple(
            DataFile(
                path=str(item["path"]),
                sha256=str(item["sha256"]),
                bytes=int(item["bytes"]),
                rows=int(item["rows"]),
                semantic_hash=str(item["semantic_hash"]),
            )
            for item in _objects(value["files"], "files")
        )
        manifest = DataManifest(
            manifest_id=str(value["manifest_id"]),
            created_at=str(value["created_at"]),
            source_revision=str(value["source_revision"]),
            contract_schema=str(value["contract_schema"]),
            sources=sources,
            files=files,
            row_count=int(value["row_count"]),
            split=dict(_object(value["split"], "split")),
            deduplication=dict(_object(value["deduplication"], "deduplication")),
            eligibility_counts={
                str(key): int(count)
                for key, count in _object(value["eligibility_counts"], "eligibility_counts").items()
            },
            truncation_applied=bool(value["truncation_applied"]),
            non_claims=tuple(str(item) for item in _sequence(value["non_claims"], "non_claims")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentPreparationError("invalid canonical data manifest") from exc
    manifest.validate()
    if manifest.to_dict() != dict(value):
        raise ExperimentPreparationError("data manifest does not round-trip canonically")
    return manifest


def verify_canonical_dataset(
    manifest_path: Path,
) -> tuple[list[dict[str, Any]], DataManifest, dict[str, SplitAssignment], dict[str, Any]]:
    """Verify schema, byte hashes, semantic hashes, recorded splits, and B0 from scratch."""

    manifest_path = manifest_path.expanduser().resolve()
    value = _json_object(manifest_path)
    schema = _json_object(ROOT / "schemas" / "data-manifest-v0.schema.json")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path)
    )
    if errors:
        raise ExperimentPreparationError(f"data manifest schema failed: {errors[0].message}")
    manifest = _manifest_from_value(value)
    if len(manifest.files) != 1:
        raise ExperimentPreparationError("tiny-overfit requires exactly one canonical Parquet file")
    file = manifest.files[0]
    if Path(file.path).name != file.path or Path(file.path).suffix != ".parquet":
        raise ExperimentPreparationError("manifest Parquet path must be one safe basename")
    parquet_path = manifest_path.parent / file.path
    if not parquet_path.is_file():
        raise ExperimentPreparationError(f"canonical Parquet file is missing: {parquet_path}")
    if parquet_path.stat().st_size != file.bytes or _sha256(parquet_path) != file.sha256:
        raise ExperimentPreparationError("canonical Parquet byte identity mismatch")
    records = read_transition_parquet(parquet_path)
    semantic_dataset_hash = semantic_hash([semantic_hash(record) for record in records])
    if len(records) != file.rows or semantic_dataset_hash != file.semantic_hash:
        raise ExperimentPreparationError("canonical Parquet row or semantic identity mismatch")
    split = manifest.split
    assignments_value = _object(split.get("assignments"), "split.assignments")
    canonical_assignments = {str(key): str(name) for key, name in assignments_value.items()}
    if split.get("assignments_hash") != semantic_hash(canonical_assignments):
        raise ExperimentPreparationError("split assignment digest mismatch")
    episode_roots = {str(record["episode_id"]): str(record["seed"]) for record in records}
    if set(canonical_assignments) != set(episode_roots):
        raise ExperimentPreparationError("split assignments do not cover the exact episodes")
    assignments: dict[str, SplitAssignment] = {}
    for episode, name in canonical_assignments.items():
        if name not in ("train", "dev", "test"):
            raise ExperimentPreparationError(f"invalid split name for {episode}: {name}")
        assignments[episode] = SplitAssignment(episode, episode_roots[episode], cast(Any, name))
    b0 = validate_b0(
        records,
        schema_root=ROOT / "schemas",
        manifest=manifest,
        splits=assignments,
    )
    if b0.verdict != "pass" or b0.eligibility_counts != manifest.eligibility_counts:
        raise ExperimentPreparationError("dataset failed exact B0 or eligibility-count replay")
    return records, manifest, assignments, b0.to_dict()


def select_tiny_records(
    records: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, SplitAssignment],
    config: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Select the preregistered bounded train subset without changing catalog contents."""

    _validate_config(config)
    selection = _object(config["example_selection"], "example_selection")
    minimum_candidates = _positive_int(
        selection.get("minimum_candidates_per_example"), "minimum_candidates_per_example"
    )
    eligible = [
        record
        for record in records
        if assignments.get(str(record.get("episode_id"))) is not None
        and assignments[str(record["episode_id"])].split == selection["split"]
        and _object(record.get("eligibility"), "eligibility").get("rank") is True
        and _object(record.get("eligibility"), "eligibility").get("rank_mode") == "full_listwise"
        and _object(record.get("eligibility"), "eligibility").get("legal_action_completeness")
        == "complete"
        and len(_sequence(record.get("legal_actions"), "legal_actions")) >= minimum_candidates
    ]
    eligible.sort(key=semantic_hash)
    selected = eligible[: int(selection["maximum_examples"])]
    if len(selected) < int(selection["minimum_examples"]):
        raise ExperimentPreparationError(
            "dataset has too few rank-eligible complete-catalog train examples for tiny overfit"
        )
    return selected


def build_rank_batches(
    records: Sequence[Mapping[str, Any]],
    *,
    profile: InputProfile = InputProfile.STANDARD,
) -> tuple[RankBatch, ...]:
    """Build candidate-aligned rank batches from exact canonical records."""

    serializer = ModelSerializerV0(profile)
    batches: list[RankBatch] = []
    for record in records:
        state = research_state_from_record(_object(record.get("state"), "state"))
        actions = tuple(
            research_action_from_record(item)
            for item in _objects(record.get("legal_actions"), "legal_actions")
        )
        chosen = research_action_from_record(_object(record.get("chosen_action"), "chosen_action"))
        keys = [action.action_key for action in actions]
        if keys.count(chosen.action_key) != 1:
            raise ExperimentPreparationError("chosen action is not unique in its exact catalog")
        batch = RankBatch(
            state_text=serializer.serialize_state(state),
            action_texts=tuple(serializer.serialize_action(action) for action in actions),
            target_index=keys.index(chosen.action_key),
            source_id=str(_object(record.get("policy"), "policy").get("source", "")),
        )
        batch.validate()
        batches.append(batch)
    return tuple(batches)


def prepare_l2_tiny_overfit(
    *,
    dataset_manifest: Path,
    qwen_cache: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Write exact owner-run inputs and stop without constructing an optimizer."""

    source_revision, source_status = _git_identity()
    config_path = config_path.expanduser().resolve()
    config = _json_object(config_path)
    _validate_config(config)
    records, manifest, assignments, b0 = verify_canonical_dataset(dataset_manifest)
    selected = select_tiny_records(records, assignments, config)
    batches = build_rank_batches(selected)
    qwen_cache = qwen_cache.expanduser().resolve()
    pin = load_l2_pin()
    artifact = inspect_l2_cache(qwen_cache, pin)
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ExperimentPreparationError("owner-training host failed CUDA/BF16 admission")
    output = output.expanduser().resolve()
    if output.exists():
        raise ExperimentPreparationError(f"refusing to overwrite preparation output: {output}")
    attempt_output = output / "attempt-001"
    preparation_path = output / "preparation.json"
    owner_command = [
        sys.executable,
        str(ROOT / "tools" / "l2_tiny_overfit.py"),
        "run",
        "--preparation",
        str(preparation_path),
        "--attempt-id",
        "attempt-001",
        "--owner-ack",
        OWNER_ACK,
    ]
    properties = torch.cuda.get_device_properties(0)
    disk = shutil.disk_usage(output.parent)
    manifest_path = dataset_manifest.expanduser().resolve()
    selected_rows = [
        {
            "transition_id": str(record["transition_id"]),
            "record_sha256": semantic_hash(record),
            "episode_id": str(record["episode_id"]),
            "candidate_count": len(cast(Sequence[Any], record["legal_actions"])),
            "target_index": batch.target_index,
        }
        for record, batch in zip(selected, batches, strict=True)
    ]
    value = {
        "schema": PREPARATION_SCHEMA,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "status": "ready_for_owner_training",
        "stop_code": "STOP - OWNER TRAINING REQUIRED: L2-TINY-OVERFIT",
        "source": {"revision": source_revision, "worktree": source_status},
        "protocol": {
            "version": config["protocol_version"],
            "path": "docs/SCIENTIFIC_EXPERIMENT_PROTOCOL.md",
            "sha256": _sha256(ROOT / "docs" / "SCIENTIFIC_EXPERIMENT_PROTOCOL.md"),
        },
        "config": {
            "path": str(config_path),
            "sha256": _sha256(config_path),
            "value": config,
        },
        "dataset": {
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "manifest_content_hash": manifest.content_hash,
            "manifest_id": manifest.manifest_id,
            "source_revision": manifest.source_revision,
            "parquet": asdict(manifest.files[0]),
            "b0": b0,
            "b0_sha256": semantic_hash(b0),
            "selected_rows": selected_rows,
            "selected_rows_sha256": semantic_hash(selected_rows),
        },
        "qwen": {
            "cache_dir": str(qwen_cache),
            "snapshot_path": str(l2_snapshot_path(qwen_cache, pin)),
            "artifact": artifact.to_dict(),
            "actual_weight_files": [
                file.to_dict() for file in artifact.files if file.kind == "weights"
            ],
            "device": "cuda:0",
            "dtype": "bfloat16",
            "feature_dtype": "float32",
            "control": "pretrained",
        },
        "seed": int(config["seed"]),
        "owner_command": owner_command,
        "resources": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "gpu_name": properties.name,
            "gpu_total_memory_bytes": properties.total_memory,
            "gpu_compute_capability": f"{properties.major}.{properties.minor}",
            "disk_free_bytes": disk.free,
            "expected_optimizer_steps": config["budget"]["optimizer_steps"],
            "expected_qwen_parameter_count": 596049920,
        },
        "artifacts": {
            "attempt_output": str(attempt_output),
            "initial_checkpoint": str(attempt_output / "checkpoint-step-000.pt"),
            "final_checkpoint": str(attempt_output / "checkpoint-step-064.pt"),
            "result": str(attempt_output / "result.json"),
        },
        "pass_fail": config["pass_criteria"],
        "retry_rule": (
            "Retain every failed attempt and its reason. Diagnose first; any retry uses a new "
            "attempt-NNN directory and an unchanged source/data/Qwen/config identity, or a new "
            "protocol/config version when an identity changes."
        ),
        "non_claims": config["non_claims"],
    }
    output.mkdir(parents=True)
    preparation_path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    return value


def _ranking_metrics(model: Scheme1Scorer, batches: Sequence[RankBatch]) -> dict[str, Any]:
    losses: list[float] = []
    correct = 0
    logits: list[list[float]] = []
    model.eval()
    with torch.no_grad():
        for batch in batches:
            scores = model(batch.state_text, batch.action_texts)
            loss = F.cross_entropy(
                scores.unsqueeze(0), torch.tensor([batch.target_index], device=scores.device)
            )
            losses.append(float(loss.cpu()))
            correct += int(int(scores.argmax().item()) == batch.target_index)
            logits.append([float(value) for value in scores.cpu().tolist()])
    return {
        "mean_listwise_nll": sum(losses) / len(losses),
        "memorized_top1_fraction": correct / len(batches),
        "per_example_logits": logits,
    }


def run_l2_tiny_overfit(
    *,
    preparation_path: Path,
    attempt_id: str,
    owner_ack: str,
) -> dict[str, Any]:
    """Execute the bounded real-dataset run only after an explicit owner acknowledgement."""

    if owner_ack != OWNER_ACK:
        raise ExperimentPreparationError("missing exact owner acknowledgement")
    if re.fullmatch(r"attempt-[0-9]{3}", attempt_id) is None:
        raise ExperimentPreparationError("attempt_id must match attempt-NNN")
    preparation_path = preparation_path.expanduser().resolve()
    preparation = _json_object(preparation_path)
    if preparation.get("schema") != PREPARATION_SCHEMA:
        raise ExperimentPreparationError("unsupported preparation manifest")
    source_revision, _ = _git_identity()
    if source_revision != _object(preparation.get("source"), "source").get("revision"):
        raise ExperimentPreparationError("source changed after owner-training preparation")
    config_info = _object(preparation.get("config"), "config")
    config_path = Path(str(config_info["path"]))
    config = _json_object(config_path)
    _validate_config(config)
    if _sha256(config_path) != config_info.get("sha256"):
        raise ExperimentPreparationError("training config changed after preparation")
    dataset_info = _object(preparation.get("dataset"), "dataset")
    dataset_manifest = Path(str(dataset_info["manifest_path"]))
    if _sha256(dataset_manifest) != dataset_info.get("manifest_sha256"):
        raise ExperimentPreparationError("dataset manifest changed after preparation")
    records, manifest, assignments, b0 = verify_canonical_dataset(dataset_manifest)
    if semantic_hash(b0) != dataset_info.get("b0_sha256"):
        raise ExperimentPreparationError("B0 replay changed after preparation")
    selected = select_tiny_records(records, assignments, config)
    selected_rows = [
        {
            "transition_id": str(record["transition_id"]),
            "record_sha256": semantic_hash(record),
            "episode_id": str(record["episode_id"]),
            "candidate_count": len(cast(Sequence[Any], record["legal_actions"])),
            "target_index": next(
                index
                for index, action in enumerate(
                    cast(Sequence[Mapping[str, Any]], record["legal_actions"])
                )
                if action["action_key"]
                == _object(record["chosen_action"], "chosen_action")["action_key"]
            ),
        }
        for record in selected
    ]
    if semantic_hash(selected_rows) != dataset_info.get("selected_rows_sha256"):
        raise ExperimentPreparationError("selected rows changed after preparation")
    qwen_info = _object(preparation.get("qwen"), "qwen")
    qwen_cache = Path(str(qwen_info["cache_dir"]))
    artifact = inspect_l2_cache(qwen_cache)
    if artifact.to_dict() != qwen_info.get("artifact"):
        raise ExperimentPreparationError("Qwen artifact changed after preparation")
    base_output = preparation_path.parent
    attempt_output = base_output / attempt_id
    if attempt_output.exists():
        raise ExperimentPreparationError(f"refusing to overwrite attempt: {attempt_output}")
    attempt_output.mkdir(parents=True)

    seed = int(config["seed"])
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    started = perf_counter()
    backend = RealQwenBackend(
        l2_snapshot_path(qwen_cache),
        control="pretrained",
        device="cuda:0",
        feature_dtype=torch.float32,
    )
    cache = CachingQwenBackend(backend)
    batches = build_rank_batches(selected)
    model = Scheme1Scorer(cache, backend.hidden_size, head="linear").to(backend.device)
    optimizer_config = _object(config["optimizer"], "optimizer")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(optimizer_config["learning_rate"]),
        weight_decay=float(optimizer_config["weight_decay"]),
    )
    trainer = V0Trainer(
        model,
        optimizer,
        grad_clip_norm=float(optimizer_config["grad_clip_norm"]),
    )
    checkpoint_identity = CheckpointIdentity(
        source_revision=source_revision,
        data_manifest_hash=manifest.content_hash,
        architecture_id=str(config["architecture_id"]),
        config_hash=str(config_info["sha256"]),
        serializer_version=ModelSerializerV0.version,
        input_profile=str(config["input_profile"]),
        qwen=cache.identity,
    )
    manager = CheckpointManager()
    initial_checkpoint = attempt_output / "checkpoint-step-000.pt"
    manager.save(
        initial_checkpoint,
        model=model,
        optimizer=optimizer,
        identity=checkpoint_identity,
        trainer_state=TrainerState(0, 0, 0, 0),
    )
    initial = _ranking_metrics(model, batches)
    trace: list[dict[str, Any]] = []
    optimizer_steps = int(_object(config["budget"], "budget")["optimizer_steps"])
    for step in range(1, optimizer_steps + 1):
        batch = batches[(step - 1) % len(batches)]
        metrics = trainer.train_step(batch)
        measured = _ranking_metrics(model, batches)
        trace.append({"step": step, "train_step": asdict(metrics), "evaluation": measured})
    final = trace[-1]["evaluation"]
    final_checkpoint = attempt_output / f"checkpoint-step-{optimizer_steps:03d}.pt"
    manager.save(
        final_checkpoint,
        model=model,
        optimizer=optimizer,
        identity=checkpoint_identity,
        trainer_state=TrainerState(
            optimizer_steps,
            optimizer_steps,
            0,
            sum(
                sum(backend.token_lengths([batch.state_text, *batch.action_texts]))
                for batch in batches
            ),
        ),
    )
    criteria = _object(config["pass_criteria"], "pass_criteria")
    initial_loss = float(initial["mean_listwise_nll"])
    final_loss = float(final["mean_listwise_nll"])
    reduction = 0.0 if initial_loss == 0 else (initial_loss - final_loss) / initial_loss
    checks = {
        "memorized_top1_fraction": float(final["memorized_top1_fraction"])
        >= float(criteria["memorized_top1_fraction"]),
        "maximum_final_mean_listwise_nll": final_loss
        <= float(criteria["maximum_final_mean_listwise_nll"]),
        "minimum_relative_mean_loss_reduction": reduction
        >= float(criteria["minimum_relative_mean_loss_reduction"]),
        "qwen_gradient_tensor_count": backend.parameter_gradients_absent()
        and int(criteria["qwen_gradient_tensor_count"]) == 0,
        "all_values_finite": all(
            torch.isfinite(torch.tensor(value)).item()
            for value in (initial_loss, final_loss, reduction)
        ),
    }
    result = {
        "schema": RESULT_SCHEMA,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "attempt_id": attempt_id,
        "preparation_sha256": _sha256(preparation_path),
        "source_revision": source_revision,
        "dataset_manifest_content_hash": manifest.content_hash,
        "qwen": backend.runtime_summary(),
        "qwen_identity": asdict(cache.identity),
        "cache_manifest": cache.manifest(),
        "config": config,
        "selected_rows": selected_rows,
        "initial": initial,
        "final": final,
        "relative_mean_loss_reduction": reduction,
        "checks": checks,
        "trace": trace,
        "elapsed_seconds": perf_counter() - started,
        "artifacts": {
            "initial_checkpoint": initial_checkpoint.name,
            "final_checkpoint": final_checkpoint.name,
        },
        "non_claims": config["non_claims"],
    }
    (attempt_output / "result.json").write_text(canonical_json(result) + "\n", encoding="utf-8")
    return result


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExperimentPreparationError(f"{name} must be an object")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ExperimentPreparationError(f"{name} must be an array")
    return value


def _objects(value: Any, name: str) -> Sequence[Mapping[str, Any]]:
    sequence = _sequence(value, name)
    if not all(isinstance(item, Mapping) for item in sequence):
        raise ExperimentPreparationError(f"{name} must contain only objects")
    return cast(Sequence[Mapping[str, Any]], sequence)


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ExperimentPreparationError(f"{name} must be a positive integer")
    return value
