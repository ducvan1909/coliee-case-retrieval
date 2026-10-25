# Plan 05 — Sidecar annotations and structural relations

Plan 05 runs replaceable deterministic rule workers over validated SourceBlock
v1.3 and SentenceAtom artifacts. Sidecars never copy source text. Every record
keeps exact SpanRef, producer/version, dependency fingerprints, evidence refs,
and a canonical ID.

## Annotation semantics

- Marker and inherited balanced quote/list observations use `observed`.
- Citation/reference and speaker-language cues use `candidate`.
- Unbalanced quote observations use `review`.
- Speaker cues never assign speaker or attribution.
- Citation mentions never assert authority identity, treatment, noticed case,
  relevance, or legal support.
- Confidence is omitted because these rule outputs have no adjudicated
  calibration. If a future worker emits it, `confidence_definition` is required.

## Relations

Persisted relations are limited to exact containment, cue-backed continuation,
and candidate-only formal heading governance. Heading candidates do not become
accepted governance. `next`/`previous` adjacency is not persisted; the API
reconstructs it from SourceBlock order with `status=derived` and
`reconstructable=true`.

All annotation and relation evidence filters use exact half-open overlap.
`[x,x)` is empty and returns no records, including at source offset `0` and the
source end. Touching boundaries do not overlap. Invalid/out-of-range spans or a
case/source identity mismatch raise a structured query error; there is no
implicit point-query interpretation.

No semantic relations such as `qualifies`, `responds_to`, `condition_for`, or
`same_legal_point` are allowed. There is no mandatory tree or semantic graph.

## Failure and cache behavior

Cache identity includes source hash, Plan 03 and Plan 04 artifact cache keys,
worker bundle version, and policy hash. Worker failure is isolated and recorded
without removing source or successful worker outputs. Partial artifacts use a
dependency-addressed `partial-<failed-worker-fingerprint>` namespace, so they
cannot occupy or overwrite the complete cache path.

Run:

```powershell
python -m knowledge_base.pipeline_v1.sidecars
```
