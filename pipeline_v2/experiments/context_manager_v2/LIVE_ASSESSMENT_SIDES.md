# CM4 v6 — đồng bộ phía evidence của assessment

Lượt `cache/cm4-compact-preflight-20261115-final` gửi được 7 request, gồm
assessment ở lượt 7 với 7.618 input tokens. Nó dừng ở validator với
`assessment_state:container_refs_belongs_to_another_case`. Tổng lượt này có
46.637 input, 1.033 output tokens và 2 lượt embedding, 91 input tokens theo
báo cáo AG. Kết quả có một assessment pending và chưa có assessment accepted.

Action gốc bỏ `speaker` và đưa cả ref A và B vào `container_refs`. Schema cũ
chấp nhận cả hai ref. M4 áp phía B mặc định khi không chỉ định phía A, nên trả
lỗi ở ref A. Mismatch này còn áp dụng cho `speaker_evidence_refs` và
`quote_chain_refs` vì cả ba dùng cùng quy tắc validator.

Bản `cm4-assessment-sides-v6` tạo schema theo từng cặp và phía speaker cho
`assess_case_link` và `review_conflicting_link`. Speaker bỏ trống, `unknown`
hoặc thiếu `side` dùng refs B. Nhánh speaker có `side: A` dùng refs A. Model
thấy nhóm refs theo phía và hướng dẫn bỏ các field attribution khi không dùng.
`pair_ref` vẫn gắn đoạn A và B chính. `identity_support_refs` và `counterevidence`
vẫn chọn được refs của cả cặp, theo các kiểm tra dependency hiện hành.

Host kiểm schema trong manifest trước khi dịch action. Validator M4 vẫn xác minh
provenance và attribution. Nếu một action không hợp lệ vẫn đến host, đường lỗi
ghi receipt rejected và dừng theo hành vi hiện hành. Production không tự sửa
action hoặc tự gửi lại model. Bản sửa chỉ nằm trong bộ thử nghiệm.

36 test hiện hành PASS. Regression mới kiểm cả ba field với speaker bỏ trống,
unknown, mặc định, explicit B và explicit A, đồng thời kiểm host từ chối action
trộn hai phía. Review độc lập kiểm 120 cấu hình schema cho hai tool và chạy 30
action hợp lệ theo cấu trúc qua validator M4. Assessment còn thiếu evidence vẫn
pending. XGrammar trên Modal và hành vi model thật chờ lượt do user hoặc AG chạy.

Replay prefix thật qua event 25 đạt 7.821/8.500 input tokens, với cùng refs và
raw spans A `[0,927]`, B `[1255,1859]` như lượt 7. Schema mới chặn chính action
lịch sử chứa hai refs. Một action giả lập chọn ref B đi qua validator và giữ
`pending_evidence` theo nội dung báo thiếu. Replay giữ nguyên hash run nguồn và
có 0 lượt inference/embedding. Kết quả ở
`cache/cm4-side-contract-replay-20261115-01/report.json`.

Run cũ còn ghi nhận cùng ứng viên B được mở lại dưới need khác. Việc đánh dấu
`already_opened` theo case khiến host có thể chuyển sang tìm lại trong B bằng
focus. Lượt sửa này chỉ xử lý lỗi schema, nên hành vi mở lại vẫn cần đánh giá.

Preflight mới đạt 5.421 input tokens và 0 admission. Từ repo root, người dùng
hoặc AG chạy namespace này theo AGENTS.md.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-side-contract-preflight-20261115-01
```
