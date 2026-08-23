"""Fail-closed preparation and owner execution for the first Human S1 smoke."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import torch

from ..canonical import canonical_json, semantic_hash
from ..contracts import ContractError
from ..data import inspect_corpus_snapshot
from ..models import RankBatch, Scheme1Scorer
from ..qwen.l2 import inspect_l2_cache, l2_snapshot_path, load_l2_pin
from ..qwen.real_backend import CachingQwenBackend, RealQwenBackend
from ..representation import InputProfile, ModelSerializerV1
from ..training import CheckpointIdentity, CheckpointManager, TrainerState, V0Trainer
from .l2_tiny_overfit import build_rank_batches, verify_canonical_dataset

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "v0" / "experiments" / "s1-human-combat-smoke-v1.json"
OWNER_ACK = "I_AM_THE_OWNER_AND_AUTHORIZE_S1_1K_2K_SMOKE"
READY_SCHEMA = "stpd/s1-smoke-training-ready-v1"
RESULT_SCHEMA = "stpd/s1-smoke-result-v1"
STOP_CODE = "STOP - OWNER TRAINING REQUIRED: S1-1K-2K-SMOKE"


class S1PreparationError(ContractError):
    """An S1 preparation or owner-run identity check failed closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise S1PreparationError(f"cannot read JSON object: {path}") from error
    if not isinstance(value, dict):
        raise S1PreparationError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], value)


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise S1PreparationError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise S1PreparationError(f"{name} must be a positive integer")
    return int(value)


def _git_identity() -> str:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if status:
        raise S1PreparationError("S1 preparation and execution require a clean source")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise S1PreparationError("source revision is not an exact Git commit")
    return revision


def _validate_config(value: Mapping[str, Any]) -> None:
    expected = {
        "schema": "stpd/s1-smoke-config-v1",
        "protocol_id": "S1-1K-2K-SMOKE",
        "architecture_id": "scheme1-linear-pretrained",
        "family": "scheme1",
        "head": "linear",
        "input_profile": InputProfile.STANDARD.value,
        "serializer_version": ModelSerializerV1.version,
        "qwen_control": "pretrained",
        "seed": 20260822,
    }
    for name, required in expected.items():
        if value.get(name) != required:
            raise S1PreparationError(
                f"S1 config {name} must be {required!r}, got {value.get(name)!r}"
            )
    data = _object(value.get("data"), "data")
    minimum = _positive_int(data.get("minimum_unified_records"), "minimum_unified_records")
    maximum = _positive_int(data.get("maximum_unified_records"), "maximum_unified_records")
    train_minimum = _positive_int(data.get("minimum_train_records"), "minimum_train_records")
    if minimum != 1500 or maximum != 2000 or train_minimum != 1000:
        raise S1PreparationError("S1 data gates must remain 1500/2000 unified and 1000 train")
    if minimum > maximum:
        raise S1PreparationError("S1 minimum_unified_records exceeds maximum")
    expected_data = {
        "split": "train",
        "rank_eligible_only": True,
        "legal_action_completeness": "complete",
        "order": "transition_semantic_hash_ascending",
    }
    for name, required in expected_data.items():
        if data.get(name) != required:
            raise S1PreparationError(f"S1 data.{name} must be {required!r}")
    optimizer = _object(value.get("optimizer"), "optimizer")
    if optimizer != {
        "name": "adamw",
        "learning_rate": 0.0001,
        "weight_decay": 0.01,
        "grad_clip_norm": 1.0,
    }:
        raise S1PreparationError("S1 optimizer identity drift")
    budget = _object(value.get("budget"), "budget")
    if budget != {
        "epochs": 1,
        "candidate_batching": "one_complete_candidate_set",
        "checkpoint_steps": [0, "final"],
    }:
        raise S1PreparationError("S1 budget identity drift")
    boundaries = _object(value.get("boundaries"), "boundaries")
    if boundaries.get("owner_execution_required") is not True:
        raise S1PreparationError("S1 must remain owner gated")
    for forbidden in (
        "human_gold_allowed",
        "gold_test_allowed",
        "b6_allowed",
        "core_matrix_allowed",
        "scientific_claim_allowed",
    ):
        if boundaries.get(forbidden) is not False:
            raise S1PreparationError(f"S1 boundary must forbid {forbidden}")


