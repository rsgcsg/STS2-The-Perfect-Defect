# AgenticSTS Import

This module is a source adapter for historical AgenticSTS records. It is not a
game adapter and it does not establish current STS2, Headless, or Connector
authority. The canonical output is an existing `ResearchTransition` plus a
separate provenance/license sidecar.

## Input boundary

`stpd.data.agenticsts.import_agenticsts(path)` reads one JSON document, JSONL
file, or gzipped JSONL file. A JSON document may contain one record or:

```json
{
  "source": {
    "dataset": "AgenticSTS-trajectories",
    "revision": "dataset-revision",
    "license": "CC-BY-4.0",
    "source_url": "https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories",
    "record_ref": "trajectories/run-id#step-0"
  },
  "records": [
    {"transition": {"...": "ResearchTransition v0 fields"}}
  ]
}
```

JSONL records may carry `source`/`provenance` themselves. A caller may pass a
file-level `source_metadata` mapping when the license manifest is stored next
to the raw file. A record-level source mapping takes precedence; it is not
silently completed from the fallback mapping when the record declares an
incomplete source envelope.

The transition payload must already contain the fields required by
`ResearchTransition` v0, including:

- `decision_mode: "combat"`;
- an explicit non-empty `legal_actions` catalog;
- `eligibility.legal_action_completeness: "complete"`;
- a `chosen_action` that maps to exactly one catalog action;
- `successor_stable: true` when a successor is present;
- a successor for every non-terminal, in-scope decision;
- explicit `environment` identity rather than an inferred current identity.

The importer intentionally does not infer alternatives from prompts, action
indices, localized text, `state` fields, or a current Headless installation.
Raw AgenticSTS event logs that do not include an extracted complete catalog are
therefore rejected as incomplete source records. This is a useful audit result,
not a claim that the historical game run was invalid.

## Output and evidence

```python
report = import_agenticsts("trajectory.jsonl.gz")
for record in report.accepted:
    transition = record.transition
    provenance = record.provenance.to_dict()
```

`record.normalized_transition` is the exact JSON-compatible mapping produced by
`ResearchTransition.to_dict()`. The sidecar retains dataset, revision, license,
source URL, record reference, and extra source metadata. It is deliberately not
part of model input.

`ImportReport.rejected` is a quarantine list. Each item has:

```json
{
  "record_ref": "...",
  "reason_code": "incomplete_legal_action_catalog",
  "message": "...",
  "details": {}
}
```

The stable reason codes currently include:

- `missing_license` and `unknown_license`;
- `missing_provenance`;
- `missing_legal_action_catalog` and `incomplete_legal_action_catalog`;
- `ambiguous_action_mapping` and `chosen_action_not_in_catalog`;
- `missing_successor` and `unstable_successor`;
- `non_combat_record`, `malformed_json`, `invalid_record`, and
  `invalid_transition_contract`.

The admitted AgenticSTS source license for this slice is `CC-BY-4.0`. Mixed or
third-party competitor archives must be split and audited under their own
licenses before they can be imported. Unknown rights fail closed.

The importer preserves historical game/source provenance but does not create a
current Headless/Connector artifact identity, current-patch qualification, B0
pass, or semantic parity claim. Accepted records still require downstream
split, leakage, deduplication, and B0 checks before training use.

## Non-claims

- A parsed AgenticSTS trajectory is not current-patch ground truth.
- A complete source catalog is not proof that the source action was optimal.
- `ResearchTransition` construction is not Headless or live-runtime evidence.
- This slice does not download external data, verify a dataset revision, or
  redistribute raw trajectories.
