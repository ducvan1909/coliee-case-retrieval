# CM4 — kết quả code/local trước khi user hoặc AG chạy

Ngày 15/11/2026. User yêu cầu nối inference; Codex chỉ chuẩn bị và kiểm local
theo phân công AGENTS.md. **Chưa gọi Modal/controller/embedding hoặc deploy.**

## Kết quả bản cuối

- `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -q`:
  **30/30 PASS**, 0 skip, 10,854 giây (Main).
- Reviewer độc lập: **30/30 PASS**, 0 skip, 12,178 giây; 0 lỗi chặn xác nhận
  cho gate code/local. Probe riêng xác nhận exact merged schema, STOP, repeated
  page/2-page cycle, new raw positive progress, crash no resend, malformed Unicode/
  duplicate JSON, invalid telemetry và non-ModelReply rejection.
- Local preflight cuối `cache/cm4-preflight-20261115-final`: exit 0,
  **5.375 input tokens**, 0 controller/embedding requests, 0 request admissions,
  `preview.admitted=false`. Ledger chỉ có 1 event run_created.
- Preflight chạy với guard chặn `ModalQwenTransport.send_structured` và
  `HybridSearch.search`. Runtime plan binding khớp code cuối khi Main đối chiếu.
- Namespace `cache/cm4-preflight-20261115-01` là preflight trước hai sửa cuối
  trace/response; giữ nguyên, không dùng để chạy code mới.
- Những lượt tests lỗi STOP ban đầu dùng sai vị trí file ở fixture đã được giữ
  trong stdout công cụ; fixture cuối theo layout run-root/session và suite PASS.
  Không có call provider trong các lượt tests lỗi đó.

## Bindings

- Engine SHA-256: `708e3d8d57afdcc3e77c71c160879a29df3d2f4847103947bd8648d992e03d4e`.
- live.py SHA-256: `98b80a3bb687996c0d11033ae84d3b11ec813c627aa4e22ccfbc16c91ac75523`.
- Plan SHA-256: `9e5b71067ed181fb132a6f99da26651eb0ba3808949d37bef039f1b84cd3546e`.
- Preview SHA-256: `93aa19031f07628e682bd73b3f39d48066b7a98b111ba7195cc19568d12f10ac`.

## Lệnh tiếp theo do user/AG thực hiện

Namespace đã prepare, từ repo root:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-preflight-20261115-final
```

Lệnh này bắt đầu có thể gọi controller và embedding thật. Query `021095.txt`,
giữ model/retrieval parameters hiện hành; cumulative caps sentinel `2**60`,
input/output mỗi request 8.500/512. Loop/no-progress thresholds 3/6; không tự retry.
STOP file ở `cache/cm4-preflight-20261115-final/STOP` có hiệu lực tại safe boundary.
Xem `CM4.md` cho giới hạn chờ, log và việc xử lý call đang treo.

Chưa chứng minh GPU/provider availability, vLLM grammar acceptance hoặc semantic
quality. Sau run, AG cần review traces, payload/schema, decisions, raw coverage,
usage kể cả lỗi/unknown; không mở pilot rộng hơn từ kết quả offline này.
