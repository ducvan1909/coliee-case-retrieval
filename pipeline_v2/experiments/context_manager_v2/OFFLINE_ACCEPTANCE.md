# Nghiệm thu CM4 offline

Bản `cm4-pair-navigation-v12` được kiểm trên query `021095.txt`. Bài chạy dùng
tokenizer và công cụ đọc corpus thật. Kết quả hybrid lấy từ ledger đã lưu
của `cm4-grounded-speaker-preflight-20261115-final`. Các quyết định của
controller được viết sẵn. Mỗi action được kiểm với JSON Schema của đúng lượt,
cùng số token và hash của payload trong ledger.

| Kịch bản | Kết quả |
| --- | --- |
| Đọc A, tìm, nhận kết quả, đọc B, assessment pending, đánh giá lại rồi đọc và đánh giá các B còn lại | 12 lượt. Engine chấp nhận assessment cho 3 ứng viên `012856.txt`, `011064.txt`, `042319.txt`. `complete_policy` kết thúc với `complete`. Không còn assessment pending hay request/action dang dở. |
| Đóng gói payload ở lượt 8 từng vượt ngân sách | Replay prefix tới event 29. Payload mới 7.557 token có raw A và B, action `assess_case_link` giả lập được chấp nhận. |
| Lặp lại cùng truy vấn hybrid dưới một need khác | Replay prefix tới event 25 dùng lại đúng ba ứng viên theo thứ tự đã lưu, gắn với need hiện tại và không gọi tool tìm kiếm lần nữa. |
| Dừng chủ động, dừng vòng điều hướng và khôi phục sau gián đoạn | Bộ test local kiểm `no_progress`, phát hiện vòng qua các trang, dừng trước và sau khi nhận phản hồi, và khôi phục mà không gửi lại request đã ghi ledger. |
| Toàn bộ bộ test của thử nghiệm | 48/48 pass. |

Lượt chạy đầy đủ có payload lớn nhất 7.873/8.500 token. Cả lượt chạy và replay
dùng 0 request inference, 0 request embedding. Hash của run nguồn được kiểm
trước và sau. `pending_selection` là trạng thái bàn giao sau review. Các nhãn
`unknown` trong bài chạy chỉ để kiểm đường thực thi assessment.

## Ba lỗi điều hướng đã sửa

1. Tiếp tục đọc A khi chưa có ứng viên từng tạo mục quay lại cặp với B rỗng.
   Chọn mục đó có thể làm mất tool tìm kiếm. Bản v12 giữ tool tìm kiếm khả dụng.
2. Sau khi đọc tiếp A, một tool có thể lấy được đoạn A mới nhưng payload tiếp
   theo vẫn hiện đoạn cũ. Cả `read_more_context` và `read_query_passages` nay
   cập nhật đoạn đang hiển thị.
3. Quay lại một cặp từ trang thứ hai của danh sách đã lưu từng mang offset cũ
   sang màn hình assessment. Bản v12 đưa màn hình assessment về trang đầu và
   giữ vị trí đọc raw của đúng cặp.

## Phạm vi kết luận

Các đường điều hướng, đóng gói, review và dừng đã thử đạt yêu cầu offline. Kiểm
độc lập tái hiện một trường hợp action hợp JSON Schema nhưng bị từ chối khi
kiểm provenance. Ví dụ, controller dùng đoạn văn thường làm bằng chứng bao
chứa phần lập luận được trích dẫn. Engine ghi
`assessment_state:container_ref_lacks_matching_provenance` rồi kết thúc phiên,
chưa có lượt để controller sửa. Bài nghiệm thu chưa đo tần suất lỗi trên model
thật, cách decoder của provider xử lý schema, hay chất lượng pháp lý của
assessment.

## Tái hiện

Chạy từ thư mục gốc repo và chọn thư mục đầu ra mới cho từng lệnh.

```powershell
.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -q

.venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.offline_acceptance `
  --source-run cache/cm4-grounded-speaker-preflight-20261115-final `
  --output-dir cache/cm4-offline-acceptance-repro

.venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.replay_fit `
  --source-run cache/cm4-hit-first-preflight-20261115-01 --through 29 `
  --check-action assess_case_link --output-dir cache/cm4-offline-fit-repro

.venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.replay_fit `
  --source-run cache/cm4-side-contract-preflight-20261115-01 --through 25 `
  --check-search-reuse --output-dir cache/cm4-offline-reuse-repro
```

Kết quả đã xác minh nằm ở `cache/cm4-offline-acceptance-20261115-v12`,
`cache/cm4-offline-fit-regression-20261115-v12` và
`cache/cm4-offline-reuse-20261115-v12`. Lượt chạy đầy đủ có `report.json`,
`trace.jsonl` và ledger trong `session/`.
