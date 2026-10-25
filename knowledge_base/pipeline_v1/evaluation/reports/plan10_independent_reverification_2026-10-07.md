# Plan 10 independent re-verification — 2026-10-07

## Final verdict

**FAIL — the offline/mock runtime and experiment contract is still incomplete.**
This replaces neither the earlier report nor its semantic boundary.  The
remediation improves several local safeguards, but it does not materialize or
test a Plan 10 experiment.  No real provider or Modal execution occurred.

## Remediation checks that now pass

| Control | Result | Independent evidence |
|---|---|---|
| KOS-5 locked raw source | PASS | Prior raw-byte SHA-256 recomputation matches all five Plan 07 source hashes; independent Plan 07 suite completed 6/6 PASS. |
| Raw-source region renderer | PASS, upstream | Plan 07 suite confirms immutable source references and P2 arm workload invariants. |
| Arm cache separation | PASS (primitive) | Black-box run: P2a first call `cache_hits=0`, repeat `=1`, P2b `=0`; three cache files were produced. |
| Source dependency invalidation | PASS (primitive) | Changing source hash yielded `cache_hits=0` and a distinct cache record. |
| Shared control object | PASS (primitive) | `arm_spec()` fingerprints model, prompt, schema, examples and caps; equal specs pass `assert_equivalent`. |
| Invalid evidence span | PASS | A non-matching span/quote with supplied source text raised `BaselineError`. |
| Missing target and truncation | PASS (narrow) | Full Plan 10 suite completed **2/2 PASS**. |
| Basic usage fields | PASS (mock only) | Mock records input/output tokens, latency, and total tokens. |

## Remaining mandatory failures

| Required property | Result | Exact unmet requirement |
|---|---|---|
| Raw-source-only Plan 10 request construction | FAIL | Remediation removed `build_requests`; there is no Plan 10 path from locked regions and raw source to requests, no source-hash check at run entry, and no persisted input manifest. |
| Fair paired P2a/P2b experiment | FAIL | Control equality is a callable helper, not an executed/persisted paired-arm artifact.  No test binds P2a/P2b region inputs to one identical model/prompt/schema/examples/caps record. |
| No cross-arm contamination | PARTIAL | Cache key contains `arm`, and black-box caching separates arms.  There is still no run-level contamination detector covering target/result reuse, comparison input sets, or cache provenance. |
| Resume/checkpoint durability and full invalidation | FAIL | Individual cache JSON files work, but there is no atomic run ledger/status, partial-result checkpoint, resume selection, corruption handling, or tested invalidation for prompt/schema/examples/caps/model mutations. |
| Context-repeat accounting | FAIL | `repeated_context_chars` is accepted from caller and summed; it is never calculated from rendered raw-source spans or verified against P2 workload overlap. |
| Request/output accounting | PARTIAL | Mock token numbers are synthetic and only 2 existing tests execute no mock run.  There is no persisted aggregate report binding counts/latency to a manifest. |
| Rule-vs-model comparison validity | FAIL | `comparison_report` merely wraps arbitrary dictionaries.  No rule baseline, paired unit of analysis, scoring rule, matched coverage check, or comparison artifact exists. |
| `evaluation_against: model_silver` provenance gate | FAIL | A helper returns the field, but no persisted evaluation result exists and no validator rejects another provenance.  Thus the no-gold/no-semantic-overclaim boundary is not enforceable at the reported-result boundary. |
| Test evidence | FAIL | `test_plan10.py` remains two tests, covering only missing target and truncation.  None tests cache/restart/invalidation, arm equivalence, span validation, accounting, comparison, or provenance. |

## Completed suites

- Durable Plan 10 full suite: `python -m unittest discover -s
  knowledge_base/pipeline_v1/tests -p test_plan10.py -v` — **PASS 2/2**.
  Log: `plan10_full_suite.stdout.log`.
- Durable relevant upstream suite: `python -m unittest
  knowledge_base.pipeline_v1.evaluation.test_plan07_independent -v` — **PASS
  6/6 in 30.996s**. Log and exit status are stored alongside this report.

## Boundary

The passing items validate isolated mock primitives and locked input artifacts.
They do **not** validate AU semantic correctness, model performance, human gold,
or retrieval quality.  Plan 10 may receive an offline/runtime-contract PASS only
after every remaining row has an executable test and persisted, validator-backed
artifact with `evaluation_against: model_silver`.
