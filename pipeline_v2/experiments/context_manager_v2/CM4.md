# CM4 — kết nối inference cho một query

## Contract mới Q1–Q4 — 19/11/2026

Engine `cm4-query-review-v28` chạy qua live CLI `cm4-live-v2`. Model phải kết luận query đang mở trước khi tìm câu khác. Mỗi query gồm một câu tìm kiếm và tập kết quả của nó.

V28 đưa preview của đoạn truy hồi vào thẻ survey và đưa `read_next` về những án ưu tiên chưa đọc. Model cần mở raw hoặc đổi ưu tiên kèm lý do trước khi kết luận. Mệnh đề đã tìm chỉ có thể mở lại có chủ đích qua `revisit_source_need`. Xem [pilot v27 và kiểm v28](../../reviews/cm4_survey_focus_fix_v1/PILOT_20261120.md).

V27 giữ focus trong active query: screening/defer/resume/revisit source gate tạm dừng ở cả schema và host, vẫn cho đọc A. `query_gate_paused` thay gợi ý unscreened gây nhiễu; coverage và các permits cũ giữ ở host. Survey có `survey_position`, route `next_unseen` và return results về phần chưa giao đầu tiên; không tự đánh preview là delivery. Priority không cấp lại classification không đổi nhưng vẫn cho đổi ưu tiên. [Báo cáo và lệnh AG v27](../../reviews/cm4_survey_focus_fix_v1/REPORT.md).

V26 sửa lỗi host dựng bản đồ A thừa sau search: chỉ dựng map trong query mode, đếm map qua CM4 projection thực, giữ cap 2.400. Xem [báo cáo và lệnh AG chạy lại](../../reviews/cm4_map_projection_fix_v1/REPORT.md). Không resume run v25 bị lỗi bằng code v26.

- Search trả tập hits cố định. Model khảo sát tất cả cards qua pagination trước khi mở raw B; không ép đọc raw đủ 50 án. Cards/preview là leads, không phải evidence assessment.
- `prioritize_query_results(candidate_refs, priority, reason)` đặt `read_next`, `maybe` hoặc `low_priority` cho cards đang hiển thị. Không tạo assessment.
- `conclude_search_query(outcome, reason, unresolved_reason, remaining_source_need)` kết luận query sau survey. Host giữ IDs/counters án chưa đọc/chưa giải quyết. `partially_resolved` không phải chứng nhận đã kiểm toàn bộ kết quả; defer riêng một án không tự đóng query.
- Trong active query không tìm query mới/đổi source need; vẫn được đọc A, xem kết quả, đọc và đánh giá các candidate được cấp. Counters survey/raw dựa receipts, không tính fresh prepare preview như delivery.
- Source gate dùng `search_needed`, `no_search_needed`, `need_more_context`. Mệnh đề pháp lý có thể cần nguồn dù không citation/tên án rõ. `signal_ref` tùy chọn. Paragraph partial có thể tìm khi model khai đủ ngữ cảnh cho mệnh đề; provenance/raw/offset validators vẫn giữ.
- `read_query_span(span_ref)` mở lại vùng liên tục ghép từ các cửa sổ A đã được giao. Host cấp tối đa bốn lựa chọn liền kề (tối đa 8.192 byte), thử dựng payload và chỉ cấp vùng vừa cap 8.500; không nhận offsets do model tự đặt, không cho lấp khoảng raw chưa giao. Sau reload chọn proposition ref bình thường. Không thể ghép mệnh đề dài tùy ý vượt context.
- `revisit_source_need(reason)` cho quay lại nhu cầu đã xử lý sau conclusion để diễn đạt query khác. Query trùng hoàn toàn trả lại query ID/kết luận cũ, không retrieval hoặc survey lại. Án `unknown` vẫn nằm trong unresolved dù assessment đã được chấp nhận về protocol.
- Loop guard mặc định `--loop-guard-mode warn`; mode `stop` chỉ khi chủ động chọn. AG xem log và tạo STOP nếu cần. Schema/source/provider failures vẫn được ghi thật; không execute tool sai hoặc tự resend admission unknown.
- `report_review_blocker` giữ đường recovery; `finish_case_review` vẫn chỉ có khi các điều kiện case-level đủ, không thay cho conclusion từng search query. `partial_supported_cases` là kết quả dừng chưa hoàn tất, gồm STOP, không phải final prediction đã nghiệm thu.

Cap mỗi lượt vẫn input 8.500/output 512; cumulative rộng, top 50 khi không truyền settings riêng, không mặc định max-turn cap. Giữ model/index/RRF. Selector M6 và explicit passage leads đã được nối. CM4 model_support/model_attribution vẫn khác heuristic citation/header M6 thường.

Đọc [luồng/tools hiện hành](MODEL_CONTEXT_FLOW.md), [kế hoạch Q1–Q4](../../docs/plan/CM4_QUERY_REVIEW_PLAN_20261119.md) và [lệnh giao AG](../../reviews/cm4_query_review_v24/AG_CHECK.md). Kết quả local ghi trong `REPORT.md` cùng thư mục review; không suy ra live/semantic PASS. Khi code/root/settings thay đổi, prepare namespace mới; không resume plan từ revision khác.

Lịch sử tham khảo: [CM4_HISTORY.md](CM4_HISTORY.md). Không dùng lệnh run lịch sử cho code hiện hành.
