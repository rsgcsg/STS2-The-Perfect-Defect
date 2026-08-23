# Experimental Live S1 Operations

This lane connects one exact trained behavior S1 checkpoint to the shipped UI
through the official sibling Connector TypeScript SDK. It is an experimental
live smoke, not scientific Core, B6, Human Gold, or a model-quality result.

## Frozen input

`configs/v0/experiments/s1-human-combat-live-v1.json` binds the trained source,
READY file, checkpoint SHA-256, Scheme1 linear head, serializer v1, Standard
profile, frozen Qwen identity, exact Connector artifact, exact game release and
Connector-only Modset. The runner refuses any drift. Qwen and the linear head load once
and remain resident for the process.

The runner imports the exact built sibling Connector SDK through a small NDJSON
transport bridge. The SDK performs strict protocol decoding and owns controller
registration, lease acquisition/renewal/release, Reads and action submission.
STPD never reconstructs legality or native input.

The checkpoint's model Read policy is explicitly `none`. This is not an
information-closure claim: all 1,962 accepted Human records were imported by
`human_annotator.py` with `reads={}` for both state and successor, their immutable
Parquet rows retain that shape, and serializer v1 emitted zero `READS=` lines for
the training population. Advertised Read descriptors remain intact in the Snapshot
and evidence, but the live bridge prefetches only the exact training-time subset,
which is empty for this checkpoint.

Connector `reads[]` remains a multi-instance array. Duplicate kinds are valid:
the admitted raw evidence includes 10 successor Snapshots advertising 39
per-card `surface_card` descriptors with distinct `read_id` and
`target_referent_id`. The bridge therefore never keys responses by kind; any
future selected responses retain every opaque Read identity in deterministic
`read_id` order. A duplicate opaque `read_id`, by contrast, fails closed.

## Admission and handoff

Default mode is Human with no controller lease. A complete decision is available
to Qwen only when all of these are true:

- the persistent run declares Defect and Ascension 0;
- the Snapshot is coherent and complete, and the frozen checkpoint Read selector
  returns exactly its empty training-time subset;
- interaction, surface and context are an ordinary player Combat turn;
- the complete, non-empty Connector catalog contains only `play` and `end_turn`;
- projection is a one-to-one `play_card` / `end_turn` catalog with no runtime IDs
  in serializer output.

Any potion, selector, choice, non-Combat surface, incomplete catalog or unknown
action hands the whole step to Human. Candidates are never filtered. `T` toggles
automatic combat takeover, `S` executes one admitted step, `H` immediately
returns to Human and releases the lease, and `Q` exits the runner while leaving
the game open.

A stale not-delivered Receipt causes a fresh observation without retrying the
request. Unknown delivery or transport loss after submission permanently taints
that runner process, disables auto, releases where possible and never retries.
Connector TTL remains the crash-safe release path.

An HTTP 409 `stale_state` while prefetching any selected Snapshot-bound Reads is different:
the entire uncommitted observation bundle is discarded, the terminal briefly
reports `REFRESHING_STALE_OBSERVATION`, and the runner performs a bounded
exponential-backoff fresh observe. It never reuses a Read from the stale bundle
and this observation-only race does not taint handoff state. Repeated inability
to verify a successor after a delivered action remains fail-closed.

## Local evidence

Each run creates `.local/live-s1/<UTC timestamp>/manifest.json` and append-only
`events.jsonl`. Evidence includes live/training/checkpoint/Qwen/Connector
identities, semantic candidates and scores, chosen action, latency, exact
execution envelope, Receipt, independent successor and handoff state. These
files contain process-local runtime identities and remain gitignored.

## Checks and launch

Build the exact SDK and run the targeted tests before starting the game:

```powershell
npm --prefix ..\STS2-Connector\sdk\typescript run build
node --test tests\connector_sdk_bridge_contract.test.mjs
uv run pytest -q tests\test_live_s1.py tests\test_environment_collector.py
uv run python tools\live_s1.py model-check
```

The two-observer Human Annotator Modset intentionally has no mutation authority.
With STS2 closed, use the sibling Annotator workstation tool to back up native
settings, keep its artifact installed-but-disabled, enable only Connector, and
cold-launch with exact Connector/game canaries:

```powershell
npm --prefix ..\STS2-human-Annotator run prepare:live-connector
npm --prefix ..\STS2-human-Annotator run launch:live-connector
uv run python tools\live_s1.py run
```

The source and sibling Connector worktrees must be clean. Closing the runner does
not close STS2.