def _verify_checksum_directory(directory: Path) -> str:
    inventory_path = directory / "checksums.sha256"
    if not inventory_path.is_file():
        raise S1PreparationError(f"checksum inventory is missing: {directory}")
    entries: dict[str, str] = {}
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise S1PreparationError(f"invalid checksum inventory line: {line!r}")
        if Path(name).name != name or name == "checksums.sha256" or name in entries:
            raise S1PreparationError(f"unsafe checksum inventory entry: {name!r}")
        entries[name] = digest
    actual_names = {
        path.name for path in directory.iterdir() if path.is_file() and path != inventory_path
    }
    if actual_names != set(entries):
        raise S1PreparationError(f"checksum inventory file set drift: {directory}")
    for name, expected in entries.items():
        if _sha256(directory / name) != expected:
            raise S1PreparationError(f"checksum mismatch: {directory / name}")
    return _sha256(inventory_path)


def _verify_engineering_smoke(path: Path, control: str, revision: str) -> dict[str, Any]:
    report = _json_object(path)
    if (
        report.get("schema") != "stpd/qwen-l2-engineering-smoke-v0"
        or report.get("status") != "pass"
        or report.get("source_revision") != revision
        or report.get("source_dirty") is not False
    ):
        raise S1PreparationError(f"{control} Qwen smoke identity/status failed")
    controls = _object(report.get("controls"), "controls")
    if set(controls) != {control}:
        raise S1PreparationError(f"Qwen smoke must contain only {control} control")
    evidence = _object(controls[control], f"controls.{control}")
    if evidence.get("frozen_parameters") is not True:
        raise S1PreparationError(f"{control} Qwen smoke did not prove frozen parameters")
    if evidence.get("qwen_gradients_absent") is not True:
        raise S1PreparationError(f"{control} Qwen smoke observed Qwen gradients")
    representations = _object(evidence.get("representations"), "representations")
    if representations.get("deterministic_exact") is not True:
        raise S1PreparationError(f"{control} Qwen extraction was not deterministic")
    models = _object(evidence.get("models"), "models")
    if set(models) != {"scheme1", "s2-simple", "s2-sdt"}:
        raise S1PreparationError(f"{control} Qwen smoke did not cover all model families")
    for family, measured in models.items():
        value = _object(measured, f"models.{family}")
        loss = value.get("loss")
        if not isinstance(loss, (int, float)) or not math.isfinite(loss):
            raise S1PreparationError(f"{control}/{family} loss is not finite")
        gradients = _object(value.get("gradients"), f"models.{family}.gradients")
        if int(gradients.get("gradient_tensor_count", 0)) <= 0:
            raise S1PreparationError(f"{control}/{family} has no trainable gradients")
    return report


