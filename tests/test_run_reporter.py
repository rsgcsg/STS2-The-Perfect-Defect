from __future__ import annotations

from pathlib import Path

import pytest

from stpd.artifact_contracts import Manifest, Parent
from stpd.json_boundary import FrozenObject
from stpd.storage.blobs import StoreError
from stpd.storage.local import LocalBlobStore
from stpd.storage.run_reporter import ObjectStoreRunReporter
from stpd.storage.store import ManifestArtifactStore

from test_artifact_store_v1 import PRODUCER


def test_immutable_completion_and_manifest_event_recovery(tmp_path: Path) -> None:
    class FailIndexOnce(LocalBlobStore):
        failed = False

        def put_if_absent(self, key: str, data: bytes) -> bool:
            if key.startswith("run-events/") and not self.failed:
                self.failed = True
                raise StoreError("injected_index_write_failure")
            return super().put_if_absent(key, data)

    blobs = FailIndexOnce(tmp_path)
    store = ManifestArtifactStore(blobs)
    reporter = ObjectStoreRunReporter(store, blobs)
    run = Manifest("run", PRODUCER)
    store.publish(run)
    event = Manifest("run_event", PRODUCER, (Parent("run", run.artifact_id),),
                     parameters=FrozenObject.of({"schema": "stpd/run-event-v1", "step": 1}))
    with pytest.raises(StoreError):
        reporter.emit(event)
    assert reporter.events(run.artifact_id) == (event,)
    assert reporter.emit(event) == event.artifact_id
    assert reporter.completed(run.artifact_id) is None
    result = Manifest("run_result", PRODUCER, (Parent("run", run.artifact_id),),
                      parameters=FrozenObject.of({"schema": "stpd/run-result-v1"}))
    assert reporter.complete(result) == result.artifact_id
    assert reporter.complete(result) == result.artifact_id
    assert reporter.completed(run.artifact_id) == result
    conflicting = Manifest("run_result", PRODUCER, result.parents,
                           parameters=FrozenObject.of({"schema": "stpd/run-result-v1", "different": True}))
    with pytest.raises(StoreError, match="collision"):
        reporter.complete(conflicting)
    assert reporter.completed(run.artifact_id) == result
