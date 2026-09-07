from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_artifact_store_v1 import PRODUCER
from test_fullrun_worker import training

from stpd.json_boundary import BoundaryError
from stpd.workbench.__main__ import main
from stpd.workbench.control import doctor, launch_packet
from stpd.workbench.readiness import ENGINEERING, EXTERNAL, readiness
from stpd.workers.contracts import prepare_run


def test_store_doctor_and_launch_do_not_embed_credentials(tmp_path: Path, monkeypatch) -> None:
    store, _, envelope, _ = training(tmp_path)
    _, run = prepare_run(store, envelope.artifact_id, PRODUCER)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "private-never-in-packet")
    packet = launch_packet(store, run.artifact_id, PRODUCER)
    assert "private-never-in-packet" not in str(packet)
    assert packet["commands"][-1][-1] == run.artifact_id
    assert doctor(store, smoke=True)["conditional_smoke"] == "PASS"
    with pytest.raises(BoundaryError, match="run_source"):
        launch_packet(store, run.artifact_id, replace(PRODUCER, source_revision="f" * 40))


def test_readiness_requires_exact_complete_receipts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("stpd.workbench.readiness.source_identity", lambda root: PRODUCER)
    assert readiness(tmp_path)["verdict"] == "EVIDENCE_REQUIRED"
    evidence = {
        "schema": "stpd/prefullrun-qualification-v1",
        "producer": PRODUCER.to_dict(),
        "portable": "PASS",
        "e2e": {"verdict": "CPU_E2E_PASS", "producer": PRODUCER.to_dict()},
        "ci": {
            "head_sha": PRODUCER.source_revision,
            "run_id": 1,
            "conclusion": "success",
            "jobs": {
                name: "success" for name in ("linux-portable", "windows-portable", "locked-python")
            },
        },
    }
    report = readiness(tmp_path, evidence)
    assert report["verdict"] == "STPD_PRE_FULLRUN_AI_ENGINEERING_READY"
    assert all(report["categories"][name] == "AI ENGINEERING PASS" for name in ENGINEERING)
    assert all(report["categories"][name] == state for name, state in EXTERNAL.items())
    evidence["ci"]["jobs"]["windows-portable"] = "skipped"
    assert readiness(tmp_path, evidence)["verdict"] == "EVIDENCE_REQUIRED"
    evidence["ci"]["jobs"]["windows-portable"] = "success"
    evidence["ci"]["head_sha"] = "f" * 40
    assert readiness(tmp_path, evidence)["verdict"] == "EVIDENCE_REQUIRED"


def test_cli_requires_exact_transfer_identity_and_redacts_errors(tmp_path: Path, capsys) -> None:
    assert main(["push", "--store", str(tmp_path)]) == 1
    assert "exact_artifact_and_peer_required" in capsys.readouterr().out
    assert main(["doctor", "--store", str(tmp_path), "--smoke"]) == 0
    assert '"conditional_smoke": "PASS"' in capsys.readouterr().out
