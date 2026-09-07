from __future__ import annotations

from pathlib import Path

import pytest
from test_artifact_store_v1 import PRODUCER

from stpd.artifact_contracts import Manifest, Parent
from stpd.json_boundary import FrozenObject
from stpd.storage.blobs import StoreError
from stpd.storage.local import LocalBlobStore
from stpd.storage.run_reporter import ObjectStoreRunReporter
from stpd.storage.store import ManifestArtifactStore


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
    event = Manifest(
        "run_event",
        PRODUCER,
        (Parent("run", run.artifact_id),),
        parameters=FrozenObject.of({"schema": "stpd/run-event-v1", "step": 1}),
    )
    with pytest.raises(StoreError):
        reporter.emit(event)
    assert reporter.events(run.artifact_id) == (event,)
    assert reporter.emit(event) == event.artifact_id
    assert reporter.completed(run.artifact_id) is None
    result = Manifest(
        "run_result",
        PRODUCER,
        (Parent("run", run.artifact_id),),
        parameters=FrozenObject.of({"schema": "stpd/run-result-v1"}),
    )
    assert reporter.complete(result) == result.artifact_id
    assert reporter.complete(result) == result.artifact_id
    assert reporter.completed(run.artifact_id) == result
    conflicting = Manifest(
        "run_result",
        PRODUCER,
        result.parents,
        parameters=FrozenObject.of({"schema": "stpd/run-result-v1", "different": True}),
    )
    with pytest.raises(StoreError, match="collision"):
        reporter.complete(conflicting)
    assert reporter.completed(run.artifact_id) == result


def test_completion_publication_race_selects_one_immutable_result(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    store = ManifestArtifactStore(LocalBlobStore(tmp_path))
    reporter = ObjectStoreRunReporter(store, store.blobs)
    run = Manifest("run", PRODUCER)
    store.publish(run)
    results = [
        Manifest(
            "run_result",
            PRODUCER,
            (Parent("run", run.artifact_id),),
            parameters=FrozenObject.of({"schema": "stpd/run-result-v1", "attempt": i}),
        )
        for i in range(8)
    ]

    def publish(result):
        try:
            return reporter.complete(result)
        except StoreError as error:
            assert error.code == "immutable_key_collision"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = [value for value in pool.map(publish, results) if value is not None]
    assert len(winners) == 1
    assert reporter.completed(run.artifact_id).artifact_id == winners[0]
