# M6 local engineering review — 12/11/2026

Trạng thái: triển khai và kiểm local đạt trong phạm vi bên dưới. Chưa nghiệm thu engine live, semantic correctness, COLIEE quality hoặc lợi ích fixed/adaptive. Không inference/deploy Modal trong đợt này; không đọc gold để tạo hành động replay.

## Thay đổi

- `pipeline_v2/m6.py`: AdaptiveHarness trên M4 ledger, source verifier và validator; state dựng lại qua events, budgets/resume/no-progress, selector/fallback injection có fingerprint.
- `pipeline_v2/agent_harness/adaptive_policy.py`: tool theo mục đích, catalog/schema chỉ cho action hợp lệ với state/payload, citation raw spans/scan continuation, query/candidate/context descriptors, assessment/attribution/counterevidence và targeted review.
- `pipeline_v2/m6_live.py`: chuẩn bị local có first-payload preview và chạy explicit trên transport Qwen đã pin; manifest/source/code/profile guards và report append-only mỗi invocation.
- `pipeline_v2/tests/test_m6_adaptive.py`, `test_m6_live.py`, `docs/M6_ADAPTIVE.md`, cập nhật riêng tiến độ M6 trong `docs/PROGRESS.md`.

Không sửa production M3/M4/M5, không sửa snapshot/receipt lịch sử. Working tree trước đợt này đã có thay đổi/untracked của các mốc trước; không stage/commit chúng.

## Kiểm tra bản cuối

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m6_adaptive pipeline_v2.tests.test_m6_live pipeline_v2.tests.test_m4_harness pipeline_v2.tests.test_m4_tools pipeline_v2.tests.test_m4_corpus_action_policy pipeline_v2.tests.test_m5_assessment pipeline_v2.tests.test_m5_baseline pipeline_v2.tests.test_m3_source_tools -q
```

Main: **80/80 PASS**, 7,405 giây. Review độc lập: **20/20 test M6 PASS**, 2,311 giây; thêm kiểm tra ad hoc source drift trước admission, chèn tham số host-owned bị từ chối và unknown request resume không gửi lại. Các phép kiểm đều local, không gọi model.

Các lỗi phát hiện trong review đã sửa trước freeze: reload sau mở B chưa khả dụng; schema fingerprint lệch do enum order sau JSON canonicalization; `neighbor_policy` bị dùng như handle; citation scan không có continuation; counterevidence bị gán sai semantic axis hoặc thiếu dependency; review cap chưa đếm pending attempt. Có regression cho các đường liên quan.

## Replay corpus thật

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m6_local_v1.replay_corpus
```

Bản cuối: [report.json](corpus_replay_20261112T102936345109Z/report.json), implementation fingerprint khớp code cuối. A=`017984.txt`, lexical hai kênh, 6 unique candidate, 5 lượt giả lập: issue search → read B → reload A/B → assess → finish. Một assessment giả lập `unknown` được validator nhận; resume giữ nguyên requests/usage và không gửi thêm. Cả sáu assertion đạt. Thời gian tổng 32,210 giây, 0 request Modal/model, 0 retry. Code dùng canary chặn tạo remote client trong replay.

Tokenizer đã pin đếm 52.385 input token qua năm payload (6.842, 9.250, 12.465, 14.426, 9.402); output token giả lập 0. Đây là số prompt theo tokenizer ở replay, **không phải actual provider usage**. Provider latency không quan sát được; ledger giữ năm request có latency provider unknown. Cap 16.384 token/payload và các limits trong script là fixture kỹ thuật chưa hiệu chỉnh, không dùng để tuyên bố equal-cost hay thắng M5.

Bản replay trước sửa cuối vẫn giữ ở `corpus_replay_20261112T102731693547Z/` để truy vết; không dùng làm chứng nhận revision cuối.

## Chuẩn bị live, không inference

`m6_live prepare` đã chạy thật với [settings](live_preflight_settings.json), nguồn corpus và pinned tokenizer. [Plan](live_preflight_20261112_v1/plan.json) có `preflight_status=ready`, first payload 6.865 input token; [preview](live_preflight_20261112_v1/first_payload.json) và ledger giữ **0 admitted requests**. Không gọi nhánh `run`. Lệnh dành cho người dùng/AG nằm trong [hướng dẫn M6](../../docs/M6_ADAPTIVE.md).

## Giới hạn và gate tiếp theo

- Regex citation chỉ phủ một số neutral/SCR format, không phải identity resolver đầy đủ. Candidate previews là leads, không evidence.
- Registry/catalog làm payload lớn; cần profile/cap phù hợp rồi đo usage live. Không tự dùng lại cap M4 nhỏ hơn hoặc coi stop sớm là tiết kiệm.
- Reviewer là thêm action có finding của cùng controller/model, có cap và audit deterministic; không độc lập như human gold. Chưa có trigger sát cutoff.
- Selector và baseline injection đã có contract, nhưng chưa có policy M5 calibrated/frozen để nối trong CLI. Thiếu chúng thì `prediction=null`, `selection_status=pending_selection`; lỗi giữ `fallback_unavailable`.
- Cần nghiệm thu engine nhiều tool/schema trên live, kiểm attribution/quan hệ riêng bằng evidence có nhãn và so discovery/reading với M5 trên cùng toolbox/limits/model/budget/selector trước chốt M6.
