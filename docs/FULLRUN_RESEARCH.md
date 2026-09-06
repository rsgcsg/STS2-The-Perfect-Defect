# Full-Run Research Contracts

The new research contract is versioned separately from historical combat-v0. The latter's
corpora, serializers, checkpoints and scientific protocol remain reproducible and are not
silently relabelled Full-Run.

## Authority

Platform owns semantic execution state S, complete A_sem(S), exact Human choice, native Commit,
causal successor, occurrence/disposition accounting and real-game qualification. STPD consumes
verified projections. H is not S; public BoundActions are not the research legal catalog.
Family/surface labels are stratification metadata, not a second native census or model switch.

`SourceAdapter` is the narrow integration port. `SourceProjection` binds source bytes, adapter,
evidence scope, run continuity proofs and transitions. Only the explicitly synthetic adapter
is installed at this stage. It cannot accept a guessed final Platform schema or emit qualified
Platform evidence. A future adapter must verify the final owning Platform format before
producing a qualified projection; a caller-controlled flag is not qualification.

## ResearchTransitionV1

The typed codec owns `stpd/research-transition-v1`: stable source-record identity, run/episode/
step, domain/family/surface, semantic state, complete catalog, chosen key, Commit reference,
causal successor or terminal, disposition and provenance. Action keys identify candidates
outside model inputs. Runtime/witness IDs remain provenance, not features. Missing evidence,
unknown schema, duplicate candidates and invalid chosen/Commit/successor combinations fail.

Leaving Combat is normal run continuity. Native root/continuation relationships remain
Platform-owned; STPD does not manufacture a new gameplay root for a child selector.

## Data admission and splits

Admission rejects incomplete/uncommitted decisions instead of silently calling a subset a
Full-Run corpus. Exact duplicate records are counted; same identity with different content,
run/step collisions, missing steps and source-accounting mismatch fail. Source blobs and
manifests remain immutable. A failed admission does not rewrite source evidence.

Whole-run splitting also joins runs connected by repeated semantic decision inputs. Labels,
candidate ordering, runtime IDs and future successors do not enter that grouping key. At
least three independent components are required; the gate is not weakened when data is
insufficient. The split seed and deterministic assignment are bound to the logical dataset.

Canonical storage is Parquet with indexed run/surface/family/split fields plus canonical
transition JSON. Loading verifies payload hashes, every indexed-column/record alignment,
source provenance, admission and the recomputed split/logical identity. The physical artifact
ID additionally binds the exact Parquet bytes and producer; logical identity is independent
of a later equivalent physical encoding. This is not a claim of unmeasured large-corpus scale.

## Provisional model representation

Lite, Standard and Full are explicitly `stpd-fullrun-provisional-v1`. All scenes share one
RUN/DECISION/VISIBLE_ENTITIES/READS state format and kind/subject/arguments action format.
Reads require an admitted semantic projection and evidence reference, which is excluded from
model text. Forbidden runtime/native IDs, timestamps, chosen-label position and future/outcome
fields fail closed. Candidate permutation preserves the corresponding text and semantic key.

Standard is not finally frozen until qualified real Full-Run token/compute profiling. The
synthetic fixtures exercise twelve illustrative decision contexts; they are neither the
Platform surface vocabulary nor native coverage evidence.

## Next consumers and non-claims

ModelView, exact frozen-Qwen FeatureSet, TrainingInput, provider-neutral worker, checkpoints,
models and evaluations consume these immutable identities. ArtifactStore, Registry, analysis
and dashboard remain peripheral. No source/test result here proves a real Full-Run corpus,
Human Gold, pretrained-Qwen advantage, cloud qualification or live-game capability.
