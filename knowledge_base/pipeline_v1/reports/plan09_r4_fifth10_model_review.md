# Plan09 R4 — 099980 fifth ten missing targets

Ngày 2026-10-06. Provenance gpt-6.1-sol low; model-only/model-silver, không phải Terra output hoặc independent acceptance.

## Kết quả

Đúng 10 ID đầu trong 117 missing_target_ids trước batch. Batch: 3 AU / 6 hard-negative / 1 unresolved. Reviewed 252 → 262 / 369; missing 117 → 107. Effective totals: 114 AU / 142 hard-negative / 6 unresolved.

Giữ nguyên 252 target cũ và 291 preservation hashes của proposals/sidecars/amendments/risk reviews/registry history/prior batches/reports/R3 artifacts. Forty R4 manifest records cũ giữ nguyên, append ten records mới. Không xử lý target thứ 11; không audit hoặc mở Plan10.

## Exact targets / evidence

Raw case `099980`, SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Offsets half-open trên raw source, không normalize.

| # | Target ID | Full reviewed span | Decision / evidence / qualification |
|---|---|---|---|
| 1 | at-3c30af827186591d2bf66be2 | [22872,23361) | AU procedural_rule/current_court. Primary [23174,23361): respondent không được argue thay Commission rằng fairness được tôn trọng **in this case**. Paragraph 46 cross-reference giữ ngoại lệ thực tế: court vẫn xem arguments vì applicant không phản đối, có reservation về remedies/costs. Không biến borderline reasonableness advocacy thành primary rule. |
| 2 | at-3e39044f97b84404b520022e | [56769,57487) | Hard-negative party_argument_only: applicant notice/disclosure/fairness arguments; later agreement không đổi speaker của span. |
| 3 | at-3e97359dc0a6d7669025040b | [104086,104753) | Hard-negative fact_only: cấu trúc report/new allegations/agency guilt finding, không Court conviction hoặc rule mới. |
| 4 | at-41ba0116a63ebb7c839e9149 | [54817,55458) | Hard-negative party_argument_only: applicant conjunction/ancillary-power argument; tentative response ở 92 và reservation ở 93 không phải final adoption. |
| 5 | at-422fbd7f49cb2cff502c7399 | [90733,91372) | AU holding/current_court. Primary [90733,90938): bác respondent suggestion rằng procedure của investigator phù hợp legitimate expectations của người bị nghi fraud; scoped to this investigation, không general investigator-motive rule. |
| 6 | at-4751d840ca72860653e65cd8 | [78112,78583) | Hard-negative fact_only: supervisor/job facts và thiếu liên hệ managers; không universal manager-interview duty. |
| 7 | at-47a655a27ed5534b3a17e956 | [89950,90724) | AU holding/current_court, medium uncertainty. Chỉ primary [90595,90724) là lời court bác truncated argument; ba câu respondent trước đó không phải court witness. Claim giới hạn rejection of no-prejudice/cure argument cho notice này; cross-reference court response [90733,90938), không universal no-cure rule. |
| 8 | at-49def3d233262fffd76bbd5a | [1510,1929) | Hard-negative fact_only: introductory impugned agency decision, không Court guilt finding. |
| 9 | at-49ed1261d578f869e56746d2 | [52348,53106) | Hard-negative fact_only: DNR facts và why-not-referral question; không binding ReviewTeam recommendation. |
| 10 | at-4b1f384513ca1b440639bff3 | [42842,43448) | Unresolved: court distancing from Seck1/questioning jurisdiction-standard chưa thành final ruling. Paragraph 93 giữ reservation; không forced AU hoặc negative. |

Đọc full targets và neighboring raw context ±1200 chars; đọc thêm full paragraphs 92–93 cho reservation. Detailed JSON lưu exact primary/context witnesses, field qualifications, notes, trace/checksums và unresolved reason. AU là model proposals, chưa semantic gold.

## Checkpoint / verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-fifth10-sol-v1.json`. Ten immutable single-target proposals + `.validation.json` sidecars trong `r4_model_proposals/099980`. Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_fifth10`; runner dùng persisted checkpoints, không relabel hoặc tự chọn batch tiếp.

Detailed validation: `outputs/plan09_au_gold_v1/r4_fifth10_validation.json`. Pre-checkpoint source/decision test PASS 1/1 (0.203s); focused R4 batches + R3 completion PASS 16/16 (25.008s). Manifest rebuild PASS, 50 records, `manifest_rebuild_changed=false`; preservation 291/291 hashes; all proposals/effective overlays valid. R3 acceptance validator vẫn PASS cho cohort cũ, không audit-acceptance cho R4 mới.

Full relevant Plan09 PASS 52/52 (289.382s), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Test result và bound artifact hashes được lưu trong `outputs/plan09_au_gold_v1/r4_fifth10_completion_verification.json`. Contract/test PASS không chứng minh semantic correctness, human gold hoặc retrieval quality. R4 incomplete, R5 chưa PASS, Plan10 false.
