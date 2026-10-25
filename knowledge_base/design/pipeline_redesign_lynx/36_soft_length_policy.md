# Độ dài AU là mục tiêu mềm

Quyết định thay thế kế hoạch 35 về rút gọn output: claim 500, limits 250 và context question 200 ký tự chỉ là mức khuyến nghị. Vượt mức thì ghi cảnh báo có đường dẫn field, độ dài thực và ngưỡng; không loại AU, không cắt text, không gọi model sửa, không tự tạo retry/repair task vì lý do này.

Các ràng buộc bắt buộc vẫn giữ: JSON/keys/kiểu dữ liệu đúng; string không rỗng hoặc chỉ khoảng trắng, không lone surrogate; kind và evidence ID hợp lệ, có TARGET evidence; số AU đúng contract. Trần output token vẫn là giới hạn tài nguyên; response bị cắt không được tự coi là hoàn tất.

## Áp dụng cho artifact hiện có

Module `au_claim_soft` kiểm lại raw response của 16 TARGET trong run A bằng chính sách mới, lưu report riêng. Không sửa artifact hoặc code extraction cũ vì chúng gắn hash/provenance lịch sử.

- Kế thừa 14 kết quả cũ nếu còn hợp lệ.
- Hai output dài được nhận nếu vượt độ dài là lỗi duy nhất; giữ đầy đủ nội dung và cảnh báo.
- Câu hỏi context hợp lệ vẫn có trạng thái cần context. Chấp nhận cấu trúc không có nghĩa đã giải quyết câu hỏi hay xác nhận chất lượng AU.
- Chi phí lịch sử vẫn báo đầy đủ. Việc kiểm lại offline không tiêu tốn token model.

Lệnh compatibility `experiments/run_au_claim_recovery.ps1` chuyển sang kiểm lại offline. Switch cũ `-Execute` không còn gửi request shortening. CLI shortening cũ bị chặn khi có `--execute`; không tiếp tục resume run sửa độ dài đã thất bại.

```powershell
cd G:\Git\coliee-case-retrieval
$out = "knowledge_base\pipeline_v1\outputs\au_claim_soft_$(Get-Date -Format yyyyMMdd_HHmmss)"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_claim_soft import `
    --parent-root knowledge_base\pipeline_v1\outputs\au_claim_a_local_ready_20261020 `
    --output-root $out
```

Đây là thay đổi chính sách chấp nhận output, không phải cải thiện ngữ nghĩa extraction. Module/hash validator cũ được giữ để đọc lịch sử; khi nối pipeline thực thi tiếp, phải dùng validator mềm mới, không dùng validator độ dài cứng cũ hoặc tạo length-repair queue.
