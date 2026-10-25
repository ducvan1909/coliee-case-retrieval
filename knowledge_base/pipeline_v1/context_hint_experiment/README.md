# Phép thử ContextHint — Kế hoạch 11

Thử nhỏ bốn target có hint thật trong KOS-5: 011904 (tham chiếu phía trước), 099980 (speaker continuity), 013948 (quotation), 045155 (lead-in ở phần editorial, đối chứng âm). Đây là phép thử phát triển, không phải gold hoặc đánh giá toàn corpus.

## Hai arm

P2a/P2b dùng cùng target, atom/context, model Qwen3.5-9B, few-shot v4, schema AU, grammar, thinking=false và cap 800 output token. Hướng dẫn sử dụng hint giống nhau. P2a có danh sách hint rỗng; P2b có nội dung hint đã resolve. ID request khác nhau để theo dõi/cache, không phải một biến ngữ nghĩa.

Không thêm source character ngoài atom catalog ở P2b. Metadata cue chỉ lặp phần nguồn đã có, kèm type/direction/status, target/related atom IDs. Hint là dự đoán cấu trúc, không chứng minh AU/speaker. Nội dung liên quan nằm ngoài catalog chỉ được báo unavailable, không tự nạp. Phép thử mở rộng context được tách và chưa chạy trong đợt này.

Host khóa source/hash, Plan04 binding và map hint/workload theo readiness report. Kiểm tra hint map hash, record hash, case/source và atom cache key; payload khác map bị từ chối trước inference. Nguồn/hint luôn là dữ liệu, không phải chỉ dẫn.

## Lệnh

```powershell
Set-Location G:\Git\coliee-case-retrieval
$inputs = 'knowledge_base\pipeline_v1\outputs\plan11_hint_pairs_20261011'
$run = 'knowledge_base\pipeline_v1\outputs\plan11_hint_pairs_run_20261011'
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.context_hint_experiment build --output-root $inputs
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact preflight `
  --manifest "$inputs\manifest.json" `
  --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
  --output "$inputs\preflight.json"
if ($LASTEXITCODE -eq 0) {
  .\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact run `
    --execute --transport jobs --string-decoder host_validated `
    --manifest "$inputs\manifest.json" `
    --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
    --output-root $run
}
```

Run tự warmup và schema probe; không cần deploy lại. Resume dùng đúng manifest/output root. Không tạo lượt mới khi job cũ chưa rõ trạng thái; giữ receipt lỗi. Eight extraction requests không bao gồm warmup/probe/retry. Tổng cap theo AU_* local config; không in credential.

## Review và quyết định

`review.masked_packet` tạo packet có nguồn/evidence nhưng bỏ arm/hint/receipt; mapping giữ riêng để gắn review trở lại đúng request. Reviewer kiểm tra từng AU, omission cả target âm, attribution, điều kiện và context dependency. Review agent không phải human gold; không đặt yêu cầu người adjudicate trong luồng này.

Review sidecar theo `contracts/au_candidate_review.v1.json`: khóa SHA của run và từng proposal, chọn primary atom/quote, field witnesses, material conditions và verdict từng check. Host dựng offset từ quote duy nhất trong atom, kiểm tra primary quote nằm trong raw TARGET. AU được accepted chỉ ở mức `accepted_agent_reviewed`; lỗi semantic bị rejected, thiếu/bất đồng giữ unresolved. Không sửa claim để làm arm tốt hơn.

So cặp ở mức target và AU có evidence, không dùng số AU sinh ra làm chất lượng. Báo token input/output, lỗi/retry, latency và overhead warmup/probe riêng. Nếu không cải thiện ngữ nghĩa nhưng tăng token, ghi disable_candidate cho metadata hint trong workload này; không xóa worker hay suy kết luận toàn corpus. Kết quả không rõ thì giữ cần đo thêm, không ép giữ/bỏ.

## Kết quả lượt 2026-10-11

8/8 extraction request complete; 51 kiểm thử local PASS; resume 8 kết quả không gọi mạng. P2a 10.601 token, P2b 11.628 (+9,69%); gồm overhead có usage là 22.345 token. Chi phí GPU, usage warmup lỗi và review Codex chưa đo.

Main sau phân xử với review độc lập che arm của tester_advanced: 3 accepted_agent_reviewed, 4 rejected, 0 unresolved. P2b có thêm AU được hỗ trợ ở 013948 với condition witnesses giữ scope; cả hai arm còn lỗi qualification. Checkpoint unknown ban đầu được giữ nguyên. Xem `outputs/plan11_hint_pairs_run_20261011/decision.md`, `review.adjudicated.bound.json`, `semantic_review.masked.advanced.json`, `semantic_review.advanced.followup.md` và `semantic_review.masked.tester.json`. Giữ hai store riêng để thấy khác biệt mức bằng chứng. `agent_reviewed_complete` trong audit chỉ chỉ việc đã nhận đủ record review, có thể còn unknown/rejected; không phải cổng chất lượng PASS.

Quyết định `needs_measure`, chưa bật hint metadata mặc định và chưa mở Plan 12. Phép thử này không đánh giá mở thêm nguồn theo hint hoặc recall trên held-out.


### Checkpoint Plan 11 — vòng v5/v6 ngày 2026-10-11

Đã sửa renderer để phân biệt chính xác `TARGET_BODY` với `CONTEXT_PADDING`, giữ nguyên atom/source/offset; render và prompt version tham gia cache identity. V6 bổ sung ví dụ âm party argument/citation list bằng dữ liệu tổng hợp. Không đổi model Qwen3.5-9B, schema, endpoint hoặc giới hạn output.

Local Main 43 test PASS, tester độc lập 24 PASS. V6 chạy đủ 8 request trên bốn cặp development; resume 8 cache/0 lời gọi mạng. Review che arm có 4 supported/4 rejected trước dedup, mỗi arm 2 supported/2 rejected; negative controls đúng. Store lọc sau dedup có 3 accepted_agent_reviewed, 3 rejected, 2 superseded; review đầy đủ không đồng nghĩa extraction đạt chất lượng.

Lỗi còn lại: court interpretation bị gán statute và lặp hệ quả tại 013948. Không khẳng định mọi proposal bị loại đều context-only: TARGET có cơ sở liên quan, còn độ chi tiết của interpretation chưa chốt. Qualification từng contested ở v5 được reviewer v6 chấp nhận dạng tóm lược; không coi thay đổi verdict là bằng chứng model sửa nghĩa. Agent review không phải gold.

P2a 12.536 token, P2b 13.514 (+978, +7,80%); tổng v6 biết được 26.166 gồm warmup/probe. Tổng hai vòng v5/v6 50.190 token provider báo; usage warmup lỗi, review Codex và GPU/billing chưa đo. P2b bổ sung evidence cho referent holding, không thêm AU đúng được review hỗ trợ; tác dụng downstream chưa đo. ContextHint vẫn needs_measure, chưa bật mặc định; metadata-only arm là disable_candidate trên workload này, chưa suy rộng toàn corpus.

Dừng vòng tuning này; chưa chạy 20 target-holdback và chưa mở Plan12. Tập target khóa trong cùng KOS-5 không phải case-held-out. Bước riêng tiếp theo cần cô lập quoted statute/court interpretation/duplicate hoặc so model trên input khóa; chưa chạy thêm model/remote. Báo cáo, manifest, review, costs, cache và checkpoint: `knowledge_base/pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/decision.md`. V5 vẫn giữ lịch sử tại `outputs/plan11_semantic_v5_gate_20261011`; code/artifact hiện local, chưa nằm trong Git HEAD.
