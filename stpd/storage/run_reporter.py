"""Object-store-backed run events and immutable, conditional final-result selection."""

from __future__ import annotations

from ..artifact_contracts import Manifest
from ..json_boundary import BoundaryError, decode_json, digest, json_bytes, object_fields
from .blobs import BlobStore, StoreError
from .store import ArtifactStore


class ObjectStoreRunReporter:
    def __init__(self, store: ArtifactStore, slots: BlobStore) -> None:
        self.store = store
        self.slots = slots

    def emit(self, event: Manifest) -> str:
        if (
            event.kind != "run_event"
            or event.parameters.value().get("schema") != "stpd/run-event-v1"
        ):
            raise BoundaryError("reporter", "unsupported_event")
        run_id = event.parent("run")
        self.store.publish(event)
        self.slots.put_if_absent(f"run-events/{run_id}/{event.artifact_id}.json", event.to_bytes())
        return event.artifact_id

    def completed(self, run_id: str) -> Manifest | None:
        digest(run_id, "reporter.run_id")
        try:
            raw = self.slots.get(f"run-completions/{run_id}.json")
        except StoreError as error:
            if error.code == "object_not_found":
                return None
            raise
        marker = object_fields(
            decode_json(raw), {"schema", "run_id", "result_id"}, "run_completion"
        )
        if (
            marker["schema"] != "stpd/run-completion-v1"
            or marker["run_id"] != run_id
            or raw != json_bytes(marker)
        ):
            raise BoundaryError("reporter", "completion_marker_mismatch")
        result = self.store.get_manifest(digest(marker["result_id"], "reporter.result_id"))
        if (
            result.kind != "run_result"
            or result.parent("run") != run_id
            or result.parameters.value().get("schema") != "stpd/run-result-v1"
        ):
            raise BoundaryError("reporter", "completion_result_mismatch")
        for parent in result.parents:
            self.store.get_manifest(parent.artifact_id)
        return result

    def complete(self, result: Manifest) -> str:
        if (
            result.kind != "run_result"
            or result.parameters.value().get("schema") != "stpd/run-result-v1"
        ):
            raise BoundaryError("reporter", "unsupported_result")
        run_id = result.parent("run")
        self.store.publish(result)
        self.slots.put_if_absent(
            f"run-completions/{run_id}.json",
            json_bytes(
                {
                    "schema": "stpd/run-completion-v1",
                    "run_id": run_id,
                    "result_id": result.artifact_id,
                }
            ),
        )
        return result.artifact_id

    def events(self, run_id: str) -> tuple[Manifest, ...]:
        digest(run_id, "reporter.run_id")
        found = []
        for artifact_id in self.store.manifest_ids():
            manifest = self.store.get_manifest(artifact_id)
            if manifest.kind == "run_event" and any(
                p.role == "run" and p.artifact_id == run_id for p in manifest.parents
            ):
                if manifest.parameters.value().get("schema") != "stpd/run-event-v1":
                    raise BoundaryError("reporter", "unsupported_event")
                found.append(manifest)
        return tuple(
            sorted(found, key=lambda e: (e.parameters.value().get("step", 0), e.artifact_id))
        )
