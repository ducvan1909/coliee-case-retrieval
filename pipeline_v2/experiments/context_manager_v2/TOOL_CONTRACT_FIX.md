# Hợp đồng tool CM4 v13

CM4 biên dịch lựa chọn quy nguồn từ provenance của các đoạn raw hiện trong
payload. Danh sách `m6.assessment_attribution_options` và các nhánh JSON
Schema dùng chung lựa chọn theo `pair_ref`, phía A/B, role và type. Với đoạn
trích, mỗi lựa chọn hoàn chỉnh ràng buộc container với các ref bao phủ đúng
dấu hiệu dẫn nguồn. Validator M4 kiểm lại các tham chiếu trước khi ghi
assessment.

Nhánh đánh giá thông thường vẫn cho dùng chuỗi dẫn nguồn khi chỉ rõ đoạn
trích tương ứng, cùng bằng chứng nhận diện và phản chứng của cặp A–B.

Khi thiếu chuỗi dẫn nguồn, lựa chọn đánh dấu `pending_only` lưu attribution
ở trạng thái chờ bằng chứng. Controller cũng có thể đọc vùng liên quan,
ghi rõ còn thiếu gì, hoặc đánh giá quan hệ A–B với speaker `unknown`. Mỗi
payload hiện chứa tối đa một cửa sổ raw mỗi phía, nên bằng chứng ở hai
cửa sổ tách biệt có thể vẫn cần đọc một vùng bao phủ chung. Khi nhiều đoạn
trích nằm trong cùng một ref, độ phân giải của lựa chọn phụ thuộc vào
provenance và span của ref đó.

Lỗi tham số có thể sửa được ghi vào ledger với `cm_tool_repair`; trace
ghi `tool_input_rejected`. Payload tiếp theo trả tên tool, mã lỗi, tên
trường, các ref liên quan và hướng sửa. Cho một lượt sửa trên cùng tool,
need, ứng viên và cửa sổ nguồn. Lỗi lần nữa trong phạm vi đó dừng với
`repeated_tool_input_rejection`. Lỗi thay đổi nguồn, lỗi vận chuyển và
phản hồi sai schema vẫn kết thúc hoặc khóa phiên theo luồng hiện hành.

## Tái hiện offline

```powershell
.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -q

.venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.offline_acceptance `
  --source-run cache/cm4-grounded-speaker-preflight-20261115-final `
  --output-dir cache/cm4-offline-repair-repro --exercise-repair
```

Bài chạy dùng văn bản và tokenizer thật, kết quả retrieval đã lưu, và
controller giả lập. Run tạo báo cáo, trace và ledger ở thư mục đầu ra mới.

## Kết quả đã xác minh

| Kịch bản | Kết quả |
| --- | --- |
| Bộ test CM4 | 54/54 pass, gồm kiểm ghép chéo đoạn trích, thiếu chuỗi, sửa lỗi cùng raw và dừng khi lặp |
| Review query `021095.txt` với một `focus` sai cố ý | 13 lượt, 1 lần trả lỗi và sửa trên cùng raw, 3 assessment, `complete`, đỉnh 7.965/8.500 token |
| Review query `021095.txt` không chèn lỗi | 12 lượt, 3 assessment, `complete`, đỉnh 7.973/8.500 token |
| Replay payload lịch sử lượt 8 | 8.227/8.500 token, có raw A và B, `assess_case_link` giả lập thành công |
| Replay tìm kiếm lặp nguyên văn | Dùng lại thứ tự kết quả và gắn với need hiện tại mà không chạy lại retrieval |

Bốn lượt chạy dùng 0 request inference và 0 request embedding. Artifact
đã xác minh nằm trong các thư mục `cache/cm4-offline-repair-20261116-v13-final`,
`cache/cm4-offline-acceptance-20261116-v13-final`, `cache/cm4-offline-fit-20261116-v13-final`
và `cache/cm4-offline-reuse-20261116-v13-final`. Chuỗi dẫn nguồn được kiểm offline
bằng JSON Schema và validator M4. Decoder provider và chất lượng đánh giá
pháp lý của model thật chưa được kiểm trong đợt này.
