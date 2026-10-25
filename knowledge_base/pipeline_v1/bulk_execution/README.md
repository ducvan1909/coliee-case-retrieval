# Thử bulk, pending queue và corpus runner

Thử trên 30 target đã dùng trong benchmark C1/C2/C4, không chạy toàn corpus. Mỗi request giữ prompt AU, grammar, target/evidence và cap 800 output token; model Qwen3.5-9B, không thinking, một L40S và tối đa C4. Không gộp nhiều target trong prompt.

## Ba thay đổi

1. **Bulk:** host tạo capsule request có hash; gửi nhóm 16 capsule qua `POST /v1/batches`. GET tiến độ nhóm trả các receipt theo thứ tự hoàn tất, có cursor. Không phải poll riêng từng job.
2. **Pending queue:** server chỉ giữ cửa sổ công việc đang chờ/chạy trong queue; kết quả terminal lưu riêng. Commit checkpoint trước dispatch; restart không chạy lại job từng ở trạng thái running mà chuyển nó thành interrupted/unknown.
3. **Corpus runner:** host gửi manifest gồm các capsule đã chuẩn bị qua `POST /v1/corpora`. Server tự nạp cửa sổ công việc, điều phối C4 và lưu receipt; host vẫn chuẩn hóa AU, quote/offset/evidence sau khi nhận. Client mất kết nối không làm manifest biến mất. Đây chưa phải chuyển tokenizer/prompt builder hay inference engine sang một pipeline offline khác.

App `coliee-qwen35-9b-bulk` và Volume job riêng; không thay endpoint cũ. Contract server: [BULK.md](../deployments/modal/BULK.md).

## Chạy

Manifest khóa đã chuẩn bị ở `outputs/bulk_trial30_20261013/manifest.json`. Deploy app mới rồi chạy bulk trước:

```powershell
G:
cd G:\Git\coliee-case-retrieval
& .\knowledge_base\pipeline_v1\bulk_execution\run_trial.ps1 `
  -Arm bulk -Deploy `
  -EndpointBase "https://khanhnguqua123--coliee-qwen35-9b-bulk-server.us-west.modal.direct"
```

URL phải lấy từ deploy nếu dùng tài khoản khác. Nếu app đã deploy, bỏ `-Deploy`. Script có preflight, capability polling và warmup; không cần warmup riêng. Khi bulk hoàn tất và đạt hình thức:

```powershell
& .\knowledge_base\pipeline_v1\bulk_execution\run_trial.ps1 `
  -Arm corpus `
  -EndpointBase "https://khanhnguqua123--coliee-qwen35-9b-bulk-server.us-west.modal.direct"
```

Hai arm dùng ID khác để tránh tái sử dụng kết quả inference. Cả hai dùng cùng workload/prompt/grammar. Warmup chỉ xác nhận endpoint sẵn sàng tại thời điểm kiểm tra.

## Resume và giới hạn

Chạy lại cùng arm/root/URL, bỏ `-Deploy`. Host lưu receipt trước khi tăng cursor. Nếu mất ACK, GET theo group ID để khôi phục; không đổi ID rồi gửi lại. Server không tự retry inference có outcome unknown. Không redeploy hay xóa Volume khi còn công việc. Lock còn lại sau kill cứng cần kiểm tra không còn client trước khi xóa lock.

Server nhận bulk tối đa 32 request/4 MiB hoặc corpus tối đa 600 request/16 MiB. Client thử hiện tại chỉ nhận manifest benchmark 10–32 target; chưa mở client cho manifest 436 target. Hết thời gian polling thì giữ checkpoint; inference server có thể còn tiếp tục, không tự tính run này là thành công.

App giữ `min_containers=0`, scaledown120 giây như cấu hình thử hiện tại. Polling giữ hoạt động HTTP trong run; ngắt client lâu có thể khiến container scale down. Manifest/receipt vẫn lưu trong Volume, nhưng inference đang chạy khi container dừng sẽ thành interrupted/unknown, không tự chạy lại. Không cam kết corpus hoàn tất khi client ngắt; chưa bật min1 thường trực để tránh phát sinh chi phí idle.

## Đầu ra và đánh giá

Mỗi arm có `execution_identity.json`, `capability.json`, `warmup/`, `groups/`, `cache/`, `checkpoint.json`, `run.json` và lỗi transport nếu có. Báo request HTTP/bytes, input/output token provider, usage thiếu, thời gian workload và thời gian setup, kết quả unresolved cùng retry GET. Token source không được trừ theo prefix-cache.

`comparison.json` so bulk/corpus; kết quả normalized khác nhau cần kiểm tra AU/evidence. Chỉ so throughput khi run mới hoàn tất, hình thức đầy đủ, usage có đủ và không lấy lại receipt cũ. Đối chiếu thêm C4 cũ cùng 30 target; khác app/thời điểm chạy là nhiễu, không chứng minh riêng từng tối ưu gây tăng tốc. GPU giờ/VRAM/billing chưa đo thì giữ null. Kiểm thử mock local không chứng minh hiệu quả Modal hoặc chất lượng ngữ nghĩa.
