# ADR-0002: Versioned unified Human serialization

Status: accepted

## Context

The admitted cross-platform Human population has complete combat context in
`facts.interaction` and structured hand/enemy/card facts. The original Standard
serializer also emitted the full `facts.referents` projection, duplicating that
content for every candidate. On the real 1,962-record population this exceeded
the frozen Standard P95 token gate. Truncation, raising the gate, deleting
records, or mutating raw evidence would invalidate provenance.

## Decision

Keep `stpd-model-serialization-v0` frozen and add
`stpd-model-serialization-v1`. For Standard `turn_action` combat states only,
v1 omits the redundant `facts.referents` field after strict state validation.
The complete interaction, structured combat facts, chosen action, legal action
catalog and stable successor remain unchanged. Lite, Full and non-combat
families retain their prior behavior.

The new `human-combat-unified-v2` combination plan explicitly pins serializer
v1 and admits exact macOS v1, Windows v1 and Windows v2 profile digests. Profile
corpora and the unified snapshot must use the same serializer identity.

## Alternatives rejected

- Raise P95 or hard token thresholds: changes the frozen gate without evidence.
- Silent truncation: can remove decision-relevant content and is forbidden.
- Edit or deduplicate raw Human records: destroys evidence or distinct choices.
- Modify serializer v0 in place: rewrites historical corpus identities.

## Consequences and evidence

Corpus IDs change because serializer identity is part of every profile and
combined snapshot. Old snapshots remain immutable. The real unified population
profiles at Standard P95 2,883 and max 4,110 tokens under the unchanged
4,096/8,192 limits, with B0 pass and no cross-split semantic duplicates. These
are data-admission facts, not model-quality evidence.
