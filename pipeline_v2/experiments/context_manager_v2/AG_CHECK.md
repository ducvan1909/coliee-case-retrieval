# AG review CM2–CM3 — bộ thử nghiệm context manager v2

Hiện hành sau lỗi live CM4: xem `LIVE_FEEDBACK_FIX.md` và namespace mới
`cache/cm4-feedback-preflight-20261115-final`. Review code/local 0 lỗi chặn;
34 tests và replay dữ liệu live PASS, chưa có live behavior sau sửa. Check
duplicate không thành no_hit, feedback visible, native order tường minh,
results_ready escape bằng missing reason, schema gate đồng nhất. Checklist CM2–3
bên dưới thuộc checkpoint đã nghiệm thu trước đó.

Cập nhật sau nghiệm thu: hai ghi nhận không chặn đã sửa, kiểm độc lập 19 tests
PASS và replay/stress mới; xem `PAIR_PROGRESS_FIX.md`. Chưa mở CM4.

**Review đã hoàn tất:** 0 finding chặn engineering offline. Checkpoint nghiệm thu
ở `CM23_ACCEPTANCE.md`; giữ checklist dưới đây làm phạm vi review lịch sử.
Chưa mở CM4. Hai ghi nhận không chặn phải được rà soát trước live.

Checkpoint Main: 15 tests CM2–CM3 + 19 regression CM1 PASS. Replay và stress
bản cuối ở `cache/cm23-main-replay-20261115-final-v2/report.json` và
`cache/cm23-main-stress-20261115-final-v2/report.json`; xem REPORT để biết hashes.
Chưa có kết luận AG cuối. Đặc biệt review tiếp parked >5, multi-root termination,
partial A coverage và giới hạn một raw window mỗi phía; không coi unknown accepted
là legal correctness. Các lệnh tạo namespace AG mới nằm trong README.

Phạm vi người dùng giao ngày 15/11/2026: triển khai evidence lifecycle và tích
hợp offline bằng nguồn thật, phản hồi model giả lập. **Dừng trước CM4.** Không
gọi model/embedding/deploy; không thay model, chunk, K/fusion, selector hoặc gold.

Đọc README/REPORT mới cùng thiết kế ở
`../uncapped_probe/CONTEXT_MANAGEMENT_DESIGN.md`. CM1 đã nghiệm thu riêng trong
`../context_manager_v1/CM1_V2_ACCEPTANCE.md`; không sửa session/artifact lịch sử.

## CM2: bằng chứng và vòng đời

- Mỗi record giữ nguyên case/source hash, exact UTF-8 byte span, text hash,
  provenance và canonical/overlay ref. Reload không tự đổi identity của record.
- Pin/park theo need–candidate; chuyển B không trộn evidence giữa cặp. Park chỉ
  bỏ khỏi context, không xóa raw trong kho hoặc invalidation assessment hợp lệ.
- Có thể quay lại need/B cũ và mở lại đúng nguồn; current payload phải được nạp
  lại trước khi assess/review, không dùng raw của lượt trước hoặc summary ngầm.
- Chia nguồn theo UTF-8-safe spans; requested/delivered/pending/continuation
  phải trung thực. Fetch khác offer, offer khác delivered sau receipt. Unknown
  không tăng coverage; một trang partial không được báo thành full paragraph.
- Giữ attribution/quote-chain/container/counterevidence refs nếu cần cho validator;
  metadata thiếu không tự suy thành court/holding hoặc identity support.
- Source/config drift phải bị phát hiện và chặn/invalidate theo contract; không
  sửa snapshot/seal/hashes để đi tiếp. Pending/unknown là trạng thái hợp lệ.

## CM3: tích hợp và điều hướng

- Có đường execute thật cho reader/map/local source tools và M4 assessment
  validator, không chỉ dispatch intents của CM1. Search trong replay dùng kết
  quả đã lưu, query/hash/operation binding phải khớp; không gọi hybrid remote.
- Full catalog/schema phù hợp state của lượt hiện tại; host kiểm cùng policy.
  Tool names được giữ khi behavior giữ nguyên. Context pagination không được
  masquerade thành source-read hoặc tăng raw coverage.
- Context nhận hits mới theo rank của operation; toàn pool ngoài prompt, trạng
  thái theo need–candidate, không semantic merge needs hoặc global rank ngầm.
- Khi reading giữ focus; assessment hoặc missing/no-hit/error cụ thể tạo safe
  boundary. Model chọn tiếp/chuyển/quay lại; host không ép round-robin cứng.
- Prompt gồm instructions/template, source tool/assessment catalog, context
  controls và raw đều được đếm bằng tokenizer pin. 8.500 input/512 output; không
  so số token của view chỉ điều hướng CM1 với final full-catalog như cùng khả năng.
- Dynamic revisions/cursors và manifest của đúng request phải bền vững: record
  admission trước action, orphan không PASS, crash/in-flight/unknown không replay.
- Assessment đi qua validator M4 hiện hành với raw current records/canonical
  catalog đúng A/B; similarity hoặc schema PASS không được gọi là gold đúng.

## Evidence cần trả

1. Lệnh/stdout/stderr/exit codes và source/code/tokenizer bindings của bản cuối.
2. Unit/regression tests: full pipeline tìm→nhận→đọc→assessment/pending, đổi B,
   quay lại/reload, continuation, nguồn dài/UTF-8/quoted/unknown, tamper/drift,
   stale refs/cursors, unknown và crash/resume không gửi trùng.
3. Replay trên recorded query discovery với M3 source reader thật; ghi rõ action
   model và search replay giả lập, local reads thật, 0 inference/embedding mới.
4. Traces/view/manifest/schema/events, exact tokens, raw bytes/coverage và usage
   lỗi/unknown; source artifacts hash trước/sau không đổi. Không đọc labels.
5. Stress theo scope REPORT: pool/needs tăng và long raw; phân biệt full traversal
   với first-page sampling, CPU/RAM host với prompt bounded, những gì chưa kiểm.
6. Kiểm việc đã accepted/pending/invalidation có nguyên nhân và dependencies;
   park/reload đơn thuần không biến model labels thành gold hoặc xóa lịch sử.

Lệnh chạy cụ thể nằm trong README. Dùng namespace AG mới; không chỉnh output Main
hay run cũ. Nếu có lỗi chặn, giữ evidence và báo tái hiện, không tự sửa production
hoặc thử model/GPU khác để làm PASS.

## Điểm dừng

AG trả kết quả để Main đối chiếu nghiệm thu engineering CM2–CM3 offline. Live
CM4 là bước riêng cần được giao; review này không cấp phép gọi inference/deploy,
không chứng minh semantic correctness, recall hoặc final F1.
