"""Qwen L1 identity, metadata/tokenizer cache, and length profiling.

This module deliberately has no model-loading path.  The online operation only
requests the allow-listed metadata/tokenizer files at a pinned Hub revision;
the offline operations inspect that cache or tokenize an explicit input file.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any, cast

from ..contracts import ContractError

MODEL_ID = "Qwen/Qwen3-0.6B-Base"
MANIFEST_SCHEMA = "stpd/qwen-l1-manifest-v0"
PROFILE_SCHEMA = "stpd/qwen-token-profile-v0"
DEFAULT_PIN_PATH = Path(__file__).resolve().parents[2] / "configs/v0/qwen/qwen3-0.6b-base-l1.json"

METADATA_FILES = ("config.json", "generation_config.json", "tokenizer_config.json")
TOKENIZER_FILES = ("tokenizer.json", "vocab.json", "merges.txt")
ALLOWLISTED_FILES = METADATA_FILES + TOKENIZER_FILES
WEIGHT_SUFFIXES = (
    ".bin",
    ".ckpt",
    ".gguf",
    ".h5",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
)
WEIGHT_NAME_RE = re.compile(
    r"(?:^|/)(?:model|pytorch_model|consolidated|weights|checkpoint).*"
    r"(?:\.bin|\.ckpt|\.gguf|\.h5|\.onnx|\.pt|\.pth|\.safetensors)$",
    re.IGNORECASE,
)
PROFILE_IDS = (
    "stpd-combat-v0-lite",
    "stpd-combat-v0-standard",
    "stpd-combat-v0-full",
)
DECISION_FAMILIES = ("turn_action", "card_selection", "card_choice")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class QwenL1Error(ContractError):
    """Raised when an L1 identity, cache, or profile fails closed."""


class QwenL1WeightError(QwenL1Error):
    """Raised when a local cache contains a model-weight artifact."""


@dataclass(frozen=True)
class PinnedFile:
    """Content pin for one allow-listed Hub file."""

    name: str
    kind: str
    size_bytes: int
    sha256: str

    def validate(self) -> None:
        if self.name not in ALLOWLISTED_FILES:
            raise QwenL1Error(f"file is not allow-listed: {self.name}")
        if self.kind not in {"metadata", "tokenizer"}:
            raise QwenL1Error(f"invalid file kind for {self.name}: {self.kind}")
        if self.size_bytes <= 0:
            raise QwenL1Error(f"file size must be positive: {self.name}")
        if not SHA256_RE.fullmatch(self.sha256):
            raise QwenL1Error(f"invalid SHA-256 for {self.name}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "name": self.name,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class SpecialToken:
    """A special token and its tokenizer-config roles."""

    content: str
    token_id: int
    roles: tuple[str, ...]

    def validate(self) -> None:
        if not self.content:
            raise QwenL1Error("special token content must be non-empty")
        if self.token_id < 0:
            raise QwenL1Error(f"special token id must be non-negative: {self.content}")
        if not self.roles:
            raise QwenL1Error(f"special token has no role: {self.content}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "content": self.content,
            "id": self.token_id,
            "roles": list(self.roles),
        }


@dataclass(frozen=True)
class QwenL1Pin:
    """Immutable model/revision and content expectations loaded from config."""

    model_id: str
    repo_revision: str
    files: tuple[PinnedFile, ...]
    special_tokens: tuple[SpecialToken, ...]
    special_tokens_sha256: str
    config_expectations: Mapping[str, Any]
    profiles: Mapping[str, Mapping[str, Any]]
    p95_limit: int
    hard_limit: int

    def validate(self) -> None:
        if not self.model_id.strip():
            raise QwenL1Error("model_id must be non-empty")
        if not REVISION_RE.fullmatch(self.repo_revision):
            raise QwenL1Error("repo_revision must be a 40-character immutable SHA")
        if tuple(file.name for file in self.files) != ALLOWLISTED_FILES:
            raise QwenL1Error("pin must contain the exact metadata/tokenizer allowlist")
        for file in self.files:
            file.validate()
        if self.p95_limit <= 0 or self.hard_limit <= 0 or self.p95_limit > self.hard_limit:
            raise QwenL1Error("invalid token length thresholds")
        if tuple(profile for profile in self.profiles) != PROFILE_IDS:
            raise QwenL1Error("pin must define all three STPD input profiles in order")
        for profile_id in PROFILE_IDS:
            families = tuple(self.profiles[profile_id].get("families", ()))
            if families != DECISION_FAMILIES:
                raise QwenL1Error(f"{profile_id} must define all decision families")
        token_ids = set()
        for token in self.special_tokens:
            token.validate()
            if token.token_id in token_ids:
                raise QwenL1Error(f"duplicate special token id: {token.token_id}")
            token_ids.add(token.token_id)
        if special_tokens_sha256(self.special_tokens) != self.special_tokens_sha256:
            raise QwenL1Error("special token digest does not match the pin")

    @property
    def file_by_name(self) -> dict[str, PinnedFile]:
        return {file.name: file for file in self.files}

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "stpd/qwen-l1-config-v0",
            "model_id": self.model_id,
            "repo_revision": self.repo_revision,
            "files": [file.to_dict() for file in self.files],
            "special_tokens": [token.to_dict() for token in self.special_tokens],
            "special_tokens_sha256": self.special_tokens_sha256,
            "config_expectations": dict(self.config_expectations),
            "profiles": {profile: dict(value) for profile, value in self.profiles.items()},
            "thresholds": {
                "p95_max_tokens": self.p95_limit,
                "hard_max_tokens": self.hard_limit,
                "silent_truncation": False,
            },
            "cache_policy": {
                "mode": "metadata_tokenizer_only",
                "allowed_files": list(ALLOWLISTED_FILES),
                "weight_files": "reject_if_local_and_never_download",
            },
        }


@dataclass(frozen=True)
class QwenL1Artifact:
    """Validated local cache evidence; it contains no model weights."""

    model_id: str
    repo_revision: str
    files: tuple[PinnedFile, ...]
    special_tokens: tuple[SpecialToken, ...]
    special_tokens_sha256: str
    rejected_remote_files: tuple[str, ...]
    weights_downloaded: bool = False

    def validate(self) -> None:
        if self.weights_downloaded:
            raise QwenL1WeightError("an L1 artifact cannot contain downloaded weights")
        if any(is_weight_file(file.name) for file in self.files):
            raise QwenL1WeightError("weight file present in L1 artifact")
        for file in self.files:
            file.validate()
        for token in self.special_tokens:
            token.validate()
        if special_tokens_sha256(self.special_tokens) != self.special_tokens_sha256:
            raise QwenL1Error("artifact special-token digest is invalid")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": MANIFEST_SCHEMA,
            "model_id": self.model_id,
            "repo_revision": self.repo_revision,
            "cache_mode": "metadata_tokenizer_only",
            "weights_downloaded": False,
            "files": [file.to_dict() for file in self.files],
            "special_tokens": [token.to_dict() for token in self.special_tokens],
            "special_tokens_sha256": self.special_tokens_sha256,
            "rejected_remote_weight_files": list(self.rejected_remote_files),
        }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_bytes(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def special_tokens_sha256(tokens: Sequence[SpecialToken]) -> str:
    """Hash the ordered special-token contract, not tokenizer implementation internals."""

    return _sha256_bytes([token.to_dict() for token in tokens])


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QwenL1Error(f"cannot read JSON metadata: {path}") from exc
    if not isinstance(value, dict):
        raise QwenL1Error(f"JSON metadata must be an object: {path}")
    return cast(dict[str, Any], value)


def _special_token_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping) and isinstance(value.get("content"), str):
        return cast(str, value["content"])
    return None


def extract_special_tokens(snapshot: Path) -> tuple[SpecialToken, ...]:
    """Extract special tokens from tokenizer config plus tokenizer JSON."""

    tokenizer_config = _load_json(snapshot / "tokenizer_config.json")
    tokenizer_json = _load_json(snapshot / "tokenizer.json")
    roles: dict[str, set[str]] = defaultdict(set)
    for role in ("bos_token", "eos_token", "unk_token", "sep_token", "pad_token"):
        content = _special_token_text(tokenizer_config.get(role))
        if content is not None:
            roles[content].add(role)
    for value in tokenizer_config.get("additional_special_tokens", []):
        content = _special_token_text(value)
        if content is not None:
            roles[content].add("additional_special_tokens")

    result: list[SpecialToken] = []
    for entry in tokenizer_json.get("added_tokens", []):
        if not isinstance(entry, Mapping) or not entry.get("special"):
            continue
        content = entry.get("content")
        token_id = entry.get("id")
        if not isinstance(content, str) or not isinstance(token_id, int):
            raise QwenL1Error("tokenizer.json contains an invalid special-token entry")
        result.append(
            SpecialToken(content, token_id, tuple(sorted(roles.get(content, {"special"}))))
        )
    if not result:
        raise QwenL1Error("tokenizer.json contains no special tokens")
    return tuple(result)


def load_pin(path: Path | None = None) -> QwenL1Pin:
    """Load and validate the checked-in immutable L1 pin manifest."""

    value = _load_json(path or DEFAULT_PIN_PATH)
    try:
        files = tuple(
            PinnedFile(
                name=str(entry["name"]),
                kind=str(entry["kind"]),
                size_bytes=int(entry["size_bytes"]),
                sha256=str(entry["sha256"]),
            )
            for entry in value["files"]
        )
        tokens = tuple(
            SpecialToken(
                content=str(entry["content"]),
                token_id=int(entry["id"]),
                roles=tuple(str(role) for role in entry["roles"]),
            )
            for entry in value["special_tokens"]
        )
        thresholds = value["thresholds"]
        pin = QwenL1Pin(
            model_id=str(value["model_id"]),
            repo_revision=str(value["repo_revision"]),
            files=files,
            special_tokens=tokens,
            special_tokens_sha256=str(value["special_tokens_sha256"]),
            config_expectations=cast(Mapping[str, Any], value["config_expectations"]),
            profiles=cast(Mapping[str, Mapping[str, Any]], value["profiles"]),
            p95_limit=int(thresholds["p95_max_tokens"]),
            hard_limit=int(thresholds["hard_max_tokens"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise QwenL1Error(f"invalid Qwen L1 pin: {path or DEFAULT_PIN_PATH}") from exc
    pin.validate()
    return pin


def is_weight_file(name: str) -> bool:
    """Return whether a path is a model-weight artifact that L1 must reject."""

    lower = name.lower()
    return lower.endswith(WEIGHT_SUFFIXES) or bool(WEIGHT_NAME_RE.search(name))


def _snapshot_path(cache_dir: Path, pin: QwenL1Pin) -> Path:
    safe_model_id = pin.model_id.replace("/", "--")
    return cache_dir.expanduser() / f"models--{safe_model_id}" / "snapshots" / pin.repo_revision


def cache_snapshot_path(cache_dir: Path, pin: QwenL1Pin | None = None) -> Path:
    """Return the deterministic metadata/tokenizer-only snapshot path."""

    return _snapshot_path(cache_dir, pin or load_pin())


def _validate_config(snapshot: Path, pin: QwenL1Pin) -> None:
    config = _load_json(snapshot / "config.json")
    for key, expected in pin.config_expectations.items():
        if config.get(key) != expected:
            raise QwenL1Error(
                f"config expectation failed for {key}: expected {expected!r}, "
                f"got {config.get(key)!r}"
            )


def _validate_snapshot(
    snapshot: Path,
    pin: QwenL1Pin,
    rejected_remote_files: Sequence[str] = (),
) -> QwenL1Artifact:
    if not snapshot.is_dir():
        raise QwenL1Error(f"L1 cache snapshot does not exist: {snapshot}")
    paths = {
        path.relative_to(snapshot).as_posix(): path
        for path in snapshot.rglob("*")
        if path.is_file()
    }
    weight_files = sorted(name for name in paths if is_weight_file(name))
    if weight_files:
        raise QwenL1WeightError(
            "weight files are forbidden in metadata/tokenizer-only cache: "
            + ", ".join(weight_files)
        )
    unexpected = sorted(set(paths) - set(ALLOWLISTED_FILES))
    if unexpected:
        raise QwenL1Error("unexpected files in L1 cache: " + ", ".join(unexpected))
    missing = sorted(set(ALLOWLISTED_FILES) - set(paths))
    if missing:
        raise QwenL1Error("missing allow-listed files in L1 cache: " + ", ".join(missing))

    actual: list[PinnedFile] = []
    for expected in pin.files:
        path = paths[expected.name]
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != expected.size_bytes or digest != expected.sha256:
            raise QwenL1Error(
                f"content pin failed for {expected.name}: "
                f"expected {expected.size_bytes}/{expected.sha256}, got {size}/{digest}"
            )
        actual.append(PinnedFile(expected.name, expected.kind, size, digest))

    _validate_config(snapshot, pin)
    actual_special_tokens = extract_special_tokens(snapshot)
    if actual_special_tokens != pin.special_tokens:
        raise QwenL1Error("special-token entries do not match the checked-in pin")
    digest = special_tokens_sha256(actual_special_tokens)
    if digest != pin.special_tokens_sha256:
        raise QwenL1Error("special-token content digest failed")
    artifact = QwenL1Artifact(
        model_id=pin.model_id,
        repo_revision=pin.repo_revision,
        files=tuple(actual),
        special_tokens=actual_special_tokens,
        special_tokens_sha256=digest,
        rejected_remote_files=tuple(sorted(rejected_remote_files)),
    )
    artifact.validate()
    return artifact


def _manifest_path(cache_dir: Path, pin: QwenL1Pin) -> Path:
    safe_model_id = pin.model_id.replace("/", "--")
    return cache_dir.expanduser() / "manifests" / f"{safe_model_id}-{pin.repo_revision}.json"


def _write_manifest(cache_dir: Path, pin: QwenL1Pin, artifact: QwenL1Artifact) -> Path:
    path = _manifest_path(cache_dir, pin)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def inspect_cache(cache_dir: Path, pin: QwenL1Pin | None = None) -> QwenL1Artifact:
    """Validate an existing cache without network access or tokenizer downloads."""

    resolved_pin = pin or load_pin()
    manifest = _manifest_path(cache_dir, resolved_pin)
    rejected_remote_files: tuple[str, ...] = ()
    if manifest.is_file():
        manifest_value = _load_json(manifest)
        if manifest_value.get("schema") != MANIFEST_SCHEMA:
            raise QwenL1Error(f"invalid L1 manifest schema: {manifest}")
        rejected = manifest_value.get("rejected_remote_weight_files", [])
        if not isinstance(rejected, list) or any(
            not isinstance(name, str) or not is_weight_file(name) for name in rejected
        ):
            raise QwenL1Error(f"invalid rejected weight-file evidence: {manifest}")
        rejected_remote_files = tuple(sorted(rejected))
    return _validate_snapshot(
        _snapshot_path(cache_dir, resolved_pin),
        resolved_pin,
        rejected_remote_files,
    )


def _hub_api(token: str | None = None) -> Any:
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise QwenL1Error("online Qwen L1 fetch requires the optional 'l1' dependencies") from exc
    return HfApi(token=token)


def discover_repo_revision(
    model_id: str = MODEL_ID,
    revision: str = "main",
    *,
    token: str | None = None,
    pinned_revision: str | None = None,
) -> dict[str, Any]:
    """Discover the current Hub commit; this operation never downloads files."""

    info = _hub_api(token).model_info(model_id, revision=revision)
    repo_revision = getattr(info, "sha", None)
    if not isinstance(repo_revision, str) or not REVISION_RE.fullmatch(repo_revision):
        raise QwenL1Error("Hub did not return an immutable 40-character repository SHA")
    siblings = info.siblings or ()
    files = tuple(sorted(str(item.rfilename) for item in siblings))
    return {
        "schema": "stpd/qwen-l1-discovery-v0",
        "model_id": model_id,
        "requested_revision": revision,
        "repo_revision": repo_revision,
        "files": list(files),
        "remote_weight_files": [name for name in files if is_weight_file(name)],
        "matches_pinned_revision": pinned_revision is None or repo_revision == pinned_revision,
    }


def fetch_metadata_tokenizer(
    cache_dir: Path,
    pin: QwenL1Pin | None = None,
    *,
    token: str | None = None,
) -> QwenL1Artifact:
    """Fetch only pinned metadata/tokenizer files and atomically validate the cache."""

    resolved_pin = pin or load_pin()
    target = _snapshot_path(cache_dir, resolved_pin)
    if target.exists():
        return inspect_cache(cache_dir, resolved_pin)

    api = _hub_api(token)
    try:
        remote_files = tuple(
            sorted(
                str(name)
                for name in api.list_repo_files(
                    resolved_pin.model_id,
                    revision=resolved_pin.repo_revision,
                )
            )
        )
    except Exception as exc:
        raise QwenL1Error("could not list the pinned Qwen repository revision") from exc
    missing_remote = sorted(set(ALLOWLISTED_FILES) - set(remote_files))
    if missing_remote:
        raise QwenL1Error(
            "pinned repository is missing allow-listed files: " + ", ".join(missing_remote)
        )
    rejected = tuple(name for name in remote_files if is_weight_file(name))

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{resolved_pin.repo_revision}-", dir=target.parent))
    try:
        for file in resolved_pin.files:
            try:
                source = Path(
                    _download_allowlisted_file(
                        resolved_pin.model_id,
                        file.name,
                        resolved_pin.repo_revision,
                        token,
                    )
                )
            except Exception as exc:
                raise QwenL1Error(f"could not fetch allow-listed file: {file.name}") from exc
            shutil.copy2(source, staging / file.name)
        artifact = _validate_snapshot(staging, resolved_pin, rejected)
        try:
            staging.rename(target)
        except FileExistsError:
            shutil.rmtree(staging)
            artifact = inspect_cache(cache_dir, resolved_pin)
        _write_manifest(cache_dir, resolved_pin, artifact)
        return artifact
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _download_allowlisted_file(
    model_id: str,
    filename: str,
    revision: str,
    token: str | None,
) -> str:
    from huggingface_hub import hf_hub_download

    return str(hf_hub_download(model_id, filename, revision=revision, token=token))


def _nearest_rank(values: Sequence[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * quantile) - 1)]


def token_length_summary(
    lengths: Sequence[int],
    *,
    p95_limit: int = 4096,
    hard_limit: int = 8192,
) -> dict[str, Any]:
    """Summarize lengths with a documented nearest-rank quantile and no truncation."""

    if not lengths:
        return {
            "sample_count": 0,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
            "p95_limit": p95_limit,
            "hard_limit": hard_limit,
            "status": "not_exercised",
            "violations": [],
        }
    if any(length < 0 for length in lengths):
        raise QwenL1Error("token lengths cannot be negative")
    p95 = _nearest_rank(lengths, 0.95)
    maximum = max(lengths)
    violations: list[str] = []
    if p95 > p95_limit:
        violations.append(f"p95={p95} exceeds limit={p95_limit}")
    if maximum > hard_limit:
        violations.append(f"max={maximum} exceeds hard limit={hard_limit}")
    return {
        "sample_count": len(lengths),
        "p50": _nearest_rank(lengths, 0.50),
        "p90": _nearest_rank(lengths, 0.90),
        "p95": p95,
        "p99": _nearest_rank(lengths, 0.99),
        "max": maximum,
        "p95_limit": p95_limit,
        "hard_limit": hard_limit,
        "status": "pass" if not violations else "fail",
        "violations": violations,
    }


def _load_tokenizer(tokenizer_path: Path) -> Any:
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise QwenL1Error("token profiling requires the optional 'l1' dependencies") from exc
    try:
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        tokenizer.no_truncation()
        return tokenizer
    except Exception as exc:
        raise QwenL1Error(f"could not load tokenizer without truncation: {tokenizer_path}") from exc


def _profile_key(profile: str, family: str) -> str:
    return f"{profile}/{family}"


def profile_records(
    tokenizer_path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    pin: QwenL1Pin | None = None,
) -> dict[str, Any]:
    """Profile JSON-like samples grouped by input profile and decision family."""

    resolved_pin = pin
    p95_limit = resolved_pin.p95_limit if resolved_pin else 4096
    hard_limit = resolved_pin.hard_limit if resolved_pin else 8192
    tokenizer = _load_tokenizer(tokenizer_path)
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    sample_count = 0
    for index, record in enumerate(records, start=1):
        profile = record.get("profile")
        family = record.get("family")
        text = record.get("text")
        if not isinstance(profile, str) or not profile.strip():
            raise QwenL1Error(f"sample {index} has no non-empty profile")
        if not isinstance(family, str) or not family.strip():
            raise QwenL1Error(f"sample {index} has no non-empty family")
        if not isinstance(text, str):
            raise QwenL1Error(f"sample {index} has no string text")
        if resolved_pin and profile not in resolved_pin.profiles:
            raise QwenL1Error(f"sample {index} has unknown profile: {profile}")
        if family not in DECISION_FAMILIES:
            raise QwenL1Error(f"sample {index} has unknown decision family: {family}")
        encoding = tokenizer.encode(text, add_special_tokens=False)
        groups[(profile, family)].append(len(encoding.ids))
        sample_count += 1

    expected_groups = {
        (profile, family)
        for profile in (
            resolved_pin.profiles if resolved_pin else sorted({key[0] for key in groups})
        )
        for family in (
            resolved_pin.profiles[profile].get("families", DECISION_FAMILIES)
            if resolved_pin
            else sorted({key[1] for key in groups if key[0] == profile})
        )
    }
    all_groups = expected_groups | set(groups)
    by_profile: dict[str, dict[str, Any]] = {}
    for profile in sorted({key[0] for key in all_groups}):
        family_reports = {
            family: token_length_summary(
                groups.get((profile, family), ()),
                p95_limit=p95_limit,
                hard_limit=hard_limit,
            )
            for family in sorted(key[1] for key in all_groups if key[0] == profile)
        }
        profile_lengths = [
            length
            for (group_profile, _), lengths in groups.items()
            if group_profile == profile
            for length in lengths
        ]
        by_profile[profile] = {
            "summary": token_length_summary(
                profile_lengths,
                p95_limit=p95_limit,
                hard_limit=hard_limit,
            ),
            "by_family": family_reports,
        }

    by_family: dict[str, dict[str, Any]] = {}
    for family in sorted({key[1] for key in all_groups}):
        family_lengths = [
            length
            for (_, group_family), lengths in groups.items()
            if group_family == family
            for length in lengths
        ]
        by_family[family] = token_length_summary(
            family_lengths,
            p95_limit=p95_limit,
            hard_limit=hard_limit,
        )

    violations: list[str] = []
    for profile, report in by_profile.items():
        for family, summary in report["by_family"].items():
            key = _profile_key(profile, family)
            if summary["status"] == "not_exercised":
                violations.append(f"missing profile/family samples: {key}")
            violations.extend(f"{key}: {value}" for value in summary["violations"])
    return {
        "schema": PROFILE_SCHEMA,
        "tokenizer_sha256": sha256_file(tokenizer_path),
        "tokenizer_path_name": tokenizer_path.name,
        "sample_count": sample_count,
        "truncation": {"enabled": False, "policy": "reject_over_hard_limit"},
        "thresholds": {"p95_max_tokens": p95_limit, "hard_max_tokens": hard_limit},
        "by_profile": by_profile,
        "by_family": by_family,
        "passed": sample_count > 0 and not violations,
        "violations": violations,
    }


def profile_jsonl(
    tokenizer_path: Path,
    input_path: Path,
    *,
    pin: QwenL1Pin | None = None,
) -> dict[str, Any]:
    """Profile an offline UTF-8 JSONL file; network access is never attempted."""

    records: list[Mapping[str, Any]] = []
    try:
        lines = input_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise QwenL1Error(f"cannot read profile input: {input_path}") from exc
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QwenL1Error(f"invalid JSONL at line {index}: {input_path}") from exc
        if not isinstance(value, Mapping):
            raise QwenL1Error(f"JSONL line {index} must be an object")
        records.append(value)
    return profile_records(tokenizer_path, records, pin=pin)


def discovery_timestamp() -> str:
    """Return an explicit UTC timestamp for human-readable online evidence."""

    return datetime.now(UTC).replace(microsecond=0).isoformat()
