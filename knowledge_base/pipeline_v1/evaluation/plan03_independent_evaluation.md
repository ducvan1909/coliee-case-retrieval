# Đánh giá độc lập Kế hoạch 03

## Verdict retest

**PASS — 2026-10-03 21:09 +07:00.** P03-F01 và P03-F02 đều được xác minh sửa đúng. Không còn finding mở trong phạm vi structural pre-pass/SourceBlock Plan 03. Không bắt đầu Plan 04.

PASS này xác nhận exact structural contract, cache/provenance identity và audit-event integrity trên KOS-5; không xác nhận semantic heading quality, LegalUnit, AU hoặc retrieval.

## Bằng chứng chạy

```powershell
python -m knowledge_base.pipeline_v1.structural_prepass
python -m unittest discover -s knowledge_base/pipeline_v1/tests -v
python -m unittest discover -s knowledge_base/pipeline_v1/evaluation -p "test_*.py" -v
python -m unittest knowledge_base.pipeline_v1.evaluation.test_plan03_independent -v
```

- CLI Plan 03: PASS.
- Test gốc Plan 01–03: 31/31 PASS.
- Existing independent trước test mở rộng cuối: 23/23 PASS.
- Independent Plan 03 sau mở rộng: 9/9 PASS.
- Rebuild/resume: 5/5 artifacts `reused`.
- Bốn thế hệ artifact (`sourceblock-rules-v1`, `v1.1`, `v1.2`, `v1.3`) vẫn tồn tại cho đủ 5 án; 0 historical artifact đổi bytes qua rebuild.

## P03-F01 — High — FIXED VERIFIED

Parser `sourceblock-rules-v1.3` tiếp tục dùng canonical named-field payload chung giữa producer và validator. Fault injection độc lập xác nhận validator từ chối:

- top-level cache key;
- block ID, order, parser version và policy hash;
- block/content/marker/nested-span case/source identity;
- event provenance và canonical artifact path mismatch.

Stable deterministic IDs, cache identity và dependency-addressed path hiện được tái tính thay vì tin dữ liệu lưu.

## P03-F02 — High — FIXED VERIFIED

Event contract v2 khóa năm event types bằng `EVENT_SPECS`. Schema conditional constraints và runtime validator cùng đối chiếu canonical severity, message code và exact message. Event ID bao phủ contract/provenance, related block, event type, severity, message code/message và exact span.

Reproduction cũ—hạ `heading_candidate_review` từ `review` xuống `info` và sửa message—hiện bị từ chối.

Test mở rộng tạo canonical fixture cho đủ năm event types:

- `heading_candidate_review`;
- `bracket_year_protected`;
- `unclosed_quotation`;
- `very_long_block`;
- `unknown_block`.

Với từng loại, các mutation riêng của severity, message, message_code, event_type, event contract version, block ID/order, span case/hash/bounds, parser version, policy hash và event ID đều bị `StructuralPrepassError`.

## Exact structure, cache và audit ledger

Cả 5 án đạt:

- 431 SourceBlocks;
- coverage 100%; order liên tục; không gap/overlap;
- exact source round-trip;
- source hash được kiểm tra qua Plan 02 trước parse;
- source/parser/policy identity đổi tạo cache/path mới;
- cached artifact hỏng không được silently reuse;
- artifact lịch sử không bị ghi đè.

Rà trực tiếp event ledger vẫn giữ đúng:

- 39 `review/heading_candidate_review`;
- 10 `review/unclosed_quotation`;
- 27 `info/bracket_year_protected`;
- 0 severity `error`.

Tổng cộng 49 review + 27 info = 76 events. `error=0` được báo tách biệt, không che uncertainty/review. Không có SentenceAtom, LegalUnit, AuthorityUnit, AnalysisRegion, relation hoặc LLM.

## Kết luận

Plan 03 đạt gate độc lập. P03-F01 và P03-F02 đóng là `fixed_verified`. Plan 04 chỉ được bắt đầu bằng lượt triển khai/đánh giá riêng.
