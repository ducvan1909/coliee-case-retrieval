# Plan09 R4 — 099980 sixth ten missing targets

Ngày 2026-10-06. Provenance gpt-6.1-sol low; model-only/model-silver, không phải Terra output hoặc independent acceptance.

## Kết quả

Đúng 10 ID đầu trong 107 missing_target_ids trước batch. Batch: 7 AU / 2 hard-negative / 1 unresolved. Reviewed 262 → 272 / 369; missing 107 → 97. Effective totals: 121 AU / 144 hard-negative / 7 unresolved.

Giữ nguyên 262 target cũ và 315 preservation hashes của proposals/sidecars/amendments/risk reviews/registry history/prior batches/reports/R3 artifacts. Fifty R4 manifest records cũ giữ nguyên, chỉ append ten records mới. Không xử lý target thứ 11, không audit, không mở Plan10.

## Exact targets / evidence

Raw case `099980`, SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`. Offsets half-open trên raw source, không normalize.

| # | Target ID | Full reviewed span | Decision / evidence / qualification |
|---|---|---|---|
| 1 | at-4d1f2de7b9825c4769503ecd | [58843,59006) | AU procedural_rule/current_court: fairness content varies with context. Primary [58843,58910), context limit [58886,58910). Không duplicate danh sách Baker ở target 3. |
| 2 | at-53b9e5a98f7f48d4d0b6edeb | [70406,70770) | AU holding/current_court, medium uncertainty: thiếu cơ hội comments trên final analysis/findings report trước Commission approval là fundamental flaw trong case này. Primary [70406,70723); report-date limit [70515,70559), pre-approval limit [70662,70722); confirm paragraphs 173–174 [104755,105460). Không duty circulate mọi document. |
| 3 | at-5504fe5bd31f8b96cf578894 | [59035,59360) | AU procedural_rule/current_court, medium uncertainty: năm contextual Baker criteria. Primary list [59045,59311), speaker/adoption intro cross-reference [58843,59035). Không lấy section heading làm proposition; không biến factors thành unconditional duties hoặc decisive procedural-choice criterion. |
| 4 | at-5ae776a11ff4273a21d10c5e | [12316,12947) | Unresolved: non-party history + assumed non-representation + hypothetical conflict. Không xác định actual concurrent representation hoặc adjudicated conflict; không forced holding/whole-span negative. |
| 5 | at-5b314a4af85452a367b6930c | [47816,48574) | AU statutory_hook/current_court: paragraph 69(a) appointment remedy. Primary first sentence [47816,48161); fraud condition [47982,47999), as-case-may-be limit [48142,48160). Exclude unanswered third-party corrective-action question; preserve 93/183–184 reservation as context. |
| 6 | at-5d005ab7046f40f4effbf4c6 | [58244,58835) | AU standard_of_review/current_court: correctness for alleged procedural-fairness breach. Primary [58244,58400), fairness limit [58329,58399). Không jurisdiction/reasonableness determination hoặc invented suppressed authority. |
| 7 | at-5e5b91a4b13687e831ba0418 | [109520,110170) | Hard-negative editorial: judicial-dialogue/truth-telling/sharp-argument reflection, không operative remedy/costs rule. |
| 8 | at-5ec7836e659f3030d36f47ac | [114451,115298) | AU holding/current_court, medium uncertainty: increased costs trong exceptional case, kèm discretionary reasons. Primary full target; exceptional condition [114485,114562), ordinary-default qualification [114699,114754), case limit [114936,114948), costs limit [115276,115297). Không tự động solicitor-and-client costs hoặc approved requested amount. |
| 9 | at-604adea56602fb87307c1f7d | [24465,25295) | AU statutory_hook/statutory_text, không court jurisdiction holding. Primary English s69 [24605,24959); investigation threshold [24609,24691), fraud-satisfaction threshold [24753,24795), remedy limits [24873,24891) và [24929,24958). Giữ permissive may và cả (a)/(b); French parallel reviewed context. Không kết luận independent third-party sanction power. |
| 10 | at-61be17d6a14ab52741a7c2a4 | [99502,99768) | Hard-negative fact_only: factual incompleteness về tasks/supervision; không universal manager-interview duty hoặc freestanding legal investigation test. |

Đọc full targets và neighboring raw context ±1200 chars. #2 đọc thêm paragraphs 168–174; #5/#9 đọc full paragraphs 92–93 và 183–184 để giữ reservation. Detailed JSON lưu exact witnesses/context, field qualifications, notes, trace/checksums và unresolved reason. Seven AU vẫn là model proposals, chưa semantic gold.

## Checkpoint / verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-sixth10-sol-v1.json`. Ten immutable single-target proposals + `.validation.json` sidecars trong `r4_model_proposals/099980`. Resume đúng batch: `python -m knowledge_base.pipeline_v1.review_plan09_r4_sixth10`; runner dùng persisted checkpoints, không relabel hoặc tự chọn batch tiếp.

Detailed validation: `outputs/plan09_au_gold_v1/r4_sixth10_validation.json`. Pre-checkpoint source/decision test PASS 1/1 (0.244s); focused R4 batches + R3 completion PASS 18/18 (31.682s). Manifest rebuild PASS, 60 records, `manifest_rebuild_changed=false`; preservation 315/315 hashes; all proposals/effective overlays valid. R3 acceptance validator vẫn PASS cho cohort cũ, không acceptance cho R4 mới.

Full relevant Plan09 PASS 54/54 (299.920s), lệnh `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Test results và bound artifact hashes được lưu trong `outputs/plan09_au_gold_v1/r4_sixth10_completion_verification.json`. Contract/test PASS không chứng minh semantic correctness, human gold hoặc retrieval quality. R4 incomplete, R5 chưa PASS, Plan10 false.
