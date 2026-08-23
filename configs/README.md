# Configuration workspace

Future experiment configurations live here after their interfaces are implemented.

Recommended layout:

```text
configs/v0/data/
configs/v0/models/
configs/v0/training/
configs/v0/benchmarks/
configs/v0/experiments/
```

A config contains no secret or machine-specific absolute path. It references versioned data,
model, serializer, Host, Connector, and benchmark identities. Each executed config is copied
or hashed into its experiment manifest.

`configs/v0/experiments/s1-human-combat-smoke-v1.json` freezes the bounded
owner-gated behavior S1 smoke. Machine-specific corpus/Qwen/runtime paths and
their exact hashes live only in the generated `.local/training-ready` handoff.

`configs/v0/experiments/s1-human-combat-live-v1.json` freezes the first
experimental S1 checkpoint-to-Connector lane. It admits only the complete
Defect A0 `play_card`/`end_turn` catalog and binds the exact local checkpoint,
Qwen, game, Connector and Modset identities without changing training data.
