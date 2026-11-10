# Nghiệm thu M0 — 05/11/2026

Bundle hiện hành: `../artifacts/m0_20261105_v2/`. Bundle v1 được giữ lại; v2 thay thế sau khi làm chặt điều kiện đường dẫn output. Không ghi đè bundle cũ.

- Tester độc lập chạy `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v`: **6/6 PASS** trên code cuối.
- Phạm vi: build tái lập, candidate train-only/không gold edges, cohort 10+10 không giao nhau, loại exposure và reserved holdout, phân biệt candidate đọc với query-gold, phát hiện source drift, sửa artifact và tự reseal, chặn ghi đè.
- Tester và Main chạy `.venv/Scripts/python.exe -m pipeline_v2.m0 validate --repo-root . --bundle pipeline_v2/artifacts/m0_20261105_v2`: **PASS**. Lần Main xác minh mất 2,592 giây local.
- Nguồn: 7.708 án, 2.001 query, 8.251 gold edges. Loại 479 query; còn 1.522 eligible. Toàn bộ 401 query IDs có gold được serialize trong manifest AU-reference được ghi nhận với reason riêng.
- Không có blocker trong phạm vi chuẩn bị local. Trạng thái: `prepared_with_pending_model_profiles`; nguồn đủ điều kiện bắt đầu M1. Dense/runtime/token preflight chưa sẵn sàng.

Đây là kiểm tra integrity/protocol, không chứng minh chất lượng retrieval hoặc pháp lý. Ledger chưa đầy đủ mọi lịch sử, nên cohort chỉ được gọi `fresh-by-ledger`. Chưa thiết lập cách ly quyền đọc giữa solver/evaluator. M0 không gọi inference, tải model, xây index hoặc chạy M1.
