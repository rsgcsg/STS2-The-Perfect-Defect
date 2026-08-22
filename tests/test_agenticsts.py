from __future__ import annotations

import gzip
import json
from pathlib import Path

from stpd.data.agenticsts import ImportReport, RejectionCode, import_agenticsts

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "agenticsts"


def _report(name: str) -> ImportReport:
    return import_agenticsts(FIXTURES / name)


def test_imports_jsonl_and_keeps_transition_and_license_sidecar() -> None:
    report = _report("pass.jsonl")

    assert report.accepted_count == 1
    assert report.rejected_count == 0
    record = report.accepted[0]
    assert record.provenance.license == "CC-BY-4.0"
    assert record.provenance.record_ref == "trajectories/run-fixture#0"
    assert record.normalized_transition["schema"] == "stpd/research-transition-v0"
    assert record.normalized_transition["chosen_action"]["action_key"] == "play:defend:H0"


def test_missing_and_unknown_license_fail_closed() -> None:
    unknown = _report("unknown-license.json")
    missing = _report("missing-license.json")

    assert unknown.rejected[0].reason_code is RejectionCode.UNKNOWN_LICENSE
    assert missing.rejected[0].reason_code is RejectionCode.MISSING_LICENSE


def test_mixed_license_competitor_subset_cannot_self_declare_cc_by(
    tmp_path: Path,
) -> None:
    source = json.loads((FIXTURES / "pass.jsonl").read_text(encoding="utf-8"))
    source["source"]["record_ref"] = "competitors/CharTyr.tar.gz#record-0"
    path = tmp_path / "competitor.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    report = import_agenticsts(path)

    assert report.accepted_count == 0
    assert report.rejected[0].reason_code is RejectionCode.SOURCE_SUBSET_NOT_ADMITTED


def test_unpinned_or_noncanonical_source_fails_closed(tmp_path: Path) -> None:
    source = json.loads((FIXTURES / "pass.jsonl").read_text(encoding="utf-8"))
    source["source"]["revision"] = "main"
    source["source"]["source_url"] = "https://example.invalid/agenticsts"
    path = tmp_path / "untrusted-source.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    report = import_agenticsts(path)

    assert report.accepted_count == 0
    assert report.rejected[0].reason_code is RejectionCode.SOURCE_SUBSET_NOT_ADMITTED


def test_missing_successor_is_not_transition_eligible() -> None:
    report = _report("missing-successor.json")

    assert report.accepted_count == 0
    assert report.rejected[0].reason_code is RejectionCode.MISSING_SUCCESSOR


def test_ambiguous_semantic_chosen_action_is_rejected() -> None:
    report = _report("ambiguous-action.json")

    assert report.accepted_count == 0
    assert report.rejected[0].reason_code is RejectionCode.AMBIGUOUS_ACTION_MAPPING


def test_incomplete_catalog_is_rejected_without_fabricating_actions() -> None:
    report = _report("incomplete-catalog.json")

    assert report.accepted_count == 0
    rejection = report.rejected[0]
    assert rejection.reason_code is RejectionCode.INCOMPLETE_LEGAL_ACTION_CATALOG
    assert rejection.details["legal_action_completeness"] == "partial"


def test_json_document_and_machine_report_are_serializable(tmp_path: Path) -> None:
    source = json.loads((FIXTURES / "pass.jsonl").read_text(encoding="utf-8"))
    document = tmp_path / "trajectory.json"
    document.write_text(json.dumps(source), encoding="utf-8")

    report = import_agenticsts(document)

    assert report.accepted_count == 1
    serialized = report.to_dict()
    assert serialized["rejected_count"] == 0
    json.dumps(serialized)


def test_gzipped_jsonl_accepts_explicit_file_level_provenance(tmp_path: Path) -> None:
    source = json.loads((FIXTURES / "pass.jsonl").read_text(encoding="utf-8"))
    source.pop("source")
    path = tmp_path / "trajectory.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(source))

    report = import_agenticsts(
        path,
        source_metadata={
            "dataset": "AgenticSTS-trajectories",
            "revision": "fixture-v1",
            "license": "CC-BY-4.0",
            "source_url": "https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories",
            "record_ref": "trajectories/run-fixture#file-level",
        },
    )

    assert report.accepted_count == 1
    assert report.accepted[0].provenance.record_ref == "trajectories/run-fixture#file-level"


def test_terminal_transition_may_end_without_a_successor(tmp_path: Path) -> None:
    source = json.loads((FIXTURES / "pass.jsonl").read_text(encoding="utf-8"))
    source["transition"]["successor"] = None
    source["transition"]["successor_stable"] = False
    source["transition"]["terminal"] = True
    path = tmp_path / "terminal.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    report = import_agenticsts(path)

    assert report.accepted_count == 1
    assert report.accepted[0].transition.successor is None
