# Plan09 R4 — 099980 tenth ten missing targets

Ngày 2026-10-06. Provenance gpt-6.1-sol low; model-only, evaluation_against=model_silver. Không Terra output, human gold hoặc independent acceptance.

## Kết quả

Freeze exact 10 ID/order đầu trong 67 missing_target_ids trước khi mở raw source. Six positive targets chứa 8 AU; 4 hard-negative targets; 0 unresolved targets. Target formal judgment chứa ba AU riêng, nên 8 AU không đồng nghĩa 8 positive targets. Reviewed 302 → 312 / 369; missing 67 → 57. Effective totals: 146 AU / 159 hard-negative / 9 unresolved.

Giữ nguyên 302 target cũ và 411 preservation hashes của proposals/sidecars/amendments/risk reviews/registry history/prior batches/reports/R3 artifacts. Ninety R4 manifest records cũ giữ nguyên, chỉ append ten records mới. Không xử lý target thứ 11, không audit, không mở Plan10.

## Exact targets / evidence

Raw case `099980`, SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Offsets half-open trên raw source, không normalize.

| # | Target ID | Full reviewed span | Decision / witness / scope |
|---|---|---|---|
| 1 | at-8f8857880ffb9989ff95d485 | [109086,109511) | AU statutory_hook/current_court, medium uncertainty: FCA remedy discretion và Rule400 costs-factor requirement. Primary last two sentences [109173,109511); Rule400/relevant-matters limit [109419,109510). Không unfettered discretion hoặc awarded amount ở paragraph180. |
| 2 | at-9169a7cb049cf248e5c2ce1a | [6838,7064) | Hard-negative fact_only: relative evidence-strength/seriousness appraisal, không legal proof standard hoặc innocence finding. |
| 3 | at-9225bf8f48de08423b2764aa | [65723,66100) | AU statutory_hook/cited_court, medium uncertainty: CHRC filtering/referral role under CHRA, không determination of rights. Primary full target; CHRA limit [65919,65951). Không transfer role sang PSEA Commission hoặc fairness exemption; 109–113 contextual distinction giữ nguyên. |
| 4 | at-950ed802967a5dd1e6352b4e | [1033,1503) | AU statutory_hook/current_court, medium uncertainty: appointment remedies sau investigation/satisfaction theo ba alternative grounds. Primary full target; investigation [1039,1065), satisfaction [1148,1166), selection-error [1187,1308), political-influence [1340,1417), fraud [1444,1489); permissive remedy limit [1082,1147). Grounds là alternatives, không mandatory AND-gates/automatic revocation/third-party sanction holding. |
| 5 | at-95364ee9fae807cd82176477 | [75879,76253) | AU procedural_rule/current_court, medium uncertainty: section69 exercise justifies greater procedural protection trong fraud/individual-impact context. Primary first sentence [75879,76059); section69 exercise limit [75944,76016). Không invent automatic oral hearing/criminal proof standard. |
| 6 | at-98814cc80cdfb175986f0de4 | [121491,122393) | Three AU: (a) holding/current_court relief+fairness, points1–4 [121494,122024), applicant/affected limits [121699,121803), [121847,121883), [121971,122023); (b) holding/current_court costs point5 [122026,122262), unpaid-$650 condition [122204,122257), deduction limit [122142,122202); (c) procedural_rule/current_court finality point6 [122264,122343), appeal-expiry condition [122307,122342). Disjoint primary spans; exclude editor credit. Không general invalidation, innocence declaration hoặc unconditional/current finality claim. |
| 7 | at-9a77548a0ed859334746f9be | [5168,5691) | Hard-negative fact_only: agency fraud/credibility findings và job/reference facts, không current-court guilt/credibility adjudication hoặc general fraud test. |
| 8 | at-9b01d3f90b10e934c376245e | [26365,26760) | Hard-negative other: dictionary definition reported as investigator source, không distinct adopted court legal definition trong target này. Không infer later paragraph53 never adopts lexical concepts hoặc import its analysis. |
| 9 | at-9c36ec4f176e3085aed6e9c8 | [91381,91714) | Hard-negative fact_only: reference-check/exam/interview/e-mail history, không legal reference rule/court fraud finding. |
| 10 | at-9d5ed1c1ad745b3679a3f919 | [47120,47808) | AU statutory_hook/current_court, medium uncertainty: sections66–68 appointment supervision/remedies. Primary full target; selection-error condition [47521,47657), political-influence alternative [47700,47782); appropriate/public-confidence limit [47457,47520), sections66/67 [47659,47689), section68 [47784,47806). Không final independent third-party power under69; retain reservation. |

Đọc full targets và neighboring raw context ±1200 chars. #3 đọc 109–113; #5 đọc Baker criteria ở97; #6 đọc183–184 và196 để giữ scoped relief/no-innocence reservation; #4/#10 đọc92–93 và183–184. Detailed JSON lưu exact witnesses/context, qualifications, notes và trace/checksums. Eight AU vẫn là model proposals; không suy ra independent acceptance từ formal source hoặc validation PASS.

## Checkpoint / verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-tenth10-sol-v1.json`, có `frozen_before_raw_source_review=true`. Ten immutable single-target proposals + `.validation.json` sidecars trong `r4_model_proposals/099980`. Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_tenth10`; runner dùng persisted checkpoints, không relabel hoặc chọn batch tiếp.

Detailed validation: `outputs/plan09_au_gold_v1/r4_tenth10_validation.json`. Pre-checkpoint source/decision test PASS 1/1 (0.259s); focused R4 batches + R3 completion PASS 26/26 (60.661s). Manifest rebuild PASS, 100 records, `manifest_rebuild_changed=false`; preservation 411/411 hashes; source/span/trace/provenance/duplicate ownership và effective overlays valid. New primary exact duplicates of old AUs: 0; judgment AU spans non-overlapping. R3 acceptance validator vẫn PASS cho cohort cũ, không acceptance cho R4 mới.

Full relevant Plan09 PASS 62/62 (339.935s), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Test results và bound artifact hashes được lưu trong `outputs/plan09_au_gold_v1/r4_tenth10_completion_verification.json`. Contract/test PASS không chứng minh semantic correctness, human gold hoặc retrieval quality. R4 incomplete, R5=false, Plan10 locked.
