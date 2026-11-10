# Kiểm tra local M3 optimization V2

Ngày 08/11/2026; production aggregate `e2e554dd44bbd99ab93b61ca893094fe9dd47e0cd8604e5898e8b169bf931cf3`.

Tester độc lập: **18/18 PASS** trên fixtures/mocks. Phạm vi, lệnh và giới hạn ở [báo cáo tester](../reviews/m3_opt_v2_validation_v1/REPORT.md). Đây không phải kiểm thử Modal thật.

Main dựng chỉ mục thực tế mới `artifacts/m3_opt_v2_index_20261108_v1/`: 916 án, 1.024 passages, không gọi model. Audit riêng kiểm hash/offset/seal, vector finite/norm và bằng chính xác baseline shards; sáu phép BM25 hai kênh so oracle độc lập đều PASS. SQLite giảm từ 138.936.320 xuống 93.270.016 bytes. Code/profile V1 giữ nguyên.

Evidence: [audit thực tế](../reviews/m3_opt_v2_validation_v1/real_index_audit.json), [nghiệm thu local và sampling/padding](../reviews/m3_opt_v2_validation_v1/local_acceptance.json).

Một lần verify Qdrant local nhận `ConnectionError`; chưa verify lại DB. Không tự mở Docker hay sửa collection. AG phải kiểm bước này trước remote. Chưa deploy/call Modal, chưa có real parity, GPU benchmark, real search latency hoặc chất lượng COLIEE V2. Không suy full-corpus readiness từ các PASS local.
