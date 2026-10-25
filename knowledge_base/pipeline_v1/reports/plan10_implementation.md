# Plan 10 AU extraction baseline — implementation status

`au_baseline/` implements a development-only, raw-source protocol. It renders
locked AnalysisRegions on demand, never stores region text as a canonical
artifact, and produces versioned request/cache records.

- Arms supported by the shared input contract: P2a and P2b.
- Model mode is adapter-ready but disabled; `run_mock` is the only runnable
  provider in this change and records `paid_provider_called: false`.
- The response contract requires all processed target ids, AU candidates,
  no-AU ids, context requests, warnings, and an explicit truncation flag.
- Host validation rejects missing/foreign/duplicate target ids, foreign
  no-AU records, malformed candidates, and truncated output.
- The input manifest is rebuilt from the locked Plan 07 P2a/P2b region maps
  and source hashes. It binds each request to case, source hash, batch, region
  fingerprint, render digest, target IDs and exact rendered span addresses.
- The paired-experiment manifest rejects different model, prompt, schema,
  examples, caps, batch pairs or target IDs before either arm runs.
- Cache identity contains arm, source hash, region, render digest and spec;
  a source/spec change cannot replay an old mock record. The run ledger keeps
  request-to-cache references, enabling deterministic resume.
- Accounting records input/output/total tokens, requests, latency, rendered
  characters and repeated source characters calculated from actual rendered
  span overlap. No semantic score is emitted by mock mode.
- `outputs/plan10_au_baseline_v1/` contains the frozen P2a/P2b input manifests,
  paired control, raw mock cache, two per-arm ledgers, deterministic rule
  baseline and comparison report. The initial offline run has 96 requests per
  arm; it is protocol evidence only.

Evaluation boundary: any future comparison to Plan09 labels must declare
`evaluation_against: model_silver`. It is not human gold, a semantic PASS, or
a retrieval estimate. The legacy Plan09 progress file says Plan10 is locked;
this implementation relies on the explicit R5/R6 development-only authority
for code and mock tests, and makes no paid/model execution claim.

This does not complete semantic AU extraction. The deterministic rule baseline
and mock adapter return `no-AU` for every scheduled target; their only purpose
is to establish a fair, resumable experiment harness before a separately
authorized real-model run.
