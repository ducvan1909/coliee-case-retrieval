# Đồng bộ EOS cho XGrammar

Runtime Qwen hiện tại có model EOS `248044` và tokenizer EOS `248046`. Backend trước đây chỉ truyền EOS model vào XGrammar, nhưng scheduler có thể dừng ở EOS tokenizer, dẫn đến JSON kết thúc giữa chuỗi.

`json_runtime_hook.py` lấy hợp của model EOS, tokenizer EOS và `additional_stop_token_ids` trước khi constructor XGrammar tạo `TokenizerInfo` và compiler. Không sửa checkpoint, schema, giới hạn token hoặc cấu hình sampler. Hợp được kiểm tra với tập stop thực tế; constructor không hỗ trợ hoặc tập không khớp phải báo lỗi, không tiếp tục chạy bản chưa đồng bộ. Lỗi ghi diagnostic sau đồng bộ không làm mất hiệu lực đồng bộ.

Đường bootstrap của SGLang là bắt buộc. Không ghi đè `PYTHONPATH` của image/Modal runner; bổ sung hook sau khi runner đã khởi động và giữ nguyên đường dẫn dependency kế thừa.

## Test nhỏ trên endpoint

Sau khi deploy, chạy từ repo root:

```powershell
& .\knowledge_base\pipeline_v1\deployments\modal\run_eos_sync_test.ps1
```

Script chạy test local, warmup, GET metadata rồi mới gửi đúng một tình huống `invalid_reason_int`. Nó từ chối gửi probe nếu runtime chưa xác nhận XGrammar có cả `248044` và `248046`. Mỗi lần chạy tạo output root mới; request formal có attempt binding mới nên không lấy lại response lỗi cũ từ cache server. Không chạy extraction hay toàn bộ formal suite trong script này.

PASS của test nhỏ chỉ xác nhận response tình huống đã chọn hợp lệ sau sửa. Chưa chứng minh mọi nhánh của formal suite, chất lượng AU hoặc hiệu quả token. Các tình huống coverage độ dài của full suite vẫn cần được phân xử riêng.
