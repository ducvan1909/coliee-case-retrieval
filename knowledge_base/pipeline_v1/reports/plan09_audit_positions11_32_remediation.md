# Plan 09 — verification hai revision 11 và 32

Ngày: 2026-10-05. Model correction: gpt-6.1-sol. Trạng thái: model_silver, pending independent re-audit; không phải semantic gold.

## Kết quả trực tiếp

- Hai revision đã tồn tại được giữ nguyên; verification không tạo lại hoặc ghi đè revision.
- 49/49 effective review heads hợp lệ; 42 physical amendments hợp lệ, lineage không fork và parent byte hashes khớp.
- 189 proposal/review/amendment files không đổi trong resumed verification. Báo cáo checkpoint trước ghi nhận bảo toàn originals và lịch sử khi thêm hai revision.
- Snapshot queue trước sửa được tái tạo đúng SHA256 `b693b883fdf4ad7966b882282d5c0e5194562689315b63bc911e0270f1e653a5`; snapshot hiện tại khớp regeneration. Không cần rebuild.
- Effective: 98 AU / 113 hard negatives / 1 unresolved. Coverage giữ nguyên 212/369 targets, 157 missing; không xử lý target thiếu. Attribution queue: 49 reviewed / 0 pending model review.

## Phạm vi correction

- Position 11, `at-a5b5b0fdf3bab9574aa4429e`: đổi `holding` thành `procedural_rule`; giữ claim, attribution, evidence và qualifications. Head: `p09-r3-audit-11-32-11-gpt61sol-v2`.
- Position 32, `at-3f8c7b00587a03395a1070fa`: positive narrow current-court holding. Primary proposition và attribution chỉ dùng raw `[11890,11945)`: `The Board never ruled on Mr. Bayavuge's risks of return`. Paragraphs 35–39 là cross-block support; party submission không phải primary witness. Head: `p09-r3-audit-11-32-32-gpt61sol-v2`.
- Reviews/amendments cũ còn nguyên. Báo cáo batch cũ giữ số liệu lịch sử; test tách historical snapshots khỏi live effective heads.

## Artifact cho re-audit

- `outputs/plan09_au_gold_v1/remediation_audit_positions11_32_validation.json`: checkpoint correction và preservation ban đầu.
- `outputs/plan09_au_gold_v1/remediation_audit_positions11_32_resumed_verification.json`: verification mới, hashes và 49 validation results.
- `outputs/plan09_au_gold_v1/risk_reviews/p09-r3-audit-11-32-{11,32}-gpt61sol-v2.json` và cùng ID trong `model_amendments/`.
- `outputs/plan09_au_gold_v1/attribution_risk_queue.json`, `semantic_defect_registry.json`; `reports/plan09_model_silver_progress.latest.json`.
- Reproduce verification: `python -m knowledge_base.pipeline_v1.verify_plan09_audit_positions11_32`.

## Acceptance boundary

P09-S01 vẫn `pending_reaudit`; chưa closed/independent-accepted. Validation PASS chỉ chứng minh contracts, offsets, hashes và snapshot consistency, không thay independent semantic acceptance. Plan 10 vẫn khóa. Sẵn sàng để gpt-5.6-sol low re-audit hai correction và effective heads; chưa chạy re-audit trong verification này.

## Test verification

`python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`: 36 tests PASS, 263.032 giây. Bao gồm ba test mới cho revision heads/parent hashes, position 11 preservation và position 32 exact heading/support cùng lock gate. `python -m knowledge_base.pipeline_v1.verify_plan09_audit_positions11_32`: PASS. Không gọi LLM, GPU hay bổ sung annotation trong verification.
