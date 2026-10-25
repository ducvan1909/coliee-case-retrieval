# Plan09 R4 — 099980 first ten missing targets

Ngày 2026-10-05. Reviewer lane/provenance: gpt-6.1-sol low, model-only/model-silver. Chưa independent acceptance, chưa R5. Đây là `ModelAUProposal`, không phải Terra output.

## Kết quả trực tiếp

Đúng 10 target đầu trong `missing_target_ids` của progress trước batch, giữ thứ tự ổn định: 4 AU / 6 hard-negative / 0 unresolved. Reviewed coverage tăng 212 → 222 / 369; missing giảm đúng 157 → 147. Effective totals: 102 AU / 119 hard negatives / 1 unresolved.

Các proposal/review/amendment của 212 target cũ, Terra manifest, 49-item R3 risk queue, semantic registry và `r3_completion.json` giữ nguyên hash. R3 PASS chỉ áp dụng accepted cohort cũ; 10 R4 targets mới chưa thuộc independent acceptance đó. Plan10 vẫn false, R4 coverage incomplete và R5 chưa PASS.

## Exact decisions / evidence

Source case `099980`, SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Offsets là raw half-open `[start,end)`, không normalize quotes/encoding.

| # | Target ID | Full reviewed target | Decision và primary evidence |
|---|---|---|---|
| 1 | at-002724763909ed3cbd562979 | [63313,64078) | AU procedural_rule, current_court; fair-play khi cưỡng chế người bị nghi fraud khai. Primary [63563,63812); explicit condition [63602,63724). |
| 2 | at-04bf386d8c5d925091d491c6 | [37267,37777) | Hard-negative `fact_only`: lý do mở điều tra/Policy appraisal; không nhập lời investigator paragraph 68 thành holding. |
| 3 | at-054dfde5d03691a3ecdf1850 | [76262,76858) | AU holding, current_court; thủ tục điều tra của Commission seriously flawed sau Baker analysis. Primary [76262,76557); investigation-phase limit [76375,76453). Bỏ heading cuối. |
| 4 | at-057d175123c3feeaa748a894 | [106854,108312) | Hard-negative `procedural_history_only`: court giới thiệu memo rồi quoted agency defence, không phải court adoption. Court response paragraph 179 được review riêng ở #9. |
| 5 | at-05b0930b0c23a8bd764d4430 | [76867,77190) | Hard-negative `fact_only`: sworn evidence/certified record inventory. |
| 6 | at-05ddb4f2a8aa0a4312eef8e3 | [5699,6324) | Hard-negative `fact_only`: reference-checking events, không phải rule. |
| 7 | at-0875297b672250b6552a1a4c | [116267,116777) | AU case-specific holding, current_court; public-interest consideration of irreparable harm trong costs discretion. Primary [116391,116628); paragraph 190 cross-support [114449,115300); case/harm limit [114936,115004). Không suy ra compensation rule phổ quát. |
| 8 | at-09d62c9c1e03e472ef963e5c | [40959,41627) | Hard-negative `party_argument_only`: applicant xin khác Seck 1, không court adoption. |
| 9 | at-0b86a942dd15b6bbbe7e3baa | [108321,109039) | AU holding, current_court; flagrant procedural-fairness breach in this applicant's case. Primary chỉ [108321,108391), case limit [108367,108390), không agency/party witnesses. |
| 10 | at-0be8a81021550bf6fad9cdb2 | [70779,71011) | Hard-negative `fact_only`: employment/advancement impacts, không phải rule hợp pháp hóa permission condition. |

Mỗi target được đọc full span và neighboring context; #7 mở rộng tới toàn paragraph 190 để xác định scope costs. Claim text, exact quotes, source hashes, context spans, field-level witnesses, notes và trace/checksums có trong detailed JSON.

## Minimal append / crash resume

Legacy checkpoint nhận đúng Terra identity và region batch, nên không dùng để gắn nhãn gpt-6.1-sol. Thêm schema riêng và `au_gold/r4.py`, tái dùng exact-source/trace/owner/field validator mà không thay provenance canonical records. Không đổi Terra contract.

Frozen batch `r4_batches/p09-r4-099980-first10-sol-v1.json` giữ selected IDs, original progress và preservation hashes. Mỗi target có immutable proposal + validation sidecar riêng; manifest commit atomic, duplicate ownership guard; nếu crash sau proposal trước manifest, resume revalidate/reconcile durable bytes thay vì relabel. Nếu file đã tồn tại nhưng decision khác, reject; không overwrite. Workflow dùng một writer tuần tự, không tuyên bố multi-process transaction support.

R4 manifest riêng được ghép vào `effective_proposals` và progress; Terra manifest/R3 scanner cohort giữ nguyên. `ModelAUProposal` chưa thể dùng Terra-only silver-lock contract; mixed-model lock bị chặn. R4 proposals đều pending independent audit, không dùng để tự mở R5/Plan10.

## Artifacts / reproduce

- `outputs/plan09_au_gold_v1/r4_first10_validation.json`: exact ten targets, decisions, witnesses/context và preservation results.
- `outputs/plan09_au_gold_v1/r4_model_proposals/099980/p09-r4-099980-first10-{01..10}-gpt61sol-v1.json` và `.validation.json` sidecars.
- `outputs/plan09_au_gold_v1/model_proposal_manifest.json`: ten non-Terra proposal refs/hashes/producers.
- `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-first10-sol-v1.json`: frozen selection/resume boundary.
- `reports/plan09_model_silver_progress.latest.json`: rebuilt current progress/gates.
- `python -m knowledge_base.pipeline_v1.review_plan09_r4_first10`: resume exactly this frozen batch; valid existing proposal được dùng lại, không chọn thêm ten missing tiếp theo.

## Verification

Before checkpoint infrastructure tests: 3/3 PASS. Focused R4 + R3 completion: 8/8 PASS (9.273 giây), gồm duplicate guard, exact context/provenance/trace rejection, idempotent retry, crash-before-manifest recovery, exact ten decisions và accepted R3 preservation. Full relevant Plan09: 44/44 PASS (265.979 giây), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Sau bổ sung count-rebuild/resume verification, focused suite rerun: 8/8 PASS (9.147 giây).

Resume sau capacity failure: revalidate đủ 10 immutable checkpoints, đúng selected IDs/order/provenance và 10 sidecars; không relabel/duplicate/next-batch. R4 manifest được recompute từ valid hash-bound proposals, `manifest_rebuild_changed=false`; progress rebuilt và xác nhận 222/369, 147 missing. R3 post-R4 verifier PASS (`outputs/plan09_au_gold_v1/r3_post_r4_verification.json`) với frozen R3 cohort counts 98/113/1; không ghi đè report pre-R4. Summary test/hashes: `outputs/plan09_au_gold_v1/r4_first10_resume_verification.json`. Schema/test PASS không thay independent semantic audit.
