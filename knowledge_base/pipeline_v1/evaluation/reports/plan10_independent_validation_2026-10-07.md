# Plan 10 independent validation — 2026-10-07

## Verdict

**FAIL — Plan 10 is not ready to claim its required experimental/runtime
contract.**  This is not a semantic-quality failure: no real model output was
run or judged.  It is a structural/runtime failure, despite the two supplied
unit tests passing.

## Scope and safety

Read-only inspection and offline mock execution only.  No paid provider,
Modal, or Plan 11+ action was invoked.  The implementation inspected was
`au_baseline/core.py` and its supplied `tests/test_plan10.py` at 2026-10-07.

## Evidence that passes

| Check | Result | Evidence |
|---|---|---|
| KOS-5 raw source integrity | PASS | SHA-256 recomputation against the locked Plan 07 source hashes matched for `011904`, `013009`, `013948`, `045155`, and `099980`. |
| Raw-source rendering guard | PASS | `render_region` recomputes source SHA-256 and rejects a mismatch before rendering; the Plan 10 builder calls it. |
| Missing-target and truncation rejection | PASS (narrow) | `tests/test_plan10.py`: 2/2 pass; `validate_response` rejects a missing target set and `truncated: true`. |
| P2 input eligibility | PARTIAL | Builder filters a Plan 07 region by its `arm`, but this is only request construction, not an executed paired comparison. |
| No paid provider in tested path | PASS | Only `run_mock` is runnable and emits `provider: mock_local`, `paid_provider_called: false`. |

## Contract failures / missing evidence

| Required property | Result | Independent finding |
|---|---|---|
| Same model, prompt, schema, examples, and caps for P2a/P2b | FAIL / unproved | Requests contain prompt/schema/caps and a boolean `few_shot`, but no model identity or actual example payload.  There is no paired-arm run or assertion that all non-context controls are identical. |
| No cross-arm contamination | FAIL / unproved | Cache key does not contain `arm`; no durable arm-scoped cache or contamination check exists.  A region id may currently differ by arm, but that is an incidental key distinction, not a contract. |
| Cache, resume, and dependency invalidation | FAIL | `run_mock` returns an in-memory list only.  It neither reads prior work nor persists checkpoints, resumes, or invalidates by source/prompt/schema/examples/caps dependencies. |
| Token/request/latency/context-repeat accounting | FAIL | Only requests, estimated input tokens, and local elapsed latency are populated. `output_tokens` is always zero and `context_repeated_chars` is always zero; no actual usage accounting or verification against rendered overlaps exists. |
| Invalid span handling | FAIL / unproved | Rendering inherits the Plan 07 span guard, but the Plan 10 response validator does not validate AU evidence spans/offsets or context-request spans.  The supplied tests do not exercise malformed spans. |
| Missing target / truncation handling | PARTIAL | Target-set and `truncated` handling are covered.  Missing target references during build, malformed response types, duplicate/overlapping AU candidates, and provider partial-output recovery are untested. |
| Rule-vs-model comparison validity | FAIL | No rule baseline, paired scoring definition, comparison artifact, or controls exist.  The mock intentionally emits no semantic extraction, so it cannot support a rule-vs-model claim. |
| `evaluation_against: model_silver` and no gold overclaim | FAIL / absent | `plan10_implementation.md` states this future requirement, but no evaluation artifact carries the field.  Thus there is no executable provenance/evaluation gate; semantic and gold quality remain unassessed. |

## Test execution

- `python -m unittest knowledge_base.pipeline_v1.tests.test_plan10 -v`:
  **PASS, 2 tests**.
- The relevant independent Plan 07 suite began successfully (its first test
  passed and the next test began), but the available 30-second command window
  ended before a final suite status.  Therefore **do not report a full-suite
  PASS** from this validation.
- An attempted broader `tests/test_*.py` discovery produced only progress dots
  before the same time window elapsed, with no final result.  It is recorded as
  **inconclusive**, not passing.

## Interpretation

The initial choice to call this a development-only mock protocol is reasonable,
but it is not yet an experimental baseline.  A better next implementation is
to first make the experiment durable and falsifiable: immutable arm-control
manifest, model/example/cap fingerprints, persisted arm-safe cache/checkpoint
ledger with dependency invalidation, measured accounting, and an explicit
`evaluation_against: model_silver` result schema.  Only after those gates pass
should a real model or rule-vs-model outcome be discussed.  No claim about AU
semantic correctness, human gold, or retrieval quality is supported here.
