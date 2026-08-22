# AgenticSTS Data-Admission Audit — 2026-08-22

## Verdict

The official AgenticSTS trajectory subset is licensed and immutable, but it cannot supply
the first STPD 1k–2k behavior-ranking dataset. Across every released trajectory, zero rows
satisfy the existing full-listwise ranking admission contract.

`STOP — DATA BLOCKER: AGENTICSTS INSUFFICIENT FOR S1-SMOKE`

No extractor, canonical Parquet dataset, split manifest, S1 smoke configuration, or owner
training command was created.

## Exact source and license scope

- repository: `AlayaLab/AgenticSTS-trajectories`;
- immutable revision: `20f5170c420584935ec20e004498b4d4a3621f8b`;
- source URL: `https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories`;
- admitted license/path scope: `CC-BY-4.0` for `trajectories/*.jsonl.gz` and
  `runs_history.jsonl`;
- excluded scope: `competitors/*.tar.gz`, which retains mixed third-party licenses;
- checked source pin: `configs/v0/data/agenticsts-trajectories.json`.

Pinned metadata identities:

| File | Bytes | SHA-256 |
|---|---:|---|
| `README.md` | 4,418 | `45b2673f48273dbcd7e2a83a7cf71219b526d5226af1a0f8494efd4ce9e8048b` |
| `manifest.json` | 124,959 | `59ce409e38c45506831083c28b7730609d292d3d349ad42a51c9d270a44ff3cb` |
| `runs_history.jsonl` | 460,124 | `c36b759c12543795121cf93891277ebdb5dff87878c779f0bc57d557848822f3` |

The manifest contains 312 runs and 305 trajectory files. The audited trajectory-file
identity list has semantic digest
`cec5d7d10066f6498efce447c9c9dbf36fb41f06a8292a86310abb4f46cc081b`.
The 305 available logs cover 196 defeats, 96 victories, and 13 decision-capped runs.

## Representative-sample gate

The first sample was audited before the full download:

- path: `trajectories/20260416_143704_dc06f6a4.jsonl.gz`;
- bytes: 3,186,669;
- SHA-256: `d80bea2b7c7a3f9b44010c86d78a56c87aa5da82ccf88cc2d51c611faaaa18eb`;
- raw events: 17,431;
- decisions: 1,203;
- combat decisions: 859;
- reconstructable player-visible combat states: 859;
- sequential stable-result/next-state candidates: 738;
- explicit complete legal catalogs: 0;
- exact environment identities: 0;
- game seeds: 0;
- rank-eligible accepted rows: 0.

The existing `import_agenticsts` boundary accepted 0 of all 17,431 raw sample events
without a conversion layer. This was not treated as permission to fill missing fields.

## Full audit counts

| Requirement | Count |
|---|---:|
| Raw event records | 3,090,155 |
| Decision records | 198,600 |
| Combat decision records | 139,211 |
| Reconstructable player-visible combat states | 139,211 |
| Explicit chosen-action payloads | 139,211 |
| Historical policy metadata | 139,211 |
| Historical game version present | 131,590 |
| Stable action-result markers | 129,879 |
| Sequential stable-result/next-state candidates | 129,876 |
| Catalog-like raw fields | 0 |
| Explicit complete legal-action catalogs | 0 |
| Chosen actions uniquely mapped to complete catalogs | 0 |
| Game seed or declared split root | 0 |
| Exact game/Host/Player Environment identity | 0 |
| Sufficient environment/policy/provenance | 0 |
| Rank-eligible accepted records | **0** |

Acceptance is `0 / 198,600 = 0.0%` of all decisions and
`0 / 139,211 = 0.0%` of combat decisions.

The historical game-version field is not current evidence. Among logs with trajectories,
291 declare `v0.103.1`, one declares `v0.103.3`, and 13 declare no game version. None
claims STPD's current `v0.111.0` identity.

## Missing evidence

The release does not provide:

- an explicit complete finite legal-action catalog at each decision;
- a chosen action mapped uniquely to such a catalog;
- a game seed or separately declared whole-run split root;
- exact game commit, assembly SHA-256, and MVID;
- exact Host source/artifact SHA-256 and MVID;
- exact Player Environment implementation revision and digest;
- an explicit source-bound `ResearchTransition` successor object.

Detailed hand entries contain `playable` and `target_type` fields, but deriving every card,
target, potion, and end-turn alternative from those fields would create a second legality
projection. It would not prove catalog completeness and is therefore forbidden. Sequential
stable result/next-state candidates are useful evidence, but do not repair the missing
catalog, seed, or exact environment identity.

## Required current-teacher collection

The next admissible source must collect at least 1,000 decisions from a current admitted
teacher lane and persist, per whole episode/run/seed root:

- exact current game, Host, and Player Environment identity;
- stable player-visible pre-action state;
- complete finite legal-action catalog from the authoritative environment;
- exact executed action mapped one-to-one to that catalog;
- stable post-action successor or explicit terminal/scope exit;
- declared behavior-policy identity and source revision.

Only after those records pass the existing importer/normalizer, Parquet/manifest pipeline,
whole-root split, dedup/leakage checks, and B0 may `S1-1K-2K-SMOKE` be prepared.

## Reproduction

Raw data stays outside Git. From the exact snapshot:

```powershell
uv run python tools/audit_agenticsts.py --snapshot <EXACT_20F5170C_SNAPSHOT> --output .local/evidence/agenticsts/audit-20f5170c.json
```

The local audit report is 5,823 bytes with SHA-256
`b5eeff1d6b246c731b9c86f5faa44d6ef647cd3199f38cb90da126a10140b8b3`.
