# Plan09 R4 — 099980 eleventh ten missing targets

Ngày 2026-10-06. Provenance gpt-6.1-sol low; model-only, evaluation_against=model_silver. Không Terra output, human gold hoặc independent acceptance.

Freeze exact 10 ID/order đầu trong 57 missing trước raw-source review. Batch 3 AU / 6 hard-negative / 1 unresolved. Reviewed 312 → 322 / 369; missing 57 → 47. Effective totals 149 AU / 165 hard-negative / 10 unresolved (unit counts không đồng nghĩa target counts).

312 target cũ, R3 acceptance và 435 preservation hashes giữ nguyên. One hundred R4 records cũ không đổi, append ten records mới. Không target thứ 11, không audit, R5=false, Plan10 locked.

## Exact source decisions

Case `099980`, raw SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`; half-open offsets, không normalize.

| # | Target ID | Full span | Outcome / witness / scope |
|---|---|---|---|
| 1 | at-9da27af39832dc60e64122b4 | [15949,16381) | Hard-negative fact_only: hypothetical practical-effect/appointment outcome explanation trong argument context, không rule fraud luôn cần actual appointment effect. Exclude heading. |
| 2 | at-a41b1c3147bae9ad5c1f0e11 | [110576,111282) | AU holding/current_court, medium uncertainty: scoped decision không final jurisdiction/reasonableness ruling. Primary I-have-decided clause [111177,111282); subject limit [110929,111009), these-issues limit [111266,111281); paragraph184 confirmation cross-reference. Không lack-of-jurisdiction determination hoặc universal bar on deciding. |
| 3 | at-a7039ffbcf81acfdf39a03bc | [25742,26097) | Hard-negative editorial: Rousseau philosophical quotation, không statutory/court fraud-elements test. |
| 4 | at-a717d9e338c80464e87d585c | [4697,5160) | Hard-negative fact_only: DNR/PWGSC participation/submissions facts, không general employer participation/report entitlement. |
| 5 | at-a8d96590034d4f26937d6ac4 | [22,540) | AU statutory_hook/current_court: PSEA federal appointments based on merit/non-partisanship. Primary [52,300); federal-service limit [87,120). Exclude judge/translation metadata và next private-sector honesty expectation; không automatic fraud finding. |
| 6 | at-aa407c31bddfef792959ec7e | [6332,6830) | Hard-negative fact_only: reference quality/authorship/e-mail corroboration, không court guilt hoặc fraud test. |
| 7 | at-aad011c3eeb3d5201e016a63 | [100923,101308) | Hard-negative party_argument_only: respondent memorandum quoted opportunities to comment. Skilfully insists không fairness-satisfaction adoption; next169 addresses omitted final-analysis issue. |
| 8 | at-affded0df7852c0f341cd3b6 | [98124,98859) | Unresolved: possible double-standard impression/one-may-wonder bias observation, không settled bias finding/complete threshold. Full paragraph186 context also says apprehensions one may have. Eligibility/kind uncertainty, không forced holding hoặc fact-only negative. |
| 9 | at-b0d26b01c226af7bf286f860 | [105467,105829) | Hard-negative procedural_history_only: corrective-action phase/agency inflexibility sau agency fraud finding, không court confirmation of guilt hoặc universal no-cure rule. |
| 10 | at-b16418abd94e0e3822932535 | [45604,46316) | AU statutory_hook/current_court: PSDPA Commissioner/Tribunal role allocation. Primary final sentence [46069,46316); protected-disclosure limit [46278,46315). Không transfer role sang PSEA Commission hoặc establish applicant recourse. |

Đọc full targets + neighboring raw context ±1200 chars. #2 đọc full92–93 và183–184; #8 đọc186. Detailed validation JSON lưu exact source/context/field witnesses, notes, unresolved reason và trace/checksums. AU vẫn là model proposals pending independent semantic review.

## Checkpoint and verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-eleventh10-sol-v1.json`, `frozen_before_raw_source_review=true`. Ten immutable proposals + ten `.validation.json` sidecars. Resume `python -m knowledge_base.pipeline_v1.review_plan09_r4_eleventh10`; persisted checkpoints được reused, không relabel/select batch tiếp.

Detailed report: `outputs/plan09_au_gold_v1/r4_eleventh10_validation.json`. Pre-checkpoint decisions PASS 1/1 (0.265s). Manifest rebuild PASS, 110 records, `manifest_rebuild_changed=false`; preservation 435/435; all proposals/effective overlays and ownership/source/span/trace/provenance valid. Exact new primary duplicates of old AU spans: 0. R3 validator PASS chỉ cho accepted cohort cũ.

Focused R4 batches + R3 completion PASS 28/28 (74.818s). Full Plan09 PASS 64/64 (357.218s), command: `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Completion verification: `outputs/plan09_au_gold_v1/r4_eleventh10_completion_verification.json`. Contract/test PASS không chứng minh semantic correctness, human gold hoặc retrieval quality. R4 incomplete; R5=false; Plan10 locked.
