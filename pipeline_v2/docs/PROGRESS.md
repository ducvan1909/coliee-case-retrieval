# Tiến độ pipeline_v2 ngày 10/11/2026

Đang ở M3. Nền nguồn và passage đã qua kiểm tra toàn corpus. Full embedding và DB integrity đã nghiệm thu. Chỉ mục BM25 sparse đã dựng và kiểm tra trên toàn train. Hybrid dùng reader mới đã chạy trên Qdrant thật bằng vector cache.

AG review sparse đã hoàn tất ngày 10/11/2026, đạt correctness, index integrity và corpus parity, với 0 lỗi production chặn nghiệm thu. Hybrid local dùng vector cache đạt. Bốn ghi nhận còn lại liên quan startup/RAM, chi phí guard, revalidate và phạm vi M3. Khi nối harness, dùng session xuyên nhiều truy vấn; cân nhắc gom guard ở biên request sau khi giữ đủ kiểm tra invalidation. [Báo cáo AG](../reviews/m3_sparse_ag_review_v1/REPORT.md).

| Mốc | Tình trạng | Đầu ra đã có | Việc còn lại |
|---|---|---|---|
| M0 — Khóa nguồn/profile | Đã khóa nguồn, cohort và embedding profile | Manifest train, exposure/split ledger, Qwen revision và runtime L4 | Model/tokenizer/ngân sách cho agent được chốt khi sang M4 |
| M1 — Nguồn/cấu trúc | Đã nghiệm thu trong contract đã ghi | Raw registry, byte offsets, paragraph/quotation/unknown, vùng nguồn | Xử lý ngữ nghĩa tiếng Pháp được hoãn theo yêu cầu |
| M2 — Passage/context mapping | Đã nghiệm thu toàn train | 415.693 passages, 382.343 parents, 7.708 án, tokenizer và context refs | Tầng giao payload cho agent thuộc M4 |
| M3 — Chỉ mục hybrid | Đang hoàn thiện | BM25 sparse hai kênh khớp oracle ở 16 phép đối chiếu; full vector cache, Qdrant, exact dense + RRF và query-case exclusion; 3 truy vấn dùng vector cache khớp từng kênh và top 20 của bản SQLite | Phrase/identity search; kiểm và hoàn thiện context open/pagination; AG review toàn hybrid và một truy vấn embedding thật |
| M4 — Tools/harness | Chưa triển khai thành harness agent | Có readers và search adapters làm thành phần đầu vào | Tool schema/delivery ledger, token caps, resume/fallback, invalidation assessments |
| M5 — Baseline lịch cố định | Chưa triển khai cho pipeline_v2 | Có contract trong kế hoạch | Fixed search/read schedule, evidence assessment, selector số án biến thiên |
| M6 — Agent thích ứng | Chưa triển khai | Có contract trong kế hoạch | Controller search/open/expand/assess/stop và review có mục tiêu |
| M7 — Đánh giá khóa | Chưa chạy | Có split/exposure protocol | Freeze hệ thống, chạy evaluation, phân tích lỗi và cost theo protocol COLIEE đã kiểm |

Mốc M3 chỉ chốt khi đủ phạm vi trong kế hoạch tổng thể. Việc ingestion PASS hoặc hybrid trả top 20 là các gate kỹ thuật thành phần. Số top 20 của retrieval chưa phải số án noticed được chọn cuối cùng.

Tiếp theo là chốt các quyết định của bản review full search, hoàn thiện search_case/case_map/case_anchors, phrase/identity/context và nghiệm thu M3. Query embedding thật cần được kiểm tra bằng lệnh do người dùng hoặc AG chạy. M4 sẽ nối các công cụ truy hồi với agent. M5–M7 lần lượt xây baseline, agent thích ứng và đánh giá khóa.

Nguồn đối chiếu gồm [kế hoạch M0–M7](plan/README.md), [M2 passages](M2_PASSAGES.md), [full ingestion](M3_FULL.md), [BM25 sparse và benchmark](M3_SPARSE.md), [hybrid thật](M3_HYBRID.md), [draft full search](plan/M3_FULL_SEARCH.md).
