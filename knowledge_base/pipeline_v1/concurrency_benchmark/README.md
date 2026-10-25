# Bước1 — Thử concurrency trên một GPU

Kế hoạch: `knowledge_base/design/pipeline_redesign_lynx/14_speed_optimization_plan.md`.
Chưa triển khai prefix caching hoặc batch nhiều target. Baseline và checkpoint Mốc1
giữ nguyên. App thử riêng `coliee-qwen35-9b-concurrency`, job volume thử riêng; model
cache pinned dùng chung. Model/prompt/schema/evidence/output 800 giữ nguyên, chỉ ID
request quản trị tách theo arm để job cache không giả thành inference mới.

Đã chuẩn bị local 30 target phân tầng độ dài trên cả năm án:
`outputs/concurrency_step1_20261012/{manifest,preflight}.json`.
Chuẩn bị workload khác bằng `prepare --benchmark-id ID_MOI --count 30 --output-root THU_MUC_MOI`.
Tất cả source/context/catalog được xác minh local trước khi gọi model.

## Chạy từng mức

PowerShell dưới đây deploy app thử và gọi inference thật, không deploy baseline.
`knowledge_base/.env` hiện tại cung cấp token/model/thinking; không thêm .env mới.
URL lấy từ kết quả deploy, cùng workspace với token. Không copy token vào lệnh.

```powershell
G:
cd G:\Git\coliee-case-retrieval

& .\knowledge_base\pipeline_v1\concurrency_benchmark\run_step1.ps1 `
    -Concurrency 1 `
    -EndpointBase 'https://khanhnguqua123--coliee-qwen35-9b-concurrency-server.us-west.modal.direct'
```

Sau khi C1 complete và kiểm tra report, chạy lại script với `-Concurrency 2`.
Sau khi C2 complete, không OOM/outcome unknown và không tăng lỗi so C1, mới chạy
`-Concurrency 4`. Không deploy mức tiếp theo khi job mức trước vẫn đang chạy.
Script không tự tăng mức, không tự retry inference/repair hoặc mở rộng workload.
Mỗi mức 30 source request. Startup warmup/warmup ngoài workload báo riêng;
request thất bại và token đã tiêu dùng vẫn có trong cache/report.

Resume một arm sau Ctrl+C: dùng cùng manifest/output và cùng deployment concurrency;
gọi trực tiếp CLI `run`, KHÔNG deploy recreate trong lúc job phía server còn chạy:

```powershell
$root = 'knowledge_base\pipeline_v1\outputs\concurrency_step1_20261012'
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.concurrency_benchmark run `
    --execute --concurrency 1 `
    --url 'https://khanhnguqua123--coliee-qwen35-9b-concurrency-server.us-west.modal.direct/v1/chat/completions' `
    --manifest "$root\manifest.json" --output-root "$root\c1"
```

Resume đọc cache/job cùng ID. Run có cache/reservation cũ không được dùng để khẳng
định throughput fresh. Hard kill có thể để lock: xác nhận tiến trình đã dừng trước
phục hồi thủ công, không xóa jobstore hoặc tự submit payload khác.

## Báo cáo

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.concurrency_benchmark compare `
    --output-root knowledge_base\pipeline_v1\outputs\concurrency_step1_20261012
```

Mỗi arm: `identity.json`, `capability.json`, `warmup/`, `reservations/`, `cache/`,
`run.json`. Tổng hợp: `comparison.json`, wall time/throughput/p50/p95/token,
formal PASS, needs_split và ID output khác C1 để review nguồn. `complete` chỉ nói
đã nhận đủ số kết quả; không có nghĩa mọi kết quả formal/semantic PASS. Missing/
unresolved vẫn hiện riêng. CPU/GPU giờ/VRAM/billing chưa thu được ghi null, không
dự đoán tốc độ GPU từ latency HTTP. Capability là cấu hình được deployment báo,
không thay thế số đo live scheduler/VRAM. Giữ cùng tổng KV budget 12288 có thể khiến
C4 bị queue hoặc chậm; đó là kết quả thử, không tăng bộ nhớ để che bất lợi.

Chỉ đánh giá speedup trên ba fresh complete run cùng manifest. So formal lỗi và
coverage với C1; review khác biệt AU/evidence trước chọn cấu hình. Output cũ/KOS
không phải human gold. Lặp mẫu mới nếu chênh lệch thời gian không ổn định.
