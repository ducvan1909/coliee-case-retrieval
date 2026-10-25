# Plan09 R4 — 099980 eighth ten missing targets

Ngày 2026-10-06. Provenance gpt-6.1-sol low; model-only, evaluation_against=model_silver. Không Terra output, human gold hoặc independent acceptance.

## Kết quả

Freeze exact 10 ID/order đầu trong 87 missing_target_ids trước khi mở raw source. Batch: 6 AU / 3 hard-negative / 1 unresolved. Reviewed 282 → 292 / 369; missing 87 → 77. Effective totals: 131 AU / 152 hard-negative / 9 unresolved.

Giữ nguyên 282 target cũ và 363 preservation hashes của proposals/sidecars/amendments/risk reviews/registry history/prior batches/reports/R3 artifacts. Seventy R4 manifest records cũ giữ nguyên, chỉ append ten records mới. Không xử lý target thứ 11, không audit, không mở Plan10.

## Exact targets / evidence

Raw case `099980`, SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Offsets half-open trên raw source, không normalize.

| # | Target ID | Full reviewed span | Decision / witness / scope |
|---|---|---|---|
| 1 | at-77795080c5c4a12d616c23fb | [61977,62376) | AU statutory_hook/current_court, medium uncertainty: commissioner witness compulsion; refusal may lead to contempt/prosecution, không automatic conviction. Primary [62099,62376); called-witness condition [62105,62139), refusal [62240,62289), commissioner limit [62215,62234). Cross-reference 103 [61611,61970) và 107–108 [63306,64708) giữ fair-play/applicable testimony safeguards. |
| 2 | at-7ae2ae96e98fe1711c0bb0c8 | [10166,10761) | Hard-negative fact_only: other investigation/agency fraud findings/reference facts; không Court guilt finding hoặc general reference-entitlement rule. |
| 3 | at-7c2438bcce27682cdd68ac16 | [62385,62946) | AU procedural_rule/current_court: investigative means phải respect legitimate expectations regardless procedure chosen, trong Commission fraud/compulsion context. Primary second sentence [62687,62946), such-case limit [62821,62835). Không apply mọi investigation/body hoặc tự động bốn remedies. |
| 4 | at-7ca139c74013a440ec1f9b58 | [105383,105458) | Unresolved: anaphoric confirmation + heading; underlying draft-comment proposition nằm paragraph 173. Distinct AU vs confirmation/duplicate cross-reference eligibility chưa rõ; không forced AU hoặc editorial negative. |
| 5 | at-7d8a081b1e141c63b05c04f0 | [60065,60464) | AU statutory_hook/current_court, medium uncertainty: potential fraud disqualification/revocation tùy appointment stage. Primary first sentence [60065,60349); ongoing-process condition [60228,60275), appointed condition [60309,60348), could-lead limit [60171,60184). Không automatic penalty hoặc unconditional investigation duty; giữ riêng requires-investigate paraphrase và may-investigate quotation ở 48, chưa adjudicate quan hệ giữa hai wording. |
| 6 | at-7e7fcd55dcd3ac2c48651d45 | [22324,22864) | AU procedural_rule/current_court, medium uncertainty: conditional objective explanation of decision/jurisdiction/powers. Primary [22324,22515), as-long-as condition [22354,22514); cross-references 43 [21574,22318) và 45–46 [22866,23847). Không unrestricted merits/fairness advocacy hoặc adoption of nested jurisdiction dictum. |
| 7 | at-80dd855d64256453a585304d | [35375,36847) | AU procedural_rule/commission_policy, medium uncertainty: Policy investigation-consideration list, không court/statutory rule hoặc mandatory AND-gates. Primary [35550,36847); decision-context condition [35575,35622); participant-time limit [36288,36383), other-means limit [36554,36572); extension exception [36385,36494), non-six-month exception [36623,36703). Exclude reported-notice compliance as proof actual compliance. |
| 8 | at-82b9a66eda69a6ecd5efa988 | [32229,32806) | AU standard_of_review/current_court, medium uncertainty: conditional defensible-in-facts-and-law inquiry. Primary [32519,32806), actual-third-party-jurisdiction assumption [32519,32620), applicant-fraud-finding limit [32656,32702). 93/183–184 reserve final ruling; không actual jurisdiction/reasonableness outcome, universal standard hoặc production-motion rule. |
| 9 | at-848aa7019c8e57579343e4c6 | [81876,82497) | Hard-negative fact_only: actual questioning/oath/compulsion format và announced two-report plan, không universal two-report duty hoặc distinct general compulsion rule. |
| 10 | at-84d29312a5bc05be38261afa | [103497,104077) | Hard-negative fact_only: approval note/final-report factual contrasts, không general finality rule hoặc imported draft-comment proposition. |

Đọc full targets và neighboring raw context ±1200 chars. #1 đọc full 103–108; #4 đọc 173–174; #5 đọc section 69 quotation ở 48; #6 đọc 43–46; #8 đọc 92–93 và 183–184. Detailed JSON lưu exact witnesses/context, qualifications, notes, trace/checksums và unresolved reason. Không suy ra no-AU từ status/budget/missing citation; không sửa label cũ.

## Checkpoint / verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-eighth10-sol-v1.json`, có `frozen_before_raw_source_review=true`. Ten immutable single-target proposals + `.validation.json` sidecars trong `r4_model_proposals/099980`. Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_eighth10`; runner dùng persisted checkpoints, không relabel hoặc chọn batch tiếp.

Detailed validation: `outputs/plan09_au_gold_v1/r4_eighth10_validation.json`. Pre-checkpoint source/decision test PASS 1/1 (0.235s); focused R4 batches + R3 completion PASS 22/22 (44.725s). Manifest rebuild PASS, 80 records, `manifest_rebuild_changed=false`; preservation 363/363 hashes; source/span/trace/provenance/duplicate ownership và effective overlays valid. R3 acceptance validator vẫn PASS cho cohort cũ, không acceptance cho R4 mới.

Full relevant Plan09 PASS 58/58 (321.755s), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Test results và bound artifact hashes được lưu trong `outputs/plan09_au_gold_v1/r4_eighth10_completion_verification.json`. Contract/test PASS không chứng minh semantic correctness, human gold hoặc retrieval quality. R4 incomplete, R5=false, Plan10 locked.
