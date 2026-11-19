# CM4 v10 — bằng chứng cho speaker đã xác định

Lượt v9 `cache/cm4-assessed-preflight-20261115-01` có 13 lượt controller,
91.096 input và 1.600 output tokens. T9 dùng lại search từ T5 với need mới và
không thực thi tool hybrid. Journal ghi hai lượt embedding, tổng 82 token.
T10 mở `013180.txt` ở rank 2. Lượt chạy dừng bởi `semantic_context_cycle`,
với bốn assessment pending và chưa có assessment accepted.

T4, T7 và T11 cùng chọn speaker là court phía A nhưng bỏ `speaker_evidence_refs`.
Validator M4 đã ghi pending đúng hợp đồng. T13 dùng speaker unknown và báo một
khoảng trống evidence, cũng là kết quả pending hợp lệ. Lượt v9 xác nhận search
reuse và warning xuất hiện trong payload trên live. Nhánh sau accepted chưa có
dịp thực thi trong lượt này.

V10 giữ nhánh speaker bỏ qua hoặc `unknown`. Khi model chọn court, party hoặc
quoted source, schema yêu cầu ít nhất một `speaker_evidence_refs` cùng phía
với cấu trúc provenance phù hợp theo quy tắc M4. `quoted_source` cần thành
phần được đánh dấu quoted. Court và party dùng thành phần phù hợp ngoài quote.
Việc chọn ref và giải thích raw vẫn thuộc model. Khi raw chưa hỗ trợ xác định
speaker, model có thể giữ unknown, ghi rõ khoảng trống hoặc đọc thêm. Quoted
assessment thiếu container hoặc quote chain vẫn đi qua nhánh pending.

Với hồ sơ pending đã lưu vì thiếu ref speaker, feedback nhắc phía và vai trò,
gợi ý refs hiện có đủ điều kiện cấu trúc và nêu rõ chỉ dùng khi raw thực sự hỗ
trợ vai trò đó. Các điều kiện trên áp dụng trong bộ thử nghiệm CM4.

Replay offline trước T11 ở 6.791 input tokens. Schema mới chặn phản hồi gốc
thiếu ref. Thêm ref A hiện tại bằng script cho kết quả `accepted` với
`attribution_status=model_inferred`. Replay sau T11 ở 8.145/8.500 token và hiện
đúng ref A trong `speaker_evidence_repair`. Review độc lập xác nhận cùng quy
tắc ở T4, T7 và T11, kể cả danh sách ref rỗng, ref sai phía và provenance quote.
Lượt `unknown` có evidence gap vẫn đi qua pending. Suite offline đạt 43/43 và
kiểm tập trung sau bản chỉnh cuối đạt. Ledgers lịch sử giữ nguyên hash, 0 lượt
controller hoặc embedding. Artifacts replay ở
`cache/cm4-grounded-speaker-replay-20261115-01` và
`cache/cm4-grounded-speaker-feedback-20261115-01`.

`accepted` ở đây là kết quả kiểm cấu trúc. Chất lượng nhận diện speaker, vòng
điều phối sau accepted và schema trên XGrammar của deployment còn chờ kiểm live.

Preflight cuối đạt 5.431 input tokens, 0 admission và khớp code binding.
Người dùng hoặc AG chạy từ repo root theo AGENTS.md.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-grounded-speaker-preflight-20261115-final
```

## Kết quả v10 live và điều kiện hoàn tất v11

Ledger v10 ghi 5 request, 34.341 input và 499 output tokens, một embedding
request 46 input tokens, peak 7.868/8.500. T4 chọn `speaker=unknown` và host
chấp nhận nhãn `similarity_only` cho `012856.txt`. T5 bỏ assessment lặp và
model chọn `complete_policy` khi `011064.txt` và `042319.txt` vẫn ở
`retrieval_only`. `pending_selection` và `prediction=null` phản ánh profile
thử nghiệm chưa có selector. Lượt live xác nhận đường schema đã gửi và nhánh
speaker unknown, chưa kiểm model chọn speaker đã xác định kèm ref.

V11 báo số ứng viên đã tìm, đã có assessment accepted, còn ở retrieval_only
và số cặp pending. Host chỉ cấp `complete_policy` khi không còn ứng viên
retrieval_only hoặc cặp pending trong phạm vi đã tìm. Model vẫn có thể dừng
qua `no_progress` hoặc `failure`. Guard bỏ qua bước kiểm vòng lặp sau khi
action đã kết thúc run. Đây là thay đổi điều kiện ghi trạng thái hoàn tất
review trong thử nghiệm, không phải kết luận về đủ evidence pháp lý.

Replay offline event 17 dựng lại T5 ở 7.733/8.500 token. Schema chặn đúng
`complete_policy` lịch sử, giữ `no_progress` và cho script chuyển sang mở
`011064.txt` qua reader local. Hash run gốc giữ nguyên, 0 lượt controller và
embedding mới. Suite offline PASS 44/44, bao gồm hoàn tất khi ứng viên cuối
được assessment và kết quả pending đã được giải quyết. Report ở
`cache/cm4-review-completion-replay-20261115-01/report.json`.

Preflight v11 đạt 5.428 token, 0 admission. Người dùng hoặc AG chạy.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-review-completion-preflight-20261115-01
```
