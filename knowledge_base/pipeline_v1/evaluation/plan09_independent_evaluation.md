# Plan 09 independent evaluation

Date: 2026-10-05

## Verdict

- Structural/infrastructure: **PASS**.
- Semantic-silver quality: **FAIL (sample audit)**.
- Current workflow state: **PARTIAL / resumable**, not complete. The canonical model-silver set covers 212/369 targets; 157 targets in case `099980` remain missing because the recorded `gpt-5.6-terra` usage limit was reached.
- Plan 10: **LOCKED**. No human gold exists and model silver cannot unlock Plan 10.

These verdicts are intentionally separate. Schema and trace validity do not establish semantic correctness.

## Structural and infrastructure evidence

Independent tests in `evaluation/test_plan09_independent.py` verify:

1. Every canonical proposal passes `validate_model_proposal` against its packet and immutable source text.
2. Producer identity is exactly `model:gpt-5.6-terra`, model `gpt-5.6-terra`, reasoning effort `low`; reviewed targets have review traces and no canonical target has multiple owners.
3. `build_progress(...)` reproduces `reports/plan09_model_silver_progress.latest.json` exactly, including the blocker string and every missing target ID.
4. Counts reproduce as 369 expected, 212 reviewed, 157 missing, 99 AUs, 112 hard negatives, 1 unresolved, and 0 duplicate canonical targets. Only case `099980` is incomplete, with 157 missing targets.
5. An independently constructed overlapping-region fixture is deterministically deduplicated by `_terra_batches`; the lower-sorted region owns the target and the excluded assignment is recorded.
6. The readiness artifact keeps `plan10_allowed=false`, `locked_gold_valid=false`, zero completed human adjudication, and no locked gold snapshot.

Test results:

- Plan 09 independent: 4/4 PASS in 2.074 s.
- Original pipeline regression suite: 105/105 PASS in 77.408 s.
- Independent evaluation suite: 60/60 PASS in 215.853 s.

## Semantic-silver sample audit

Method: a non-statistical evidence review of nine positive targets from the four fully covered cases. The sample included the first and last positive target in canonical order for each complete case (`011904`, `013009`, `013948`, `045155`) plus one targeted attribution-risk item in `013948`. Claims were compared with their exact quoted evidence, `kind`, and speaker attribution. This is a defect-finding audit, not an estimate of precision/recall and not human adjudication.

### P09-S01 — severe attribution and kind error

- Case: `013948`
- Target: `at-3f8c7b00587a03395a1070fa`
- Canonical proposal: `model_proposals/013948/terra-013948-aafb64c3e03c512941a071a8.json`
- Recorded label: `kind=holding`, proposition speaker `current_court`.
- Direct evidence begins: “In other words, Mr. Bayavuge submits that ...”. The stored claim repeats that party submission and then appends “The Board never ruled ...”.
- Assessment: the proposal turns an expressly attributed litigant submission into a current-court holding. This is a severe speaker/attribution error and an unsupported `holding` classification.

Because one clear severe error was found in a small sample, semantic-silver quality does not pass. The remaining sampled items did not expose an equally clear severe error, but that does not validate the other 211 reviewed targets.

## Boundary and required next action

The current artifacts support resumable model-silver production and reproducible bookkeeping only. They do not support a claim of semantic gold, an AU quality score, or Plan 10 readiness. Before any silver lock or downstream semantic use, review at least P09-S01 and run broader independent adjudication focused on party-submission/current-court attribution confusion. Human gold still requires two independent human submissions and adjudication under the existing gate.

No semantic labels were changed during this evaluation. The only implementation artifact added is the independent test file; this report and its JSON summary are evaluation artifacts.
