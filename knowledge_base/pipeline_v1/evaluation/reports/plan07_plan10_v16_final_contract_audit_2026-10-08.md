# Plan07 / Plan10 v1.6 final contract audit

Date: 2026-10-08  
Scope: local source, current Plan07 pointer/artifacts, and focused tests. No Modal call; no production-code edit.  
Verdict: **PASS for the stated structural/runtime contract; no semantic-effect claim.**

## Evidence checked

The current Plan07 report pointer is a local `status=pass` report whose output root and build manifest both exist. The referenced build uses scheduler `p2-offline-scheduler-v1.6` and a coherent policy hash. Rebuilding Plan10 locked requests from that pointer produced 96 P2a and 96 P2b requests and 96 `(case_id, batch_id)` pairs.

Independent pair checks found:

| Invariant | Result |
|---|---:|
| base-render SHA mismatch | 0 / 96 |
| rendered source-span-list mismatch | 0 / 96 |
| P2a request with non-empty hint payload | 0 |
| P2b request with hint IDs | 11 |
| P2b hint IDs total | 16 |
| paired experiment count | 96 |

The checked Plan07 report additionally records zero displaced P2a context spans/chars and zero newly inserted P2b source-context spans/chars. The renderer now derives `render_base_region` from the same `render_items` while neutralizing arm/region labels, so equality means the source body, span sequence, and source-span order are shared; it is not merely an equality of target IDs.

## Contract findings

### Base source context and separate hint payload — PASS

`build_locked_requests` renders P2a/P2b through `render_base_region`, stores `base_render_sha256`, and `paired_experiment` rejects a pair if target IDs, base-render SHA, P2a empty payload, or P2b payload integrity differ. `prompt_for` includes `CONTEXT_HINT_PAYLOAD` separately from `REGION`; the hint payload does not alter source spans. The new paired-control labels accurately state same case/batch/target/base-render source context and separate P2b payload, replacing the earlier incorrect same-region claim.

### Duplicate fail-closed — PASS

Before any provider operation, `build_locked_requests` rejects a duplicate `(case_id, target_id)` across requests. `paired_experiment` separately rejects duplicate pair keys or request IDs. Focused tests mutate a duplicate target and duplicate request, and both are rejected. The current workload has 369 unique target IDs per arm.

### HTTP 200 then host-validation accounting — PASS

The earlier loss of provider usage has been repaired in the relevant path. After `call_modal` returns, `execute_remote` removes raw response content but retains the safe receipt. A subsequent `validate_response` failure now yields `unresolved` with `failure_diagnostic.kind=host_validation` while preserving provider `usage`, provider finish reason, and latency. The dedicated test uses an HTTP-200 response with usage `{7,8,15}` and asserts those exact values survive schema validation failure.

This repair is prospective. It does not recover the 25 discarded usage receipts in the already-written `plan10_pair_20261008_142127` artifact; that artifact remains only a lower-bound usage record, as documented in the earlier v16 audit.

## Tests

```
python -m unittest knowledge_base.pipeline_v1.tests.test_plan07 knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 48 tests ... OK
```

The run includes exact paired base source render/order tests, source/order mutation rejection, duplicate request/target rejection, and the post-HTTP-200 host-validation usage preservation test.

## Semantic limitation

The implementation proves a clean experimental *input boundary*, not that P2b has useful semantic hint information. Its P2b payload currently contains `version` plus opaque `hint_ids`; prompt content does not include the corresponding hint text, relation, cited span, or resolver data. A model cannot derive the legal/content meaning of an opaque ID from the supplied source region alone. Therefore a future P2a/P2b difference would measure the effect of adding those identifiers (and possibly their count), not established ContextHint content utility.

Likewise, Plan07 structural PASS and unit-test PASS do not validate AU semantic correctness, hint usefulness, retrieval quality, or end-to-end model quality. Those require an explicitly defined informative payload and a held-out/adjudicated evaluation gate.
