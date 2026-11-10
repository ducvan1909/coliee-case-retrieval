# COLIEE Task 1 — Pipeline V2

Hệ thống agentic đang xây để tìm các bản án được query thực sự viện dẫn hoặc sử dụng theo nhãn COLIEE. Namespace hiện hành là `pipeline_v2/`.

**Codex trên máy mới bắt đầu bằng [CODEX_HANDOFF.md](CODEX_HANDOFF.md).** Tài liệu này tổng hợp trạng thái đã nghiệm thu, tài sản cần chuyển riêng, lệnh kiểm tra và công việc kế tiếp.

- [Tiến độ M0–M7](pipeline_v2/docs/PROGRESS.md).
- [Kế hoạch tổng thể](pipeline_v2/docs/plan/README.md).
- [BM25 sparse và kết quả nghiệm thu](pipeline_v2/docs/M3_SPARSE.md).
- [Báo cáo AG sparse/hybrid](pipeline_v2/reviews/m3_sparse_ag_review_v1/REPORT.md).

Hiện đang hoàn thiện M3. M1–M2 và full vector ingestion đã nghiệm thu. BM25 sparse và hybrid local dùng vector cache đã qua review độc lập. Phần phrase/identity/context delivery, kiểm query embedding thật và harness M4 còn ở phía trước.
