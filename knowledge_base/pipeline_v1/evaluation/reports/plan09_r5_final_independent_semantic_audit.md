# P09-R5 final independent semantic audit

**Verdict: PASS — model-silver scope only.**

The effective state audited was 369/369 targets: 188 AuthorityUnits, 186 hard negatives, and 8 unresolved. No canonical proposal, amendment, queue, progress, coverage, or gate artifact was modified.

## Frozen review scope

The sample was frozen before raw review in `plan09_r5_final_independent_semantic_audit.sample_manifest.json` (SHA-256 `e4138bbdbb80e27be607000707aac8328ca374ead22317c75d9bd564d87e85d2`).

- Positives: 38 targets / 38 AUs, or 20.21% of all 188 AUs, stratified across every observed case-kind stratum in the sample.
- Hard negatives: 30 targets, or 16.13% of all 186 hard negatives, selected court/reporting-cue-first and then by deterministic SHA-256 order.
- Unresolved: 8/8, reviewed against raw source with surrounding context.
- Attribution-risk queue: 49/49.
- R3 amendment/acceptance chain: 100% of the physical amendment set and all current review heads.

This is an error-finding audit, not a precision/recall estimate.

## Semantic result

No severe, high, or moderate defect was found. Consequently, no stratum required expansion to 100%.

| Defect class | Open findings |
|---|---:|
| Attribution | 0 |
| Wrong kind | 0 |
| Lost condition, exception, or limit | 0 |
| Evidence-span error | 0 |
| Omission in reviewed scope | 0 |
| Duplicate or coverage error | 0 |

All eight unresolved items remain justified. They involve conflicting jurisprudence, suppressed citation boundaries, mixed speakers, tentative judicial language, hypothetical conflict, reserved jurisdiction questions, or a non-standalone confirming sentence. Forcing them to positive or hard-negative would overstate the raw source.

The positive sample preserved speaker and scope. The hard-negative sample included high-risk court/reporting language and did not promote party arguments, agency positions, case facts, procedural history, headings, or non-standalone rhetoric merely because they occur in reasons for judgment.

## R3 and R4 chain

- R3: 49/49 attribution-risk items reviewed; zero pending; 49 current risk-review heads; 54 physical review files; 42 physical amendment files; all current heads/amendments valid; zero open severe findings. `r3_completion.json` remains PASS and its post-R4 verification is valid.
- R4: 16/16 batch audits cover all 157 appended targets. Recomputed frozen-batch, proposal, and validation-sidecar hashes produced zero mismatch.
- The original `fourth10` audit rejected two moderate defects. The correction re-audit independently accepted both corrections (`pass_corrections_accepted`).
- Final coverage binds 417 artifacts; all 417 exist and match SHA-256. Coverage is 369/369 with zero missing targets and zero canonical duplicate owners.

## Historical sidecar limitation

There are 17 historical Terra proposal files without persisted validation sidecars. All 17 have fresh validation PASS recorded by the coverage artifact, their originals remain unchanged, and this audit did not create backfilled sidecars. This is disclosed because fresh structural validation is not equivalent to a historical sidecar and is not semantic proof by itself.

## Test qualification

A focused run produced 9 passes and 3 failures. The failures are stale assertions in `test_plan09_remediation_independent.py`: they still require the earlier 212-target state, `P09-S01` to remain quarantined, and the original R3 replacement to remain unresolved. Those expectations conflict with the completed, hash-bound R3/R4 state. They are reported as test-state drift, not hidden and not used as evidence of semantic PASS.

## Boundary and gate decision

P09-R5 passes only for the Plan 09 model-silver development scope. The result does **not** create human gold, does not estimate corpus precision/recall, and does not validate retrieval quality. Under the plan, the separate P09-R6 use decision is still required; this audit did not edit or self-open the Plan 10 gate.
