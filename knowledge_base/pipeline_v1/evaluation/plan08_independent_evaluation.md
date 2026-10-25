# Đánh giá độc lập Kế hoạch 08

## Verdict

**PASS — 2026-10-04 18:29 +07:00.** P08-F01 đã được retest và xác nhận `fixed_verified`. State machine, canonical snapshot/projection, retry/resume, cache, current pointer và sealed archive inventory đều đạt. Không bắt đầu Plan 09.

Đây chỉ là protocol/mock validation; không có AU/no-AU hoặc semantic completion.

## Bằng chứng chạy

- CLI Plan 08: PASS.
- Test gốc Plan 01–08: 93/93 PASS.
- Independent Plan 01–08: 57/57 PASS.
- Independent Plan 08: 6/6 PASS.
- Current build id: `e61ea9eb91545f4c82df905ba4d7fecfa33966b565f8e5b518b7dc1dd5a117be`.
- Một sealed archive cùng deterministic build identity, inventory 594 payloads.
- Không sửa implementation; không bắt đầu Plan 09.

## P08-F01 — Medium — fixed_verified

Sealed archive hiện có `archive_record.json` khóa canonical relative path, SHA-256, byte length và artifact type cho mọi payload. Retest xác nhận fail closed khi:

- sửa byte, truncate hoặc xóa archived `run_snapshot.json`;
- sửa hoặc xóa archived `attempt_log.jsonl`;
- thêm unexpected payload hoặc tạo duplicate/missing inventory entry;
- sửa hash, size, artifact type, build identity hoặc archive-record hash;
- path escape hoặc thay ref sang current tree;
- archived snapshot sai schema/cache, hoặc snapshot–JSONL không reconcile.

Inventory chứa đúng 594 files thực tế: 578 mock cache entries, 7 snapshots, 7 attempt projections, 1 dependency probe và 1 suite manifest. History index trỏ đúng archive record/hash; current pointer bị cấm chọn path dưới `history/`.

## Migration provenance

Archive hiện tại được seal qua `legacy-payload-inventory-migration-v1`. Record khai rõ `tamper_detection_begins_at_migration=true`; pre-inventory copy vẫn còn tại `history/legacy_unsealed/<build-id>` và không nằm trong sealed index/current pointer. Vì vậy legacy bytes không được tuyên bố là đã được bảo vệ trước thời điểm migration và không bị xóa.

## State machine và metrics không đổi

- 369 primary targets, 374 work items, 96 P2a requests;
- cold run: 96 provider calls/attempts, 369 `mock_protocol_verified`;
- exact resume: 0 calls mới, skip 96 verified requests, tránh gửi lại 342.095 chars/85.559 estimated tokens;
- interrupt/resume: 7 calls đã commit + 89 calls còn lại;
- transient retry: 97 attempts, 1 useful retry;
- permanent/protocol failures giữ 365 verified + 4 error targets;
- budget stop giữ 20 verified + 349 budget-exhausted targets.

Canonical JSON snapshot vẫn là source of truth; JSONL chỉ là projection và phải reconcile chính xác. Không có `complete`, `no_au` hoặc semantic-complete state. Token numbers là estimator `ceil(rendered_chars/4)`, không phải provider usage.

## Kết luận

Plan 08 đạt **PASS trong phạm vi offline protocol/cache/resume validation**. P08-F01 được đóng `fixed_verified`; không có finding mở. `mock_protocol_verified` không phải bằng chứng semantic correctness. Plan 09 chưa được bắt đầu.
