# Plan09 R4 — 099980 seventh ten missing targets

Ngày 2026-10-06. Provenance gpt-6.1-sol low; model-only, evaluation_against=model_silver. Không Terra output, human gold hoặc independent acceptance.

## Kết quả

Freeze exact 10 ID/order đầu trong 97 missing_target_ids **trước khi mở raw source**. Batch: 4 AU / 5 hard-negative / 1 unresolved. Reviewed 272 → 282 / 369; missing 97 → 87. Effective totals: 125 AU / 149 hard-negative / 8 unresolved.

Giữ nguyên 272 target cũ và 339 preservation hashes của proposals/sidecars/amendments/risk reviews/registry history/prior batches/reports/R3 artifacts. Sixty R4 manifest records cũ giữ nguyên, chỉ append ten records mới. Không xử lý target thứ 11, không audit, không mở Plan10.

## Exact targets / evidence

Raw case `099980`, SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Offsets half-open trên raw source, không normalize.

| # | Target ID | Full reviewed span | Decision / witness / scope |
|---|---|---|---|
| 1 | at-630e5b3107f31ec30d483195 | [81455,81867) | Hard-negative fact_only: candidate notice/representation information và applicant exclusion facts; không general court representation right hoặc adopted investigator-choice rule. Không import paragraph 136 conclusion. |
| 2 | at-67a28257657db209f376306f | [106181,106845) | Hard-negative party_argument_only: counsel fairness/remedy complaints và applicant innocence/supervision account; eloquently không phải adoption. |
| 3 | at-681c23ac14ba9fb3033bec0a | [25303,25734) | AU procedural_rule/commission_policy, medium uncertainty: investigate/not-investigate decision discretionary/case-by-case theo Policy. Primary [25303,25718); investigation-decision limit [25604,25653), case-by-case limit [25694,25717); paragraph 65 policy-factor cross-reference [35369,36849). Không court holding/statutory command/unrestricted discretion; exclude heading. |
| 4 | at-69b26fc821f7b89ea6c8ff88 | [15486,15941) | Hard-negative party_argument_only: alternative no-personal-gain reasonableness argument và reported evidence contrasts; không mandatory fraud-element holding. |
| 5 | at-6a766cf8a9d8a233e4056107 | [23853,24457) | Hard-negative party_argument_only: applicant jurisdiction objection vs respondent powers/reasonableness defence; court chưa adopt bên nào trong span. |
| 6 | at-6b416be133c2ad82afda7242 | [77199,77449) | Hard-negative fact_only: case-specific credibility/affidavit acceptance; không general credibility/fairness test hoặc fact_pattern_rule. |
| 7 | at-6dccd1f10e05f9a2f1159ec6 | [49426,50120) | Unresolved: nested Seck reasoning/respondent submissions/Commission position + court stakeholder-consistency doubt. Chưa đủ clear adoption of reusable integrity/no-effect rule; 93/183–184 reserve jurisdiction/reasonableness. Không forced AU hoặc hard-negative. |
| 8 | at-706534560fc7a1f24d660294 | [69013,69900) | AU holding/current_court: hai judgments respondent viện dẫn không apply trong case này. Primary first sentence [69013,69213); case limit [69200,69212). Suppressed names giữ nguyên; không categorical inapplicability của mọi CHRC precedent hoặc resource presumption. |
| 9 | at-73614cc48a493ce944b21023 | [34437,34851) | AU procedural_rule/current_court, medium uncertainty: sequencing trước fraud-reasonableness assessment cần satisfied về third-party jurisdiction. Primary [34437,34664); before-assessment limit [34446,34507), third-party limit [34576,34603). Không kết luận có/không jurisdiction, không universal review standard. |
| 10 | at-754e1b56d19dc114d5bbceca | [111291,111809) | AU holding/current_court: declaration scope chỉ applicant và affected fraud/corrective-action decision/report. Primary full paragraph; applicant limit [111523,111564), affected-scope limit [111709,111808); express no-jurisdiction/reasonableness declaration exclusion [111291,111425). Không invalidate mọi public servant hoặc substantive jurisdiction holding. |

Đọc full targets và neighboring raw context ±1200 chars. #3 đọc paragraph 65; #7/#9 đọc full paragraphs 92–93 và 183–184; #8 đọc paragraphs 100–113 để phân biệt nested cited-court quote với direct court response. Detailed JSON lưu exact witnesses/context, qualifications, notes, trace/checksums và unresolved reason. Không suy ra no-AU từ status/budget/missing citation.

## Checkpoint / verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-seventh10-sol-v1.json`, có `frozen_before_raw_source_review=true`. Ten immutable single-target proposals + `.validation.json` sidecars trong `r4_model_proposals/099980`. Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_seventh10`; runner dùng persisted checkpoints, không relabel hoặc chọn batch tiếp.

Detailed validation: `outputs/plan09_au_gold_v1/r4_seventh10_validation.json`. Pre-checkpoint source/decision test PASS 1/1 (0.214s); focused R4 batches + R3 completion PASS 20/20 (37.756s). Manifest rebuild PASS, 70 records, `manifest_rebuild_changed=false`; preservation 339/339 hashes; source/span/trace/provenance/duplicate ownership và effective overlays valid. R3 acceptance validator vẫn PASS cho cohort cũ, không acceptance cho R4 mới.

Full relevant Plan09 PASS 56/56 (309.720s), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Test results và bound artifact hashes được lưu trong `outputs/plan09_au_gold_v1/r4_seventh10_completion_verification.json`. Contract/test PASS không chứng minh semantic correctness, human gold hoặc retrieval quality. R4 incomplete, R5=false, Plan10 locked.
