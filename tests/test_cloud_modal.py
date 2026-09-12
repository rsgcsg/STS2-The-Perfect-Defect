from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_artifact_store_v1 import PRODUCER

from stpd.cloud_jobs.contracts import ComputeReceipt, ComputeRequest
from stpd.cloud_jobs.modal import ModalCall, ModalProvider, ModalTarget, credential_presence
from stpd.json_boundary import BoundaryError


def target() -> ModalTarget:
    return ModalTarget(PRODUCER, "registry.example/stpd@sha256:" + "d" * 64)


class FakeCall:
    object_id = "fc-fixed"

    def __init__(self, value=None, error=None):
        self.value, self.error = value, error
        self.cancelled = False

    def get(self, *, timeout):
        assert timeout == 0
        if self.error:
            raise self.error
        return self.value

    def cancel(self, *, terminate_containers):
        assert terminate_containers
        self.cancelled = True


class FakeFunction:
    def __init__(self, call):
        self.call, self.requests = call, []

    def spawn(self, request, target_id):
        self.requests.append((request, target_id))
        return self.call


def sdk_for(function, selected):
    def lookup(app_name, name):
        assert app_name == selected.app_name and name == "compute"
        return function

    def from_id(call_id):
        assert call_id == function.call.object_id
        return function.call

    return SimpleNamespace(
        Function=SimpleNamespace(from_name=lookup), FunctionCall=SimpleNamespace(from_id=from_id)
    )


def test_submit_serialize_poll_and_cancel_use_exact_target_and_receipt() -> None:
    selected = target()
    assert ModalTarget.decode(selected.to_dict()) == selected
    request = ComputeRequest("features", "a" * 64, PRODUCER, "attempt-1")
    receipt = ComputeReceipt(
        request.request_id, request.attempt_id, request.kind, request.input_id,
        PRODUCER, "candidate_prepared", "b" * 64,
    )
    call = FakeCall({"target_id": selected.target_id, "receipt": receipt.to_dict()})
    function = FakeFunction(call)
    provider = ModalProvider(selected, sdk=sdk_for(function, selected))
    handle = provider.submit(request)
    assert ModalCall.decode(handle.to_dict()) == handle
    assert provider.poll(handle) == receipt
    provider.cancel(handle)
    assert call.cancelled and len(function.requests) == 1
    call.error = TimeoutError()
    assert provider.poll(handle) is None
    call.error = RuntimeError("signed-URL-should-never-be-exposed")
    with pytest.raises(BoundaryError, match="result_unavailable") as error:
        provider.poll(handle)
    assert "signed-URL" not in str(error.value)


def test_ambiguous_submit_is_never_retried() -> None:
    selected = target()
    function = FakeFunction(FakeCall())
    calls = []

    def uncertain(*args):
        calls.append(args)
        raise TimeoutError("remote may already be running")

    function.spawn = uncertain
    provider = ModalProvider(selected, sdk=sdk_for(function, selected))
    with pytest.raises(BoundaryError, match="submission_unknown"):
        provider.submit(ComputeRequest("training", "a" * 64, PRODUCER, "attempt-1"))
    assert len(calls) == 1


def test_mutable_image_wrong_target_or_wrong_receipt_rejected() -> None:
    selected = target()
    with pytest.raises(BoundaryError, match="immutable_image"):
        replace(selected, image="registry.example/stpd:latest")
    assert replace(selected, timeout_seconds=300).app_name != selected.app_name
    with pytest.raises(BoundaryError, match="single_compatible_gpu"):
        replace(selected, gpu="T4")
    request = ComputeRequest("training", "a" * 64, PRODUCER, "attempt")
    call = FakeCall({"target_id": "wrong", "receipt": {}})
    function = FakeFunction(call)
    provider = ModalProvider(selected, sdk=sdk_for(function, selected))
    handle = provider.submit(request)
    with pytest.raises(BoundaryError, match="deployed_target"):
        provider.poll(handle)
    with pytest.raises(BoundaryError, match="foreign_target"):
        provider.poll(replace(handle, target_id="0" * 64))
    with pytest.raises(BoundaryError, match="target_source_lock"):
        provider.submit(replace(request, producer=replace(PRODUCER, source_revision="c" * 40)))
    assert len(function.requests) == 1


def test_credential_inspection_reports_only_presence(monkeypatch) -> None:
    monkeypatch.setenv("MODAL_TOKEN_ID", "never-return-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "never-return-secret")
    report = credential_presence()
    assert report["token_id_env"] and report["token_secret_env"]
    assert all(type(value) is bool for value in report.values())
    assert "never-return" not in str(report)
