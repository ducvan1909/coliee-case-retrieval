# Bước2 — Quan sát prefix cache trước tối ưu

Giữ model Qwen3.5-9B, thinking false, cấu hình server C4 và prompt/schema/grammar AU
hiện tại. Chỉ bật `--enable-cache-report` trên app thử và ghi cache metadata có
kiểu. Không bật/tắt radix cache, không flush cache, không đổi baseline Mốc1/.env.
Theo [source SGLang v0.5.19](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.19/python/sglang/srt/server_args.py),
flag này trả cached token trong `usage.prompt_tokens_details`; không giảm tổng
input token đã gửi hoặc tự tạo chiết khấu billing.

Manifest chuẩn bị: `outputs/prefix_cache_probe_20261013/manifest.json`, 5 target
(mỗi case KOS-5 một target, chọn theo median độ dài từ manifest C4). Mỗi target có
hai request fresh ID: initial/reuse, cùng nguồn/catalog/context/contract. Tổng 10
source requests, output reserve 8.000 token; input reserve 82.084 UTF-8 bytes +
framing, không phải provider token. Client chạy tuần tự để dễ quan sát reuse trên
server C4; không so wall probe này với throughput C4 chạy 4 request đồng thời.

## Chạy thật

Lệnh sau deploy lại CHỈ app thử `coliee-qwen35-9b-concurrency` ở C4 để bật telemetry,
chờ capability/warmup, xác nhận flag runtime và chạy 10 request. Chỉ chạy khi job
thử trước đã terminal. Token/model đọc `knowledge_base/.env`, không thêm env mới.

```powershell
G:
cd G:\Git\coliee-case-retrieval

& .\knowledge_base\pipeline_v1\prefix_cache_probe\run_probe.ps1 `
    -EndpointBase 'https://khanhnguqua123--coliee-qwen35-9b-concurrency-server.us-west.modal.direct'
```

Manifest/preflight đã chuẩn bị local. Nếu cần workload ID mới:

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.prefix_cache_probe prepare `
    --probe-id prefix_cache_trial_02 --output-root knowledge_base\pipeline_v1\outputs\prefix_cache_trial_02
```

Truyền `-OutputRoot` tương ứng cho script. Resume cùng output bằng `-SkipDeploy`,
không recreate nếu server job chưa kết thúc. Giữ reservations/cache/identity,
không coi cache response phía client/server là cache KV của model. Resume không
đủ để kết luận tốc độ fresh. Hard kill có thể cần phục hồi lock sau kiểm tra process.

## Đọc báo cáo

`run.json` có:

- cache_hit_observed True/False/None, provider_report_count, cached_fraction;
- cache_observations từng request: cached_tokens, prompt_tokens, fresh_server_job,
  phase, backend_seconds, client_latency_ms;
- token tổng cho cả kết quả lỗi, usage_unavailable, protocol_verified;
- runtime_cache.json: flag/strategy typed đã đọc từ backend, không arbitrary keys;
- setup warmup và server startup warmup tách khỏi workload wall;
- checkpoint/reservations/cache và stop_dispatch khi outcome chưa rõ.

`None`/missing là chưa đo được, không chuyển thành zero. `False` chỉ nói số cached
token báo cáo là zero trong các fresh job quan sát, không tự chứng minh cache bị
tắt. Request cũ được GET lại không là phép thử cache model. Initial không khẳng
định cold vì không flush và có thể có cache từ trước. Backend latency gồm nhiều
pha, chưa có prefill-only timing; không suy causal speedup từ hai lần trả nhanh
chậm, nhất là output có thể khác. Đây là kiểm tra telemetry/cache hoạt động,
chưa là ablation cache on/off hoặc AU semantic validation.

Nếu report hit rõ: chưa cần đổi prompt vốn đã có prefix cố định. Nếu report zero:
kiểm tra runtime cache strategy/eviction/page size trước thay policy. Nếu missing:
xử lý telemetry trước, không mở batching để né số đo thiếu.
