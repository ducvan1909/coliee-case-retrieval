# Phục hồi hai output quá dài và thu nhỏ phép thử escape

> Phần shortening đã được thay thế bởi [chính sách độ dài mềm](36_soft_length_policy.md). Không chạy lại các lệnh sửa độ dài dưới đây; giữ nội dung này làm lịch sử quyết định. Phép thử decoder chỉ còn phục vụ chẩn đoán riêng, chưa phải yêu cầu production.

## Quyết định

Giữ nguyên schema AU, model Qwen 9B, prompt extraction A và trần output 800 token. Chưa thay decoder: native JSON Schema 0.2.8 đã chặn cả một số chuỗi hợp lệ có escape; chưa có căn cứ đưa vào runtime.

Tách hai việc độc lập: phục hồi hai output quá dài để tiếp tục đánh giá AU; thu nhỏ phép thử decoder để xác định ranh giới sai. Không buộc chất lượng AU phải chờ nâng cấp thư viện.

## Phục hồi có giới hạn

Đầu vào là checkpoint A `outputs/au_claim_a_local_ready_20261020`: 14 output hợp lệ, hai output sai độ dài; tổng token provider lịch sử 19.672. Hai trường lỗi: `aus[0].limits` 476/250 ký tự và `context_request.question` 258/200 ký tự. Đó là JSON hoàn chỉnh, không phải chạm output cap 800.

- Module riêng `au_claim_recovery`; không sửa package `au_claim` hoặc ghi đè run cũ.
- Kiểm checkpoint nguồn, source và receipt trước khi lập kế hoạch. Run mới chỉ tham chiếu kết quả hợp lệ đã xác minh.
- Chỉ nhận lỗi vượt độ dài. Nếu output còn sai cấu trúc, ID/evidence hoặc kiểu dữ liệu, không đưa vào shortening.
- Một lần sinh bản rút gọn cho mỗi output lỗi. Gửi TARGET, bản trả lời gốc và đường dẫn trường vượt trần. Model chỉ được sửa các trường đó; phải giữ các điều kiện pháp lý quan trọng.
- Host so các trường còn lại bằng giá trị JSON và kiểm toàn bộ contract sau sửa. Không tự cắt chuỗi, không nới cap, không loại AU để hợp thức hóa output.
- Nếu câu hỏi context sau sửa hợp lệ và nguồn context có sẵn, tiếp tục đúng bước context hiện hành; không tự rút gọn đệ quy output bước đó.
- Lưu receipt riêng, ID gắn payload và nguồn gốc. Resume dùng lại kết quả terminal và truy hồi job đang dở; không gọi lại 14 output hợp lệ.
- Tách chi phí lịch sử, chi phí mới và tổng cộng. Báo chi phí chưa biết nếu có request chưa xác định usage. Mock không được gọi là token provider thực.

Shortening là một request model bổ sung, không bảo đảm giữ đúng ngữ nghĩa. Sau khi chạy thật phải đọc lại hai mục sửa, đặc biệt qualification và nội dung câu hỏi context. Không coi protocol complete là AU đạt chất lượng.

## Thu nhỏ lỗi decoder

Script `experiments/escape_length_repro.py` tạo schema chỉ có một string `text`, cap 8, 36 tình huống: ASCII, quote, backslash, newline, BMP và non-BMP; độ dài 7/8/9; Unicode literal và escaped.

Mỗi record ghi JSON nguyên văn, độ dài sau `json.loads`, độ dài biểu diễn và kỳ vọng nhận/chặn. Phép thử giúp phân biệt vấn đề đếm độ dài với vấn đề cụ thể của contract AU. Không kết luận compiler đếm raw bytes/ký tự nếu chưa có bằng chứng.

Không cần tokenizer để prepare. Chế độ đo thật nhận đường dẫn tokenizer local, không tải mạng, không load weights/inference; native compiler có watchdog tối đa 120 giây. Thiếu thư viện/tokenizer phải báo unavailable. Đây là kiểm acceptance, chưa kiểm token mask/EOS hoặc tích hợp endpoint; kết quả tốt vẫn cần bộ probe đầy đủ trước khi đổi production.

Lệnh tạo fixture (không gọi Modal):

```powershell
cd G:\Git\coliee-case-retrieval
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.experiments.escape_length_repro `
    --output "knowledge_base\pipeline_v1\outputs\escape_minimal_$stamp\prepared.json"
```

Muốn đo native phải chạy lệnh đó trong môi trường có XGrammar và tokenizer local, thêm `--tokenizer-path <thư_mục_tokenizer> --max-seconds 60`, dùng output mới. Không dùng kết quả prepare để kết luận compiler đúng/sai.

## Kiểm thử và phạm vi

Kiểm local: nhận đúng hai trường lỗi; loại lỗi không phải độ dài; khóa các trường còn lại; giữ nhiều AU; một lần sửa; checkpoint/resume; context follow-up; lịch sử và chi phí không mất; code hash A không đổi. Phép thử escape phải xác nhận hai cách serialize giải mã thành cùng giá trị và có cùng kỳ vọng.

Đợt triển khai này chỉ code, fixture, prepare/mock và test local. Không gọi inference, deploy, nâng cấp endpoint hoặc chạy lại bộ 16 TARGET.

## Chạy phục hồi

Script tự prepare nếu chưa có workload, preflight rồi chạy. Không có `-Execute`/`-Mock` thì chỉ dry run; `-Mock` dùng thư mục con riêng, không làm bẩn kết quả thật. Run thật dùng `.env` hiện hành và ReadinessGate trước dispatch, không cần lệnh warmup tách rời.

```powershell
cd G:\Git\coliee-case-retrieval
$run = "knowledge_base\pipeline_v1\outputs\au_claim_recovery_$(Get-Date -Format yyyyMMdd_HHmmss)"
& .\knowledge_base\pipeline_v1\experiments\run_au_claim_recovery.ps1 -Execute -OutputRoot $run
```

Nếu bị gián đoạn, chạy lại cùng lệnh với cùng `$run`; không tạo root khác để retry mù. Mỗi mục lỗi chỉ có một job shortening, có thể có bước context tiếp theo theo contract cũ. Lỗi shortening vẫn terminal và không tự gọi vòng sửa thứ hai. Kết quả gốc luôn nằm ở parent run, kết quả mới và chi phí bổ sung trong `$run\live\run.json`.
