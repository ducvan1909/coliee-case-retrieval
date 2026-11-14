# AG kiểm input 8.500 token / context 12.288

**Checkpoint sau lần AG chạy:** deploy v2 đã báo thành công, nhưng canary run `cache/m6-context8500-ag-canary-20261114-132347242` có call `fc-01M7CBMZWGZDPFSPB4BBT9WB94` timeout/unknown và cancel_requested. Không chạy lại các lệnh deploy/inference bên dưới như một retry. Người dùng tiếp quản, không yêu cầu chuyển run/receipt cũ; dùng call ID và thông tin trong `docs/RETRIEVAL_HANDOFF_20261114.md` để đối chiếu remote nếu còn truy được. Các lệnh phía dưới giữ làm quy trình lúc bắt đầu; chưa được cấp lại ngân sách request.

Yêu cầu bổ sung ngày 14/11/2026: input cap 8.500 token. Code engine được chuẩn bị với `MAX_CONTEXT_TOKENS=12288`; output contract vẫn tối đa 512. Profile mới `settings.json` dùng output 384 hiện hành, 8 request/actions, input tổng 68.000 và total 71.072. Khi triển khai output 512 ở RT4, tổng tối đa tương ứng là 72.096; chưa đổi trong profile này.

**Chưa deploy hoặc chạy inference bởi Codex.** Khả năng nhận context mới, VRAM/startup trên L40S và latency phải kiểm sau deploy; các test local không chứng minh engine thật đã đổi. Các run/báo cáo RT3 cap 7.400/10.000 giữ nguyên evidence lịch sử; không sửa chúng thành 8.500.

Prompt fingerprint của transport hiện bind cả context/output contract để thay đổi context không âm thầm resume bằng profile cũ. Dùng namespace mới cho prepare/canary; không sửa receipt hoặc hash của run cũ để vượt guard.

## 1. Kiểm local

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m4_modal_qwen pipeline_v2.tests.test_m6_live pipeline_v2.tests.test_m6_query_navigation -v
$contextPrepare = 'cache/m6-context8500-ag-prepare-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.m6_live prepare --settings pipeline_v2/reviews/m6_retrieval_rt3_ctx8500_v1/settings.json --run-dir $contextPrepare
```

Kiểm `preflight_status=ready`, settings input cap 8.500, input+output trong context 12.288, model requests 0. Việc actual payload nhỏ hơn 8.500 là bình thường; cap không bắt buộc phải lấp đầy.

## 2. Deploy do người dùng/AG thực hiện

App tên `coliee-qwen36-27b-fp8-l40s` là app hiện hành mà máy kia có thể cũng đang dùng. Phối hợp thời điểm deploy khi không có run đang chờ kết quả; không ngắt một call chưa rõ hoặc tự reset ledger. Không đổi model/revision/GPU/vLLM/backend để làm context mới chạy được.

```powershell
& .venv/Scripts/python.exe -m modal deploy pipeline_v2/deployments/modal_qwen36_27b/app.py
```

Giữ stdout/stderr và exit code. Nếu OOM, startup hoặc max_model_len bị từ chối thì ghi blocker, không tự hạ/trộn precision/model hoặc báo thành công. Không thay `MODAL_FUNCTION_ID` để bỏ guard; nếu deploy tạo ID khác, trả metadata cho Main kiểm và cập nhật binding rõ ràng trước inference.

## 3. Một canary controller gần 8.500 input token

Script mới chỉ chuẩn bị ở lệnh `prepare`; lệnh `run` là một request controller thật, 64 output token, 0 retry và 0 embedding. Không đọc labels hoặc corpus, không phải pilot recall. Lưu admission trước send; đã admission thì không chạy lại để gửi trùng khi receipt chưa rõ.

```powershell
$contextCanary = 'cache/m6-context8500-ag-canary-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m6_retrieval_rt3_ctx8500_v1.context_canary prepare --run-dir $contextCanary
if ($LASTEXITCODE -ne 0) { throw 'Canary prepare loi' }
Get-Content "$contextCanary/plan.json"

# Chỉ sau deploy thành công và metadata/binding phù hợp:
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m6_retrieval_rt3_ctx8500_v1.context_canary run --run-dir $contextCanary
```

Trả plan/admission/report, logs/exit codes, call ID, runtime metadata/startup error nếu có, actual input/output tokens và latency của cả lượt lỗi. PASS cần output `{"status":"ok"}` và input thực bằng số đã đếm, trong khoảng 8.400–8.500. Không gọi đây là bằng chứng model hiểu đúng án hoặc chất lượng truy hồi.

Sau context gate, AG vẫn cần hoàn tất review RT3 theo `reviews/m6_retrieval_rt3_v1/AG_CHECK.md`, đặc biệt các sửa cuối của Main. Dừng trước RT4; không chạy pilot M6 toàn bộ nếu chưa nghiệm thu.
