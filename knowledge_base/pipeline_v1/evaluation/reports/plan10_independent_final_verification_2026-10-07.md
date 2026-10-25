# Plan 10 independent final verification — 2026-10-07

## Verdict

**PASS — offline/mock runtime and paired-experiment contract only.**  This
supersedes the earlier runtime FAIL reports after independent re-execution.
It is explicitly **not** a semantic AU-quality, human-gold, provider, Modal,
or retrieval-quality pass.

## Verified controls

| Control | Result | Evidence |
|---|---|---|
| KOS-5, raw-source binding | PASS | `build_locked_requests` loads Plan 07 locked workloads, opens each immutable raw source, recomputes its SHA-256, and renders on demand.  Five case IDs are present. |
| Workload completeness | PASS | `inputs/p2a.json` and `inputs/p2b.json` each contain **96** requests; the persisted paired artifact reports **96** matched case/batch pairs. |
| Fair P2a/P2b controls | PASS | Persisted paired controls assert equal model/prompt/schema/examples/caps, case/batch pairs, and target IDs.  Independent test mutates controls and targets and observes rejection. |
| Cross-arm cache isolation | PASS | Cache key includes arm plus source, region, render digest, and full spec; caches are under separate arm paths. |
| Resume and invalidation | PASS | Temporary first run has 0 hits per arm; full rerun has **96/96 hits per arm**.  Source/spec mutation tests produce misses; the whole spec is part of cache identity. |
| Accounting and repetition metrics | PASS | Per-arm ledgers and aggregate accounting are persisted.  `comparison.json` records **93,920 `repeated_source_chars`** and **163 `repeated_context_chars`** for each arm.  These are distinct metrics; the former must not be described as repeated context. |
| Invalid/partial response handling | PASS | Tests cover missing targets, truncation, invalid usage, and mismatching evidence quote/span.  Validator also requires one target outcome per expected target. |
| Rule-vs-mock comparison validity | PASS, protocol only | Deterministic no-AU rule baseline operates on the same frozen request lists; comparison persists both arms and matched input hashes.  It emits no semantic score. |
| `model_silver` provenance/no-overclaim | PASS | Inputs, paired artifact, both runs, and comparison carry `evaluation_against: model_silver`, `semantic_gold: false`, and `retrieval_quality_claim: false`; persister rejects another boundary. |

## Executed verification

- `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p
  test_plan10.py -v`: **PASS 5/5**.
- Previously completed relevant upstream source/workload suite:
  `knowledge_base.pipeline_v1.evaluation.test_plan07_independent`: **PASS
  6/6**.
- Independent temporary rerun of complete offline experiment: first execution
  `0/96` cache hits per arm; rerun `96/96` cache hits per arm.  No remote
  provider or Modal path was invoked.

## Scope boundary

Mock output assigns all targets `no-AU`; its token counts are rendered-text
estimates and its latency is local runtime.  Thus this PASS proves reproducible
offline plumbing and a paired protocol—not AU extraction correctness, a model
comparison result, human gold, or retrieval efficacy.
