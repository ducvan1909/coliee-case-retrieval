# M3 local validation report

Date: 2026-11-06  
Checkout: `E:/Git/coliee-case-retrieval`  
Scope: independent local tests of M3 pilot/retrieval code. No production code was edited by the tester.

## Result

**Local tests pass with documented limits.** The final targeted M3 set contains **39 tests; 39 passed**. The full `pipeline_v2/tests` set contains **104 tests; 104 passed**. The tested code snapshot is bound by aggregate implementation SHA-256 `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63` (hash over the per-file map from `retrieval.common.implementation()`).

The accepted input contract is pinned to `pipeline_v2/artifacts/m2_passages_20261106_v1`, seal SHA-256 `0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6`. Model/tokenizer contract: `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`, 2,560 dimensions, 448-token cap.

## Command and result

```powershell
.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m3_retrieval_core pipeline_v2.tests.test_m3_cache pipeline_v2.tests.test_m3_corpus pipeline_v2.tests.test_m3_qdrant pipeline_v2.tests.test_m3_runtime pipeline_v2.tests.test_m3_pilot pipeline_v2.tests.test_m3_resume pipeline_v2.tests.test_m3_profile pipeline_v2.tests.test_m3_preflight -v
```

Result: `Ran 39 tests ... OK`.

The full existing M0–M3 suite was also run once after production freeze:

```powershell
.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v
```

Result: `Ran 104 tests in 16.186s ... OK` (65 earlier M0–M2 checks plus the 39 M3 checks).

Coverage includes Unicode/citation token handling and negation in BM25; one-vote-per-case RRF; source/passage mappings; vector shape, finiteness and normalization; cache identity, corruption and recovery; attempt accounting; transient retry versus permanent fail-fast; local tokenizer and remote response parity; raw document text versus query instruction; model/profile/code drift; exact token/padding/latency receipt checks; pilot sample determinism; Qdrant request protocol, point membership and source hash checks; unique tie-aware dense reference results; run-lock contention; resume without re-embedding committed batches; corrupt cache fail-stop; accepted M2 bundle/seal pinning; and invalidation of a previous successful preflight when a rerun fails.

During independent review, regressions found and fixed before the final run were: malformed vectors reaching Qdrant writes; duplicate dense hits and duplicate manifest IDs accepted as a successful reference check; run-lock contention leaking a raw SQLite error; source bundle/seal not pinned before planning; malformed padding/latency receipts accepted; case-level BM25 ignoring profile parameters; and a prior successful preflight remaining usable during a rerun. Those defects no longer reproduce in the final targeted run.

The initially failing regression commands and counts are retained in `pipeline_v2/reviews/m3_local_validation_v1/test_attempts.json`; these were intentional tests against defects or temporary fixture mismatches, not failures of the final suite. The final frozen-code test receipts are `39/39` targeted M3 and `104/104` full `pipeline_v2/tests`; exact commands and full-suite runtime are recorded above.

## Limits

- Qdrant was exercised through an injected HTTP mock only. This is a protocol/unit result, **not** evidence that Docker or a real Qdrant server works.
- Embedding was exercised with the pinned local tokenizer and synthetic response vectors. No Modal request, deployment, model weights download, or inference ran.
- No 1,024-passage embedding pilot or full-corpus indexing was performed. The accepted-corpus selection plan was run locally and independently audited below. M3 planning/audit did not read labels or run the evaluator. The full test-directory run includes an existing M0 structural test that checks a reserved/exposed gold-ID classification; no label-scoring or evaluator run occurred. Resource/latency measurements, embedding, Docker/Qdrant, and remote runtime gates remain unrun. This report makes no claim about retrieval quality, legal semantics, or COLIEE scores.
- The seeded sampling helper was unit-tested on synthetic passages; its selected manifest was audited against the sealed M2 records and raw sources, but the selector was not independently rerun over all 415,693 passages.

## Accepted M2 plan: independent audit

Main ran the frozen CLI locally on the accepted M2 bundle:

```powershell
.venv/Scripts/python.exe -m pipeline_v2.m3 plan --repo-root . --output pipeline_v2/artifacts/m3_pilot_20261106_v1
```

Receipt: `pipeline_v2/reviews/m3_local_validation_v1/real_m2_plan_receipt.json`. It exited 0 in 241.274 seconds, planned 1,024 passages, and recorded zero remote requests. Result: `planned_not_executed`; collection name reserved in the manifest, no collection was created.

I independently audited the plan with a standalone script that does not import M3 builders/readers:

```powershell
.venv/Scripts/python.exe pipeline_v2/reviews/m3_local_validation_v1/audit_real_plan.py
```

Audit result: **PASS**. It verified the run-manifest seal; pinned profile and accepted M2/navigation seal hashes; current production file hashes; 1,024 unique passage IDs and ordered input hashes; 916 corresponding raw source hashes and sealed M2/navigation case records; raw byte spans and exact text hashes; and all 1,024 token counts/EOS IDs with the pinned tokenizer. Recomputed strata matched the manifest: 105 split passages, 161 Unicode passages, and 1 without a navigation preview. Token count stats: min 2, median 103, mean 129.73, max 448. Selected cases contain 1–5 passages each (mean 1.118).

The first audit-script attempt looked for `navigation_bundle` in `m3.json`; that setting is in `m3_user_selection.json`. The script was corrected, then strengthened to verify the M2-manifest-to-navigation-seal chain and rerun successfully. This was a checker issue, not a plan or source defect; all attempts and the final receipt are preserved in `pipeline_v2/reviews/m3_local_validation_v1/audit_attempts.json`.

This establishes provenance and plan integrity for the selected 1,024 passages only. It does not independently resample all 415,693 passages, assess retrieval quality, or establish embedding/runtime correctness.
