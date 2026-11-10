# Cấu hình Qdrant local cho M3

DB chạy Qdrant server trong Docker Desktop Linux containers trên máy Windows. Model embedding chạy trên Modal; tiến trình Python local gọi Modal lấy vector rồi ghi vào Qdrant localhost. Modal không kết nối tới localhost của máy cá nhân. Compose đã chuẩn bị, **chưa pull/start container trong bước viết hướng dẫn**.

Image cố định `qdrant/qdrant:v1.20.0` theo [release chính thức](https://github.com/qdrant/qdrant/releases/tag/v1.20.0). Dùng named volume phù hợp hướng dẫn Windows của [Qdrant quickstart](https://qdrant.tech/documentation/quickstart/). Khi AG chạy pilot, ghi thêm image digest thực tế; không tự nâng version giữa run.

## Khởi động

1. Mở Docker Desktop, chờ Engine running, dùng Linux containers. Nếu Docker báo cần WSL2/virtualization/restart thì hoàn tất theo thông báo của Docker Desktop trước. Lần kiểm gần nhất thấy Docker CLI đã có nhưng Linux Engine chưa chạy.
2. Mở PowerShell tại repo và chạy từng lệnh:

```powershell
Set-Location E:/Git/coliee-case-retrieval
docker version
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml config --quiet
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml pull
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml up -d
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml ps
Invoke-RestMethod -Uri http://127.0.0.1:6333/collections | ConvertTo-Json -Depth 6
```

`docker version` phải hiện cả Client và Server. API collections trả `status: ok`; DB mới có danh sách collections rỗng. Dashboard: [http://127.0.0.1:6333/dashboard](http://127.0.0.1:6333/dashboard).

Không cần tạo collection hay chọn vector dimension trên dashboard; AG tạo collection pilot riêng sau khi xác minh output model. Nếu tên container/cổng đã bị dịch vụ khác dùng, kiểm hiện trạng và báo rõ; không dừng/xóa dịch vụ không thuộc công việc này để lấy cổng.

## Dữ liệu và vận hành

- REST `http://127.0.0.1:6333`; gRPC `127.0.0.1:6334`. Port chỉ bind loopback.
- Storage volume `coliee_pipeline_v2_qdrant_storage_v1`; snapshots volume `coliee_pipeline_v2_qdrant_snapshots_v1`. Không phải thư mục bind-mount trong repo; Docker quản lý vị trí vật lý.
- Dừng container không xóa volume. Không chạy `down -v`, xóa volume hoặc Docker factory reset nếu cần giữ DB.
- Named volume là lưu bền, chưa phải backup. Pilot phải thử snapshot/khôi phục sang collection test riêng và ghi receipts; full run cần backup/export ngoài volume.
- Bản vectors gốc theo batch và ledger lưu dưới artifact M3 riêng trong repo, để tái tạo DB mà không embed lại. Không dùng index DB làm bản duy nhất của dữ liệu đã trả phí.
- Chưa có giới hạn RAM/CPU cố định trong compose. Pilot đo peak resources; cấu hình M3 full dựa trên số đo, không tự xem Docker Desktop defaults là đủ cho toàn corpus.

Xem log:

```powershell
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml logs --tail 100 qdrant
```

Dừng rồi chạy lại, giữ nguyên dữ liệu:

```powershell
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml stop
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml start
```

Sau khi API hoạt động và code Codex đã freeze theo [M3](M3.md), giao [prompt kiểm thử](AG_M3_TEST_PROMPT.md) cho AG. AG chỉ review, viết tests và chạy thử nếu cần; không triển khai/sửa production hoặc chạy full.
