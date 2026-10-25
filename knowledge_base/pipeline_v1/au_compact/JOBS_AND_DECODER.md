# Job bền và đối chứng grammar chuỗi — Plan 10

Thay đổi này xử lý việc mất kết quả do kết nối và cho phép kiểm tra giả thuyết grammar chuỗi làm decode chậm. Chưa có số đo remote chứng minh tăng tốc. Schema compact/full, nguồn, atom và cách suy offset không đổi.

## Hai chế độ chuỗi

- `bounded` là mặc định, giữ giới hạn độ dài chuỗi trong EBNF.
- `host_validated` dùng chuỗi JSON không rỗng, không giới hạn số ký tự trong EBNF. Các enum, ID, quan hệ giữa trường, thứ tự key và giới hạn AU/evidence vẫn được ràng buộc. Host vẫn từ chối claim quá 300 ký tự hoặc other_kind quá 160 ký tự. `max_tokens` vẫn áp dụng. Không cắt chuỗi hay sửa nội dung để làm output hợp lệ.

So sánh cùng một target, model, prompt, context và output cap trong hai thư mục output mới. Báo thời gian inference phía server, thời gian client, input/output/reasoning token, finish_reason và lỗi host. Không chọn chế độ nhẹ chỉ vì nhanh hơn nếu tăng unresolved hoặc mất AU/evidence. Đây là phép thử giả thuyết, không phải cam kết tiết kiệm.

## Giao thức job

Gateway công khai ở cổng 8000, SGLang ở cổng 8001. Hai route mới là `POST /v1/jobs` và `GET /v1/jobs/{job_id}`; route chat đồng bộ vẫn dùng cho probe. Modal tiếp tục xác thực proxy token. Chỉ một container và một inference chạy tại một thời điểm; nhiều HTTP poll không đồng nghĩa nhiều inference.

Job ID là SHA-256 của payload JSON chuẩn hóa, bao gồm model, prompt/context, các ID, grammar và cấu hình sinh. POST nhận `{job_id,payload}`. Kết quả có `payload_sha256`, trạng thái, thời điểm và khi hoàn tất có `response`, `response_sha256`, `usage`, `inference_seconds`. Payload và kết quả lưu trong Volume riêng tư; GET không trả payload.

Trạng thái: `queued → running → completed/failed/interrupted`. Lưu và commit trước khi nhận job và trước khi gọi backend. POST lại cùng ID không gọi model lại. Khi container khởi động lại, job `running` thành `interrupted`; không tự retry vì chưa biết kết quả cũ. Job `queued` có thể tiếp tục. Đây không phải bảo đảm exactly-once khi container chết giữa inference và commit.

Client GET trước, POST tối đa một lần trong mỗi lượt chờ, rồi chỉ poll. Mất phản hồi POST được phục hồi bằng GET cùng ID. Hết `AU_JOB_WAIT_SECONDS` chỉ dừng chờ; model có thể còn chạy. Runner lưu unresolved và dừng dispatch các target sau. Chạy lại cùng output root với `--retry-provider-unavailable` lấy lại cùng job. Job interrupted/failed cần kiểm tra riêng, không âm thầm đổi ID để gọi lại.

Resume job sử dụng kết quả warmup/probe đã lưu để không gửi probe chen vào inference đang chạy. Ledger giữ reservation và usage một lần cho mỗi job; reservation là dự phòng, không phải token thực. Warmup và schema probe có usage trong artifact riêng, cần cộng chúng khi báo tổng workload. Khi có lỗi không lấy được usage, ghi unknown, không ghi zero.

## Triển khai và thử nhỏ

Code mới phải deploy lại; endpoint cũ chưa có `/v1/jobs`. Không đổi GPU, model hay scale-down để coi là đã sửa chậm. File deploy và hướng dẫn ở `deployments/modal/`. Chưa thực hiện deploy hoặc inference trong đợt sửa code này.

```powershell
Set-Location G:\Git\coliee-case-retrieval
.\.venv\Scripts\modal.exe deploy knowledge_base\pipeline_v1\deployments\modal\qwen35_9b_l40s.py --strategy recreate
```

Giữ AU_URL, AU_TOKEN, AU_MODEL trong `knowledge_base/.env`; không đưa token vào lệnh. Cấu hình mới tùy chọn:

```dotenv
AU_TRANSPORT=jobs
AU_STRING_DECODER=bounded
AU_JOB_WAIT_SECONDS=1800
AU_JOB_POLL_SECONDS=2
```

`AU_JOBS_URL` có thể bỏ trống nếu AU_URL kết thúc `/v1/chat/completions`. Thời gian chờ này khác scale-down và khác timeout từng HTTP request. Chế độ jobs hiện hỗ trợ ở `au_compact`; không áp dụng cho runner `au_only` cũ.

Đối chứng một target bằng hai lệnh `au_compact run --execute --transport jobs --request-id <ID>`: lượt đầu thêm `--string-decoder bounded`, lượt thứ hai `--string-decoder host_validated`, mỗi lượt dùng `--output-root` mới, cùng manifest/source-store/atom-root. Run tự warmup và probe trước target nên không cần warmup riêng. Không chạy toàn bộ suite/10 target trước khi hai lượt nhỏ có kết quả.

Ví dụ với target 013948 từng có decode chậm, sau khi deploy gateway:

```powershell
Set-Location G:\Git\coliee-case-retrieval
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$bounded = "knowledge_base\pipeline_v1\outputs\decoder_bounded_$stamp"
$light = "knowledge_base\pipeline_v1\outputs\decoder_light_$stamp"

.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact run `
  --execute --transport jobs --string-decoder bounded `
  --manifest knowledge_base\pipeline_v1\manifests\au_compact_pilot_r5_model_silver.v1.json `
  --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
  --request-id auo-885151f935ef8056f35cf5bc --output-root $bounded

# Chỉ chạy lượt đối chứng sau khi job trên đã kết thúc; nếu timeout thì resume trước.
if ($LASTEXITCODE -eq 0) {
  .\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact run `
    --execute --transport jobs --string-decoder host_validated `
    --manifest knowledge_base\pipeline_v1\manifests\au_compact_pilot_r5_model_silver.v1.json `
    --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
    --request-id auo-885151f935ef8056f35cf5bc --output-root $light
}
```

Để resume, giữ nguyên model, decoder, manifest, selection và output root, thêm `--retry-provider-unavailable`. Không dùng output root của v3 vì cache/ledger identity đã đổi. `run.json` có `pending_request_ids` cho target chưa dispatch, trace job ID, latency và usage; cache giữ compact response cùng contract đầy đủ khi host kiểm tra đạt. Protocol verified không chứng minh AU đúng ngữ nghĩa.

Nếu không cần job, `--transport direct` giữ đường đồng bộ. Không có fallback tự động giữa hai transport.
