# Phục hồi output AU quá dài

> Đã ngừng thực thi shortening. Độ dài chỉ còn là cảnh báo theo kế hoạch 36. Dùng `au_claim_soft import` để kiểm lại response đã lưu; không chạy lại model vì vượt ngưỡng. Nội dung bên dưới giữ làm lịch sử.

Module riêng cho checkpoint claim-first A; không sửa hoặc chạy lại package `au_claim`.

- Xác minh parent, chỉ chọn lỗi độ dài thuần túy.
- Một lần shortening cho mỗi output; giữ nguyên mọi trường còn lại, cap và grammar cũ.
- Nếu câu hỏi context đã hợp lệ, tiếp tục stage 2 cũ một lần; không repair đệ quy.
- Run mới gắn receipt gốc, giữ 14 kết quả hợp lệ; `merged_results` thể hiện đủ 16 TARGET.
- Resume cùng root; receipt terminal không phát sinh model call mới.
- `inherited_accounting`, `new_accounting` và phần tổng cộng lưu riêng. Usage quan sát qua GET không đồng nghĩa có POST/billing mới.

Từ repo root:

```powershell
$run = "knowledge_base\pipeline_v1\outputs\au_claim_recovery_$(Get-Date -Format yyyyMMdd_HHmmss)"
& .\knowledge_base\pipeline_v1\experiments\run_au_claim_recovery.ps1 -OutputRoot $run
# Sau preflight, chạy thật (đã gộp readiness/warmup):
& .\knowledge_base\pipeline_v1\experiments\run_au_claim_recovery.ps1 -Execute -OutputRoot $run
```

Không có switch thì dry run; `-Mock` kiểm cơ chế trong thư mục con riêng và không gọi mạng. Run thật lưu ở `$run\live\run.json`; chưa xác nhận chất lượng AU ngữ nghĩa. Nếu model thay đổi field khác, vẫn quá dài hoặc thiếu evidence thì giữ lỗi; không tự cắt chuỗi hay tăng hạn mức.

Xem quyết định và phép thử decoder tách biệt tại [kế hoạch 35](../../design/pipeline_redesign_lynx/35_length_recovery_and_escape_repro.md).
