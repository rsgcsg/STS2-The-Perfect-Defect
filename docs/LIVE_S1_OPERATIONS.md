# Experimental Live S1 Operations

This lane connects one exact trained behavior S1 checkpoint to the shipped UI
through the official sibling Connector TypeScript SDK. It is an experimental
live smoke, not scientific Core, B6, Human Gold, or a model-quality result.

## Frozen input

`configs/v0/experiments/s1-human-combat-live-v1.json` binds the trained source,
READY file, checkpoint SHA-256, Scheme1 linear head, serializer v1, Standard
profile, frozen Qwen identity, exact Connector artifact, exact game release and
observer Modset. The runner refuses any drift. Qwen and the linear head load once
and remain resident for the process.

The runner imports the exact built sibling Connector SDK through a small NDJSON
transport bridge. The SDK performs strict protocol decoding and owns controller
registration, lease acquisition/renewal/release, Reads and action submission.
STPD never reconstructs legality or native input.

## Admission and handoff

Default mode is Human with no controller lease. A complete decision is available
to Qwen only when all of these are true:

- the persistent run declares Defect and Ascension 0;
- Snapshot and every advertised Read are coherent and complete;
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
uv run pytest -q tests\test_live_s1.py tests\test_environment_collector.py
uv run python tools\live_s1.py model-check
```

Cold-launch through the exact Annotator deployment so its Connector/game/Modset
canaries remain process-local inputs, verify the loaded seal, then run:

```powershell
uv run python tools\live_s1.py run
```

The source and sibling Connector worktrees must be clean. Closing the runner does
not close STS2.
