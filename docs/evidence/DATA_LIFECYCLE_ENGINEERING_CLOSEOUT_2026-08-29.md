# Data Lifecycle Engineering Closeout - 2026-08-29

## Exact Source And Inputs

- branch base: STPD `develop` at `ae4c8ac43caf224b01951c030842a60814a09bea`;
- largest physically available admitted corpus: `dataset-8af38f14ec1a7611`;
- rows: 106;
- semantic dataset hash:
  `8af38f14ec1a76110adc8335eab81be081563ff7f9b8e1e6cdc936355b4d11a8`;
- Parquet SHA-256:
  `0078fca88b4b95b30d004b3631539e5115586482c1595424a0f37cc2c3c189e1`.

The documented 1,962-row frozen corpus was not physically available on this Mac. Historical
reports were not treated as bytes available for benchmarking.

## Measurements

- current Parquet: 86,148 bytes for 2,470,727 logical column bytes (`0.034867`);
- verified materialization, five reads: 138.216-234.289 ms, median 144.916 ms;
- 210 state references / 151 unique states;
- 106 catalogs / 89 unique ordered catalogs;
- 59 of 103 sequential successors equal the next state (`57.2816%`);
- object-reference probe: 96,296 bytes (`1.117797x` current), reconstruction pass;
- dictionary probe: 87,077 bytes (`1.010784x` current);
- monolithic record JSON probe: 52,611 bytes (`0.610705x` current).

The current canonical representation remains. This is a measured keep decision, not a claim
that it is globally optimal.

## Derived And Transfer Probe

A deterministic shape-only backend produced 572 pooled samples at hidden size 1,024 in a
2,432,912-byte immutable artifact. The local content-addressed handoff used six objects
totaling 2,522,307 bytes. First stage transferred all six; retry transferred zero and reused
all six. Tests prove corruption, model-view, source-corpus and consumer drift fail closed.

The backend was not Qwen. These figures validate artifact mechanics and storage shape only.

## Decisions

- keep canonical `ResearchTransition` and current Parquet layout;
- reject immediate object normalization and dictionary migration;
- retain monolithic layout only as a future benchmark candidate;
- compile pooled frozen-Qwen features as an optional rebuildable artifact;
- use content-addressed manifest-first incremental staging;
- bind handoff to exact STPD source, `uv.lock`, model view and Qwen identity;
- keep training authorization outside integrity/staging.

## Non-Claims

No full 1,962-row physical benchmark, real-Qwen compilation, remote-host transfer, GPU
throughput, optimizer execution, scientific result or model-quality improvement is proved.
