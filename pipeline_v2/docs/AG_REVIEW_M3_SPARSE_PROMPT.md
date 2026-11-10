# AG review chỉ mục BM25 sparse và hybrid

Đọc AGENTS.md tại repo `E:/Git/coliee-case-retrieval`. Các tài liệu đầu vào là `pipeline_v2/docs/M3_SPARSE.md`, `M3_SPARSE_TEST_REPORT.md`, `M3_HYBRID.md` và `PROGRESS.md`. Đọc code mới `sparse_bm25/index.py`, `m3_sparse.py`, profile `configs/m3_sparse.json` cùng evidence ở `reviews/m3_sparse_validation_v1/` trong pipeline_v2.

Đây là review bản code và artifact local đã dựng. Chỉ ghi tests và báo cáo mới vào `pipeline_v2/reviews/m3_sparse_ag_review_v1/`, dùng suffix mới nếu đã tồn tại. Source, ingestion, chỉ mục sparse, seals, code và profile hiện tại được đọc để đối chiếu. Mọi fault injection thực hiện trên bản sao tạm. Lỗi production gửi repro cho Codex xử lý.

Kiểm tính đúng của công thức float64 đã tính sẵn, analyzer, sorted unique query terms, IDF riêng từng kênh, exclusion trước top-k, lựa chọn passage đại diện và thứ tự ties. Kiểm per-term indices duy nhất, offsets tăng và phủ đủ postings, dtypes, checksum, nguồn SQLite, metadata mapping, artifact build dở và invalidation. Reader phải lấy postings qua mảng, chỉ mở metadata cho hits cần giữ. RAM được đo gồm heap, working set và mapped pages riêng. Kiểm mmap thực tế cùng các nhánh tạo bản sao mảng lớn.

Đối chiếu workload lexical đã khóa và ba query hybrid cũ. Recompute IDs, scores, fusion và coverage từ artifacts. Khi cần benchmark thêm, khóa số lượt, dùng cùng query/cap và ghi thứ tự. Báo cold hay warm theo mức kiểm soát thực tế, giữ cả lượt chậm. Startup/hash và metadata tách khỏi scoring. Kết quả historical khác cấu hình chỉ là đối chiếu tham khảo.

Review này dùng các vector cache sẵn có. Không cần gọi Modal hoặc dựng lại corpus để kiểm sparse reader. Nếu được giao kiểm query embedding thật thì user sẽ đưa lệnh riêng. Giữ báo cáo tất cả attempts lỗi và request unknown đã có trong ledger ingestion.

Đầu ra gồm REPORT.md, findings.json, commands_and_results.json, independent tests/results và recomputed_metrics.json. Kết luận riêng correctness, toàn vẹn index, actual corpus parity, latency/RAM, hybrid integration và phạm vi M3 còn thiếu. Không mở gold/labels hoặc dùng chất lượng COLIEE để chọn cấu hình hiệu năng.
