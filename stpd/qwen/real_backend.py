"""Full-weight frozen Qwen backend and checksum-bound in-memory feature cache."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, cast

import torch
from torch import Tensor

from ..contracts import QwenIdentity
from .l2 import QwenL2Error, QwenL2Pin, inspect_l2_snapshot, load_l2_pin

Control = Literal["pretrained", "random"]
BackendValue = Tensor | tuple[Tensor, Tensor]


def _masked_mean(hidden: Tensor, mask: Tensor) -> Tensor:
    if hidden.ndim != 3 or mask.ndim != 2 or hidden.shape[:2] != mask.shape:
        raise QwenL2Error("masked mean requires [batch,tokens,hidden] and [batch,tokens]")
    weights = mask.to(dtype=hidden.dtype).unsqueeze(-1)
    denominator = weights.sum(dim=1)
    if bool((denominator == 0).any()):
        raise QwenL2Error("cannot pool an empty token sequence")
    return (hidden * weights).sum(dim=1) / denominator


def _parameter_sha256(model: Any) -> str:
    """Hash exact parameter names, shapes, dtypes, and bytes while the model is on CPU."""

    digest = hashlib.sha256()
    for name, parameter in model.named_parameters():
        tensor = parameter.detach().contiguous().cpu()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(b"\0")
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
        digest.update(b"\0")
    return digest.hexdigest()


class RealQwenBackend:
    """Transformers/PyTorch implementation of the frozen STPD QwenBackend port."""

    def __init__(
        self,
        snapshot: Path,
        *,
        control: Control,
        device: str = "cuda:0",
        random_seed: int | None = None,
        micro_batch_size: int = 1,
        feature_dtype: torch.dtype = torch.float32,
        pin: QwenL2Pin | None = None,
    ) -> None:
        if control not in ("pretrained", "random"):
            raise QwenL2Error("Qwen control must be pretrained or random")
        if (control == "random") != (random_seed is not None):
            raise QwenL2Error("random control requires a seed; pretrained control forbids one")
        if micro_batch_size <= 0:
            raise QwenL2Error("micro_batch_size must be positive")
        if not device.startswith("cuda:"):
            raise QwenL2Error("scientific Qwen L2 admission requires an explicit CUDA device")
        if not torch.cuda.is_available():
            raise QwenL2Error("PyTorch cannot admit CUDA on this machine")
        device_index = torch.device(device).index
        if device_index is None or device_index >= torch.cuda.device_count():
            raise QwenL2Error(f"CUDA device is unavailable: {device}")
        if not torch.cuda.is_bf16_supported():
            raise QwenL2Error("the selected CUDA runtime does not support bfloat16")
        if feature_dtype not in (torch.float32, torch.bfloat16):
            raise QwenL2Error("feature_dtype must be float32 or bfloat16")

        self.pin = pin or load_l2_pin()
        self.artifact = inspect_l2_snapshot(snapshot, self.pin)
        self.snapshot = snapshot.expanduser().resolve()
        self.control = control
        self.device = torch.device(device)
        self.random_seed = random_seed
        self.micro_batch_size = micro_batch_size
        self.feature_dtype = feature_dtype
        self.load_seconds = 0.0

        try:
            import transformers
            from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise QwenL2Error("RealQwenBackend requires the optional L2 dependencies") from exc

        config = AutoConfig.from_pretrained(str(self.snapshot), local_files_only=True)
        architectures = tuple(getattr(config, "architectures", ()) or ())
        if architectures != (self.pin.backend.architecture,):
            raise QwenL2Error(
                f"loaded architecture mismatch: expected {self.pin.backend.architecture}, "
                f"got {architectures}"
            )
        tokenizer = AutoTokenizer.from_pretrained(
            str(self.snapshot),
            local_files_only=True,
            use_fast=True,
        )
        expected_pad = next(
            token.token_id
            for token in self.pin.l1.special_tokens
            if "pad_token" in token.roles
        )
        if tokenizer.pad_token_id != expected_pad or tokenizer.eos_token_id != expected_pad:
            raise QwenL2Error("loaded tokenizer pad/eos identity does not match the pin")
        tokenizer.padding_side = "right"

        started = perf_counter()
        if control == "pretrained":
            model = AutoModelForCausalLM.from_pretrained(
                str(self.snapshot),
                config=config,
                local_files_only=True,
                dtype=torch.bfloat16,
                attn_implementation=self.pin.backend.attention_implementation,
            )
        else:
            assert random_seed is not None
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(random_seed)
                model = AutoModelForCausalLM.from_config(
                    config,
                    attn_implementation=self.pin.backend.attention_implementation,
                )
            model.to(dtype=torch.bfloat16)
        initialization_sha256 = _parameter_sha256(model) if control == "random" else None
        model = cast(Any, model)
        model.to(self.device)
        model.eval()
        model.requires_grad_(False)
        torch.cuda.synchronize(self.device)
        self.load_seconds = perf_counter() - started

        if type(model).__name__ != self.pin.backend.architecture:
            raise QwenL2Error(
                f"loaded model class mismatch: expected {self.pin.backend.architecture}, "
                f"got {type(model).__name__}"
            )
        parameters = tuple(model.parameters())
        if not parameters or any(parameter.requires_grad for parameter in parameters):
            raise QwenL2Error("Qwen parameters are not fully frozen")
        if any(
            parameter.is_floating_point() and parameter.dtype != torch.bfloat16
            for parameter in parameters
        ):
            raise QwenL2Error("Qwen floating parameters are not uniformly bfloat16")
        if any(parameter.device != self.device for parameter in parameters):
            raise QwenL2Error("Qwen parameters are not all on the admitted CUDA device")
        base_model = getattr(model, "model", None)
        if base_model is None:
            raise QwenL2Error("Qwen causal LM does not expose its frozen base model")

        self._transformers = transformers
        self._tokenizer = tokenizer
        self._model = model
        self._base_model = base_model
        self.hidden_size = int(config.hidden_size)
        self.parameter_count = sum(parameter.numel() for parameter in parameters)
        self.identity = QwenIdentity(
            model_id=self.pin.model_id,
            model_revision=self.pin.repo_revision,
            tokenizer_revision=self.pin.repo_revision,
            dtype="bfloat16",
            device=str(self.device),
            frozen=True,
            control=control,
            config_sha256=self.pin.l1.config_sha256,
            tokenizer_sha256=self.pin.l1.tokenizer_bundle_sha256,
            weights_sha256=(
                self.artifact.weights_sha256 if control == "pretrained" else None
            ),
            random_seed=random_seed,
            initialization_sha256=initialization_sha256,
            attention_implementation=self.pin.backend.attention_implementation,
            feature_dtype=str(feature_dtype).removeprefix("torch."),
            cache_mode="none",
            torch_version=torch.__version__,
            transformers_version=transformers.__version__,
        )
        self.identity.validate_scientific_v0()

    def _tokenize(self, texts: Sequence[str]) -> tuple[Tensor, Tensor]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise QwenL2Error("Qwen encoding requires a non-empty batch of non-empty texts")
        encoded = self._tokenizer(
            list(texts),
            add_special_tokens=self.pin.backend.add_special_tokens,
            padding=True,
            truncation=False,
            return_attention_mask=True,
            return_tensors="pt",
        )
        input_ids = cast(Tensor, encoded["input_ids"])
        attention_mask = cast(Tensor, encoded["attention_mask"]).to(dtype=torch.bool)
        lengths = attention_mask.sum(dim=1)
        if bool((lengths == 0).any()):
            raise QwenL2Error("Qwen tokenizer produced an empty sequence")
        observed_max = int(lengths.max())
        if observed_max > self.pin.l1.hard_limit:
            raise QwenL2Error(
                f"Qwen input has {observed_max} tokens; hard limit is {self.pin.l1.hard_limit}"
            )
        return input_ids.to(self.device), attention_mask.to(self.device)

    def token_lengths(self, texts: Sequence[str]) -> list[int]:
        """Return exact untruncated token counts under the pinned tokenizer contract."""

        _, mask = self._tokenize(texts)
        return [int(value) for value in mask.sum(dim=1).cpu().tolist()]

    def _hidden_chunk(self, texts: Sequence[str]) -> tuple[Tensor, Tensor]:
        input_ids, mask = self._tokenize(texts)
        with torch.inference_mode():
            output = self._base_model(
                input_ids=input_ids,
                attention_mask=mask,
                use_cache=self.pin.backend.use_cache,
                return_dict=True,
            )
            hidden = cast(Tensor, output.last_hidden_state).detach()
        hidden = hidden.clone().to(dtype=self.feature_dtype)
        if (
            hidden.ndim != 3
            or hidden.shape[:2] != mask.shape
            or hidden.shape[2] != self.hidden_size
        ):
            raise QwenL2Error("Qwen hidden-state output violates the pinned tensor contract")
        return hidden, mask

    def _hidden(self, texts: Sequence[str]) -> tuple[Tensor, Tensor]:
        hidden_chunks: list[Tensor] = []
        mask_chunks: list[Tensor] = []
        for start in range(0, len(texts), self.micro_batch_size):
            hidden, mask = self._hidden_chunk(texts[start : start + self.micro_batch_size])
            hidden_chunks.append(hidden)
            mask_chunks.append(mask)
        max_tokens = max(chunk.shape[1] for chunk in hidden_chunks)
        padded_hidden: list[Tensor] = []
        padded_masks: list[Tensor] = []
        for hidden, mask in zip(hidden_chunks, mask_chunks, strict=True):
            missing = max_tokens - hidden.shape[1]
            if missing:
                hidden = torch.nn.functional.pad(hidden, (0, 0, 0, missing))
                mask = torch.nn.functional.pad(mask, (0, missing))
            padded_hidden.append(hidden)
            padded_masks.append(mask)
        return torch.cat(padded_hidden, dim=0), torch.cat(padded_masks, dim=0)

    def encode_joint(self, state_texts: Sequence[str], action_texts: Sequence[str]) -> Tensor:
        if len(state_texts) != len(action_texts) or not state_texts:
            raise QwenL2Error("joint state/action batches must be non-empty and equally sized")
        joint = [
            f"{state}\n{action}"
            for state, action in zip(state_texts, action_texts, strict=True)
        ]
        hidden, mask = self._hidden(joint)
        return _masked_mean(hidden, mask)

    def encode_state(
        self,
        state_texts: Sequence[str],
        *,
        return_sequence: bool,
    ) -> Tensor | tuple[Tensor, Tensor]:
        hidden, mask = self._hidden(state_texts)
        if return_sequence:
            return hidden, mask
        return _masked_mean(hidden, mask)

    def embed_action_tokens(self, action_texts: Sequence[str]) -> tuple[Tensor, Tensor]:
        input_ids, mask = self._tokenize(action_texts)
        with torch.inference_mode():
            hidden = self._model.get_input_embeddings()(input_ids).detach()
        hidden = hidden.clone().to(dtype=self.feature_dtype)
        if hidden.shape[:2] != mask.shape or hidden.shape[2] != self.hidden_size:
            raise QwenL2Error("Qwen input embeddings violate the pinned tensor contract")
        return hidden, mask

    def parameters_frozen(self) -> bool:
        return all(not parameter.requires_grad for parameter in self._model.parameters())

    def parameter_gradients_absent(self) -> bool:
        return all(parameter.grad is None for parameter in self._model.parameters())

    def runtime_summary(self) -> dict[str, Any]:
        properties = torch.cuda.get_device_properties(self.device)
        return {
            "identity": self.identity.__dict__,
            "artifact": self.artifact.to_dict(),
            "parameter_count": self.parameter_count,
            "hidden_size": self.hidden_size,
            "micro_batch_size": self.micro_batch_size,
            "load_seconds": self.load_seconds,
            "gpu": {
                "name": properties.name,
                "total_memory_bytes": properties.total_memory,
                "compute_capability": f"{properties.major}.{properties.minor}",
            },
        }


class CachingQwenBackend:
    """Checksum-keyed CPU memory cache for profiling immutable frozen features."""

    def __init__(self, backend: RealQwenBackend) -> None:
        self.backend = backend
        self.identity = replace(backend.identity, cache_mode="memory-cpu-v0")
        self.identity.validate_scientific_v0()
        self._values: dict[str, BackendValue] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def _key(self, operation: str, payload: Any) -> str:
        value = {
            "schema": "stpd/qwen-feature-cache-key-v0",
            "identity": self.identity.__dict__,
            "operation": operation,
            "payload": payload,
        }
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _cpu(value: BackendValue) -> BackendValue:
        if isinstance(value, tuple):
            return tuple(item.detach().cpu().clone() for item in value)  # type: ignore[return-value]
        return value.detach().cpu().clone()

    def _device(self, value: BackendValue) -> BackendValue:
        if isinstance(value, tuple):
            return tuple(item.to(self.backend.device).clone() for item in value)  # type: ignore[return-value]
        return value.to(self.backend.device).clone()

    @staticmethod
    def _describe(value: BackendValue) -> dict[str, Any]:
        tensors = value if isinstance(value, tuple) else (value,)
        return {
            "shapes": [list(tensor.shape) for tensor in tensors],
            "dtypes": [str(tensor.dtype).removeprefix("torch.") for tensor in tensors],
            "bytes": sum(tensor.numel() * tensor.element_size() for tensor in tensors),
        }

    def _cached(self, key: str, producer: Any) -> BackendValue:
        if key not in self._values:
            value = cast(BackendValue, producer())
            self._values[key] = self._cpu(value)
            self._metadata[key] = self._describe(self._values[key])
        return self._device(self._values[key])

    def encode_joint(self, state_texts: Sequence[str], action_texts: Sequence[str]) -> Tensor:
        payload = {"states": list(state_texts), "actions": list(action_texts)}
        key = self._key("encode_joint", payload)
        return cast(
            Tensor,
            self._cached(key, lambda: self.backend.encode_joint(state_texts, action_texts)),
        )

    def encode_state(
        self,
        state_texts: Sequence[str],
        *,
        return_sequence: bool,
    ) -> Tensor | tuple[Tensor, Tensor]:
        payload = {"states": list(state_texts), "return_sequence": return_sequence}
        key = self._key("encode_state", payload)
        return self._cached(
            key,
            lambda: self.backend.encode_state(state_texts, return_sequence=return_sequence),
        )

    def embed_action_tokens(self, action_texts: Sequence[str]) -> tuple[Tensor, Tensor]:
        payload = {"actions": list(action_texts)}
        key = self._key("embed_action_tokens", payload)
        return cast(
            tuple[Tensor, Tensor],
            self._cached(key, lambda: self.backend.embed_action_tokens(action_texts)),
        )

    def manifest(self) -> dict[str, Any]:
        entries = [
            {"key_sha256": key, **self._metadata[key]}
            for key in sorted(self._metadata)
        ]
        encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            "schema": "stpd/qwen-memory-cache-manifest-v0",
            "identity": self.identity.__dict__,
            "entry_count": len(entries),
            "total_bytes": sum(int(entry["bytes"]) for entry in entries),
            "entries": entries,
            "entries_sha256": hashlib.sha256(encoded).hexdigest(),
        }