def _select_train_records(
    records: Sequence[Mapping[str, Any]], assignments: Mapping[str, Any], config: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    selected = [
        record
        for record in records
        if str(record.get("episode_id")) in assignments
        and assignments[str(record["episode_id"])].split == "train"
        and _object(record.get("eligibility"), "eligibility").get("rank") is True
        and _object(record.get("eligibility"), "eligibility").get("rank_mode")
        == "full_listwise"
        and _object(record.get("eligibility"), "eligibility").get(
            "legal_action_completeness"
        )
        == "complete"
    ]
    selected.sort(key=semantic_hash)
    minimum = int(_object(config["data"], "data")["minimum_train_records"])
    if len(selected) < minimum:
        raise S1PreparationError(
            f"S1 requires at least {minimum} eligible train records, got {len(selected)}"
        )
    return selected


def _runtime_summary() -> dict[str, Any]:
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise S1PreparationError("S1 host requires CUDA and BF16")
    properties = torch.cuda.get_device_properties(0)
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": "cuda:0",
        "dtype": "bfloat16",
        "feature_dtype": "float32",
        "gpu_name": properties.name,
        "gpu_total_memory_bytes": properties.total_memory,
        "gpu_compute_capability": f"{properties.major}.{properties.minor}",
        "deterministic_algorithms_required": True,
        "cublas_workspace_config": ":4096:8",
    }


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def prepare_s1_smoke(
    *,
    corpus_snapshot: Path,
    smoke_handoff: Path,
    qwen_cache: Path,
    pretrained_smoke: Path,
    random_smoke: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Verify Gate-0 inputs, write an exact owner command, and construct no optimizer."""

    revision = _git_identity()
    config_path = config_path.expanduser().resolve()
    config = _json_object(config_path)
    _validate_config(config)
    snapshot = corpus_snapshot.expanduser().resolve()
    inspected = inspect_corpus_snapshot(snapshot)
    if inspected.get("corpus_kind") != "combined":
        raise S1PreparationError("S1 must consume one immutable unified corpus")
    checksum_sha = _verify_checksum_directory(snapshot)
    identity = _json_object(snapshot / "corpus-identity.json")
    report = _json_object(snapshot / "corpus-report.json")
    manifest_path = snapshot / "manifest.json"
    b0 = _json_object(snapshot / "b0-report.json")
    token = _json_object(snapshot / "token-profile-report.json")
    records, manifest, assignments, replayed_b0 = verify_canonical_dataset(manifest_path)
    data = _object(config["data"], "data")
    if not int(data["minimum_unified_records"]) <= len(records) <= int(
        data["maximum_unified_records"]
    ):
        raise S1PreparationError("unified corpus is outside the frozen S1 1K-2K envelope")
    selected = _select_train_records(records, assignments, config)
    if identity.get("stpd_source_revision") != revision or manifest.source_revision != revision:
        raise S1PreparationError("unified corpus is not bound to the current clean source")
    if identity.get("serializer_version") != config["serializer_version"]:
        raise S1PreparationError("unified corpus serializer differs from S1 config")
    if b0.get("verdict") != "pass" or replayed_b0.get("verdict") != "pass":
        raise S1PreparationError("unified corpus B0 did not replay as pass")
    if token.get("passed") is not True or token.get("serializer_version") != config[
        "serializer_version"
    ]:
        raise S1PreparationError("unified corpus Standard token gate failed")
    summary = _object(
        _object(token.get("by_profile"), "token.by_profile")[InputProfile.STANDARD.value][
            "summary"
        ],
        "token.summary",
    )
    if int(summary.get("p95", 8193)) > 4096 or int(summary.get("max", 8193)) > 8192:
        raise S1PreparationError("unified corpus token thresholds drifted")
    split_counts = _object(report.get("split_episode_counts"), "split_episode_counts")
    if any(int(split_counts.get(name, 0)) <= 0 for name in ("train", "dev", "test")):
        raise S1PreparationError("unified corpus requires non-empty train/dev/test splits")
    deduplication = _object(report.get("deduplication"), "deduplication")
    if int(deduplication.get("cross_split_semantic_duplicates", -1)) != 0:
        raise S1PreparationError("unified corpus has cross-split semantic duplicates")

    handoff_directory = smoke_handoff.expanduser().resolve()
    handoff_checksum_sha = _verify_checksum_directory(handoff_directory)
    handoff_path = handoff_directory / "handoff.json"
    handoff = _json_object(handoff_path)
    if (
        handoff.get("schema") != "stpd/human-smoke-handoff-v1"
        or handoff.get("corpus_id") != identity.get("corpus_id")
        or handoff.get("stpd_source_revision") != revision
        or handoff.get("training_authorized") is not False
        or int(handoff.get("accepted_records", 0)) != len(records)
    ):
        raise S1PreparationError("frozen smoke handoff differs from the unified corpus")

    qwen_cache = qwen_cache.expanduser().resolve()
    pin = load_l2_pin()
    artifact = inspect_l2_cache(qwen_cache, pin)
    pretrained_path = pretrained_smoke.expanduser().resolve()
    random_path = random_smoke.expanduser().resolve()
    pretrained = _verify_engineering_smoke(pretrained_path, "pretrained", revision)
    random = _verify_engineering_smoke(random_path, "random", revision)
    pretrained_runtime = _object(
        _object(_object(pretrained["controls"], "controls")["pretrained"], "pretrained")[
            "runtime"
        ],
        "pretrained.runtime",
    )
    qwen_identity = _object(pretrained_runtime.get("identity"), "qwen.identity")
    tokenizer_file = next(
        (file for file in artifact.files if file.name == "tokenizer.json"), None
    )
    if tokenizer_file is None:
        raise S1PreparationError("Qwen artifact is missing the exact tokenizer file")
    if (
        qwen_identity.get("model_revision") != pin.repo_revision
        or qwen_identity.get("tokenizer_sha256") != artifact.tokenizer_bundle_sha256
        or tokenizer_file.sha256 != identity.get("tokenizer_sha256")
        or qwen_identity.get("weights_sha256") != artifact.weights_sha256
        or qwen_identity.get("frozen") is not True
        or qwen_identity.get("control") != "pretrained"
    ):
        raise S1PreparationError("pretrained Qwen smoke identity differs from corpus/pin")
    runtime = _runtime_summary()
    output = output.expanduser().resolve()
    ready_path = output / "READY_TO_TRAIN.json"
    start_path = output / "START_TRAINING.ps1"
    if ready_path.exists() or start_path.exists():
        raise S1PreparationError(f"refusing to overwrite training-ready output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    selected_identity = [
        {
            "transition_id": str(record["transition_id"]),
            "record_sha256": semantic_hash(record),
            "episode_id": str(record["episode_id"]),
            "candidate_count": len(cast(Sequence[Any], record["legal_actions"])),
        }
        for record in selected
    ]
    result_output = output / "s1-smoke-output" / f"source-{revision[:12]}"
    ready = {
        "schema": READY_SCHEMA,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "status": "ready_for_owner_training",
        "stop_code": STOP_CODE,
        "ready_for_s1_smoke": True,
        "scientific_core_ready": False,
        "blockers": [
            "human_gold_unavailable",
            "gold_dev_unavailable",
            "gold_test_sealed",
            "scientific_core_not_authorized",
        ],
        "source": {"revision": revision, "worktree": "clean"},
        "config": {
            "path": str(config_path),
            "sha256": _sha256(config_path),
            "value": config,
        },
        "corpus": {
            "snapshot": str(snapshot),
            "corpus_id": identity["corpus_id"],
            "combination_id": identity["combination_id"],
            "combination_plan_sha256": identity["combination_plan_sha256"],
            "identity_sha256": _sha256(snapshot / "corpus-identity.json"),
            "checksums_sha256": checksum_sha,
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "manifest_content_hash": manifest.content_hash,
            "parquet_sha256": identity["parquet_sha256"],
            "split_assignments_sha256": identity["split_assignments_sha256"],
            "b0_report_sha256": _sha256(snapshot / "b0-report.json"),
            "token_profile_sha256": _sha256(snapshot / "token-profile-report.json"),
            "serializer_version": identity["serializer_version"],
            "tokenizer_revision": identity["tokenizer_revision"],
            "tokenizer_sha256": identity["tokenizer_sha256"],
            "record_count": len(records),
            "train_record_count": len(selected),
            "selected_records_sha256": semantic_hash(selected_identity),
            "split_episode_counts": split_counts,
            "b0": b0,
            "standard_token_summary": summary,
        },
        "smoke_handoff": {
            "directory": str(handoff_directory),
            "handoff_id": handoff["handoff_id"],
            "handoff_sha256": _sha256(handoff_path),
            "checksums_sha256": handoff_checksum_sha,
        },
        "qwen": {
            "cache_dir": str(qwen_cache),
            "snapshot_path": str(l2_snapshot_path(qwen_cache, pin)),
            "artifact": artifact.to_dict(),
            "pretrained_identity": qwen_identity,
            "control": "pretrained",
            "random_control_seed": int(random["random_seed"]),
        },
        "engineering_smokes": {
            "pretrained": {"path": str(pretrained_path), "sha256": _sha256(pretrained_path)},
            "random": {"path": str(random_path), "sha256": _sha256(random_path)},
            "all_model_families": ["scheme1", "s2-simple", "s2-sdt"],
            "finite_loss_and_gradients": True,
            "qwen_gradients_absent": True,
            "deterministic_extraction": True,
        },
        "runtime": runtime,
        "determinism": {
            "seed": config["seed"],
            "torch_deterministic_algorithms": True,
            "cublas_workspace_config": ":4096:8",
            "candidate_order": data["order"],
        },
        "model": {
            "architecture_id": config["architecture_id"],
            "family": config["family"],
            "head": config["head"],
            "input_profile": config["input_profile"],
            "serializer_version": config["serializer_version"],
        },
        "optimizer": config["optimizer"],
        "budget": {**_object(config["budget"], "budget"), "optimizer_steps": len(selected)},
        "artifacts": {
            "output_directory": str(result_output),
            "initial_checkpoint": str(result_output / "checkpoint-step-0000.pt"),
            "final_checkpoint": str(result_output / f"checkpoint-step-{len(selected):04d}.pt"),
            "result": str(result_output / "result.json"),
        },
        "pass_fail": config["pass_criteria"],
        "gold": {
            "human_gold_available": False,
            "gold_dev_opened": False,
            "gold_test_opened": False,
        },
        "non_claims": config["non_claims"],
    }
    ready_path.write_text(canonical_json(ready) + "\n", encoding="utf-8")
    ready_sha = _sha256(ready_path)
    uv = shutil.which("uv")
    if uv is None:
        user_uv = Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
        uv = str(user_uv) if user_uv.is_file() else None
    if uv is None:
        raise S1PreparationError("uv executable is unavailable")
    command = (
        f"& {_powershell_literal(str(Path(uv).resolve()))} run python "
        f"{_powershell_literal(str(ROOT / 'tools' / 's1_smoke.py'))} run "
        f"--ready {_powershell_literal(str(ready_path))} "
        f"--ready-sha256 {_powershell_literal(ready_sha)} "
        f"--owner-ack {_powershell_literal(OWNER_ACK)}"
    )
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            f"Set-Location -LiteralPath {_powershell_literal(str(ROOT))}",
            "$env:CUBLAS_WORKSPACE_CONFIG = ':4096:8'",
            command,
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
            "",
        )
    )
    start_path.write_text(script, encoding="utf-8")
    return {
        "status": "ready_for_owner_training",
        "stop_code": STOP_CODE,
        "ready_path": str(ready_path),
        "ready_sha256": ready_sha,
        "start_path": str(start_path),
        "corpus_id": identity["corpus_id"],
        "record_count": len(records),
        "train_record_count": len(selected),
    }


def _verify_ready(ready_path: Path, expected_sha256: str) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    Mapping[str, Any],
]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise S1PreparationError("expected READY SHA-256 is invalid")
    ready_path = ready_path.expanduser().resolve()
    if _sha256(ready_path) != expected_sha256:
        raise S1PreparationError("READY_TO_TRAIN checksum drift")
    ready = _json_object(ready_path)
    if (
        ready.get("schema") != READY_SCHEMA
        or ready.get("ready_for_s1_smoke") is not True
        or ready.get("scientific_core_ready") is not False
        or ready.get("stop_code") != STOP_CODE
    ):
        raise S1PreparationError("READY_TO_TRAIN status/boundary drift")
    revision = _git_identity()
    source = _object(ready.get("source"), "source")
    if source != {"revision": revision, "worktree": "clean"}:
        raise S1PreparationError("source changed after S1 preparation")
    config_identity = _object(ready.get("config"), "config")
    config_path = Path(str(config_identity["path"])).resolve()
    if _sha256(config_path) != config_identity.get("sha256"):
        raise S1PreparationError("S1 config checksum drift")
    config = _json_object(config_path)
    _validate_config(config)
    if config != config_identity.get("value"):
        raise S1PreparationError("S1 config value drift")
    corpus = _object(ready.get("corpus"), "corpus")
    snapshot = Path(str(corpus["snapshot"])).resolve()
    inspected = inspect_corpus_snapshot(snapshot)
    if inspected.get("corpus_id") != corpus.get("corpus_id"):
        raise S1PreparationError("unified corpus identity drift")
    if _verify_checksum_directory(snapshot) != corpus.get("checksums_sha256"):
        raise S1PreparationError("unified corpus checksum inventory drift")
    if _sha256(snapshot / "corpus-identity.json") != corpus.get("identity_sha256"):
        raise S1PreparationError("unified corpus identity document drift")
    manifest_path = Path(str(corpus["manifest_path"])).resolve()
    if manifest_path.parent != snapshot or _sha256(manifest_path) != corpus.get(
        "manifest_sha256"
    ):
        raise S1PreparationError("unified manifest path/checksum drift")
    records, manifest, assignments, b0 = verify_canonical_dataset(manifest_path)
    if (
        manifest.content_hash != corpus.get("manifest_content_hash")
        or len(records) != corpus.get("record_count")
        or b0.get("verdict") != "pass"
    ):
        raise S1PreparationError("unified dataset replay drift")
    selected = _select_train_records(records, assignments, config)
    selected_identity = [
        {
            "transition_id": str(record["transition_id"]),
            "record_sha256": semantic_hash(record),
            "episode_id": str(record["episode_id"]),
            "candidate_count": len(cast(Sequence[Any], record["legal_actions"])),
        }
        for record in selected
    ]
    if (
        len(selected) != corpus.get("train_record_count")
        or semantic_hash(selected_identity) != corpus.get("selected_records_sha256")
    ):
        raise S1PreparationError("S1 train selection drift")
    handoff = _object(ready.get("smoke_handoff"), "smoke_handoff")
    handoff_directory = Path(str(handoff["directory"])).resolve()
    if _verify_checksum_directory(handoff_directory) != handoff.get("checksums_sha256"):
        raise S1PreparationError("smoke handoff checksum inventory drift")
    handoff_path = handoff_directory / "handoff.json"
    if _sha256(handoff_path) != handoff.get("handoff_sha256"):
        raise S1PreparationError("smoke handoff identity drift")
    qwen = _object(ready.get("qwen"), "qwen")
    pin = load_l2_pin()
    artifact = inspect_l2_cache(Path(str(qwen["cache_dir"])), pin)
    if artifact.to_dict() != qwen.get("artifact"):
        raise S1PreparationError("Qwen snapshot identity drift")
    smokes = _object(ready.get("engineering_smokes"), "engineering_smokes")
    for control in ("pretrained", "random"):
        evidence = _object(smokes.get(control), f"engineering_smokes.{control}")
        path = Path(str(evidence["path"])).resolve()
        if _sha256(path) != evidence.get("sha256"):
            raise S1PreparationError(f"{control} engineering smoke checksum drift")
        _verify_engineering_smoke(path, control, revision)
    if _runtime_summary() != ready.get("runtime"):
        raise S1PreparationError("Python/torch/CUDA/GPU runtime identity drift")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
        raise S1PreparationError("CUBLAS_WORKSPACE_CONFIG must be :4096:8")
    return ready, config, cast(list[dict[str, Any]], selected), assignments


def _evaluate(model: Scheme1Scorer, batches: Sequence[RankBatch]) -> dict[str, Any]:
    losses: list[float] = []
    correct = 0
    model.eval()
    with torch.no_grad():
        for batch in batches:
            scores = model(batch.state_text, batch.action_texts)
            loss = torch.nn.functional.cross_entropy(
                scores.unsqueeze(0),
                torch.tensor([batch.target_index], device=scores.device),
            )
            losses.append(float(loss.detach().cpu()))
            correct += int(int(scores.argmax().item()) == batch.target_index)
    return {
        "records": len(batches),
        "mean_listwise_nll": sum(losses) / len(losses),
        "top1": correct / len(batches),
        "finite": all(math.isfinite(value) for value in losses),
    }


def run_s1_smoke(
    *, ready_path: Path, ready_sha256: str, owner_ack: str
) -> dict[str, Any]:
    """Execute the exact prepared smoke only after an explicit owner acknowledgement."""

    if owner_ack != OWNER_ACK:
        raise S1PreparationError("exact owner acknowledgement is required")
    ready, config, selected, assignments = _verify_ready(ready_path, ready_sha256)
    output = Path(str(_object(ready["artifacts"], "artifacts")["output_directory"])).resolve()
    if output.exists():
        raise S1PreparationError(f"refusing to overwrite S1 output: {output}")
    output.mkdir(parents=True)
    seed = int(config["seed"])
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    qwen_ready = _object(ready["qwen"], "qwen")
    pin = load_l2_pin()
    backend = RealQwenBackend(
        l2_snapshot_path(Path(str(qwen_ready["cache_dir"])), pin),
        control="pretrained",
        device="cuda:0",
        feature_dtype=torch.float32,
        pin=pin,
    )
    if backend.identity.__dict__ != qwen_ready.get("pretrained_identity"):
        raise S1PreparationError("loaded Qwen identity differs from READY_TO_TRAIN")
    cache = CachingQwenBackend(backend)
    batches = build_rank_batches(
        selected,
        profile=InputProfile.STANDARD,
        serializer_version=str(config["serializer_version"]),
    )
    dev_records = [
        record
        for record in verify_canonical_dataset(
            Path(str(_object(ready["corpus"], "corpus")["manifest_path"]))
        )[0]
        if assignments[str(record["episode_id"])].split == "dev"
    ]
    dev_batches = build_rank_batches(
        dev_records,
        profile=InputProfile.STANDARD,
        serializer_version=str(config["serializer_version"]),
    )
    model = Scheme1Scorer(cache, backend.hidden_size, head="linear").to(backend.device)
    optimizer_value = _object(config["optimizer"], "optimizer")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(optimizer_value["learning_rate"]),
        weight_decay=float(optimizer_value["weight_decay"]),
    )
    trainer = V0Trainer(
        model,
        optimizer,
        grad_clip_norm=float(optimizer_value["grad_clip_norm"]),
    )
    corpus = _object(ready["corpus"], "corpus")
    identity = CheckpointIdentity(
        source_revision=str(_object(ready["source"], "source")["revision"]),
        data_manifest_hash=str(corpus["manifest_sha256"]),
        architecture_id=str(config["architecture_id"]),
        config_hash=str(_object(ready["config"], "config")["sha256"]),
        serializer_version=str(config["serializer_version"]),
        input_profile=str(config["input_profile"]),
        qwen=cache.identity,
    )
    manager = CheckpointManager()
    initial_path = Path(str(_object(ready["artifacts"], "artifacts")["initial_checkpoint"]))
    final_path = Path(str(_object(ready["artifacts"], "artifacts")["final_checkpoint"]))
    manager.save(
        initial_path,
        model=model,
        optimizer=optimizer,
        identity=identity,
        trainer_state=TrainerState(0, 0, 0, 0),
    )
    initial_dev = _evaluate(model, dev_batches)
    losses: list[float] = []
    gradients_finite = True
    for batch in batches:
        metrics = trainer.train_step(batch)
        losses.append(metrics.total_loss)
        gradients_finite = gradients_finite and all(
            parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters()
        )
    if not losses or not all(math.isfinite(loss) for loss in losses):
        raise S1PreparationError("S1 produced a missing or non-finite loss")
    if not gradients_finite:
        raise S1PreparationError("S1 produced a non-finite trainable gradient")
    if not backend.parameters_frozen() or not backend.parameter_gradients_absent():
        raise S1PreparationError("S1 touched the frozen Qwen backbone")
    final_dev = _evaluate(model, dev_batches)
    state = TrainerState(len(batches), len(batches), 0, 0)
    final_manifest = manager.save(
        final_path,
        model=model,
        optimizer=optimizer,
        identity=identity,
        trainer_state=state,
    )
    loaded = manager.load(
        final_path, model=model, optimizer=optimizer, expected_identity=identity
    )
    if loaded != state:
        raise S1PreparationError("final checkpoint state did not round-trip")
    result = {
        "schema": RESULT_SCHEMA,
        "status": "pass",
        "ready_sha256": ready_sha256,
        "source_revision": _object(ready["source"], "source")["revision"],
        "corpus_id": corpus["corpus_id"],
        "manifest_sha256": corpus["manifest_sha256"],
        "architecture_id": config["architecture_id"],
        "qwen_identity": asdict(cache.identity),
        "optimizer_steps": len(batches),
        "train": {
            "records": len(batches),
            "mean_loss": sum(losses) / len(losses),
            "minimum_loss": min(losses),
            "maximum_loss": max(losses),
            "all_finite": True,
            "all_trainable_gradients_finite": True,
        },
        "behavior_dev": {"initial": initial_dev, "final": final_dev},
        "qwen_gradient_tensor_count": 0,
        "checkpoints": {
            "initial": str(initial_path),
            "final": str(final_path),
            "final_manifest": str(final_manifest),
            "round_trip_verified": True,
        },
        "gold_opened": False,
        "scientific_claim": False,
        "non_claims": config["non_claims"],
    }
    result_path = Path(str(_object(ready["artifacts"], "artifacts")["result"]))
    result_path.write_text(canonical_json(result) + "\n", encoding="utf-8")
    return result
