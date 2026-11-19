# CM4 v9 — điều phối sau assessment accepted

Lượt v8 tại `cache/cm4-pending-feedback-preflight-20261115-01` đã ghi được
`pending_evidence` ở T4 và feedback thiếu `speaker_evidence_refs` ở T5. Model
đọc A `[1024,2048]`, tạo truy vấn mới và mở `047660.txt`. T8–T13 tạo sáu
assessment accepted của cùng cặp. Cả sáu dùng cùng A `[1024,2048]` và B
`[5583,6383]`. Chỉ một revision còn active. Lượt chạy dừng bởi guard ở T13.
Payload tối đa 7.865 token. Ledger ghi 13 requests, 86.221 input, 2.546 output
tokens và hai embedding requests với 85 input tokens.

V9 lọc lựa chọn assessment thường theo cặp có kết quả accepted active. Khi
toàn bộ raw hiện tại nằm trong các khoảng raw chính từng được đánh giá cho
cặp đó, schema và menu bỏ `assess_case_link` cho cặp. Khoảng byte so theo case
và source hash, kể cả excerpt bị thu nhỏ hoặc đổi ref. Ordinary assessment
được cấp khi có raw ngoài coverage hoặc cặp chưa có assessment active.
`review_conflicting_link` dùng điều kiện trigger của profile như hiện hành.

Feedback sau accepted hiển thị kết quả đang có, lựa chọn `results` và `needs`,
và hướng dẫn đọc thêm hoặc kết thúc. Model tiếp tục chọn hướng. Guard dùng
coverage raw và lần đầu quan sát trạng thái assessment để tính tiến triển.
Kết quả guard warning đi vào payload kế tiếp. Khi chạy guard mới trên chính
chuỗi lịch sử T8–T13, warning xuất hiện sau T9 và guard chạm ngưỡng ở T10.

Replay offline từ event 33 dùng đúng refs của T9. Payload vừa ở 6.135/8.500
token, schema chặn action lặp lịch sử. Theo lựa chọn điều hướng do script gửi,
reader local mở được `028149.txt` từ trang kết quả. Replay giữ nguyên hashes
của run gốc và phát sinh 0 request controller hoặc embedding. Report ở
`cache/cm4-assessed-replay-20261115-01/report.json`.

Preflight v9 đạt 5.420 input tokens và 0 admission. Lượt live để kiểm lựa chọn
thực tế của model do người dùng hoặc AG chạy từ repo root theo AGENTS.md.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-assessed-preflight-20261115-01
```
