# Giao AG review độc lập M2 token passages

Repo thực: `E:/Git/coliee-case-retrieval`. Đọc AGENTS.md; các đường dẫn G: và phạm vi V1 trong cấu hình cũ đã được người dùng thay bằng E: và `pipeline_v2/` cho công việc này.

Mục tiêu: kiểm code/bundle M2 token passages có bảo toàn nguyên văn, giữ đúng parent/context và kiểm token chính xác hay không. Không nghiên cứu gold/tiêu chí noticed, không đánh giá retrieval khi chưa chạy retrieval.

## Đầu vào và phạm vi

Đọc `pipeline_v2/docs/M2_PASSAGES.md` để xác định **bundle cuối đã nghiệm thu**, receipts và kết quả thực thi; không chọn một output dở dang chỉ vì tên mới hơn. Đọc `docs/M2_PASSAGES_TEST_REPORT.md`, `docs/plan/SOURCE_CHUNK_INDEX.md`, `configs/m2_passages.json`, tokenizer lock, module `passages/`, CLI `m2_passages.py` và tests tương ứng.

Production, configs, tokenizer assets, dữ liệu và tất cả artifact/báo cáo lịch sử chỉ đọc. Chỉ ghi vào thư mục review mới `pipeline_v2/reviews/m2_passages_ag_review_v1/` hoặc suffix mới nếu đã tồn tại. Không đọc labels/gold/evaluator/test sources/.env/credentials. Không tải weights, inference, embedding/index, deploy Modal hoặc tự mở M3. Không sửa code để review PASS. Giữ attempt lỗi/retry và thời gian thực thi trong báo cáo; inference request/tokens=0 nếu không gọi, chat development token chưa đo thì unknown.

## Các kiểm tra bắt buộc

1. Chạy CLI thật và tests phù hợp trên bản code cuối. Kiểm seal, file universe, source/hash/config/code/tokenizer revision drift, cả reseal sửa sai và thay upstream config sau khi khởi tạo reader. Không chỉ gọi builder/validator rồi tuyên bố độc lập.
2. Viết audit riêng đọc raw bytes + JSON đã seal và backend tokenizer chính thức, không gọi passage builder làm oracle. Kiểm trên toàn bộ corpus train trong manifest: full raw slice, UTF-8 char/byte, IDs, passage/parent universe, no gaps/strict progress, siblings, propagation role/uncertainty/source-order context, no merge/drop unknown/quoted/French. Heading/whitespace riêng không thành embeddings: đếm và báo chính xác, không gọi coverage navigation là all raw embedded.
3. Tokenizer pinned Qwen3-Embedding-4B `5cf2132abc99cad020ac570b19d031efec650f2b`, backend version theo lock. Raw document không instruction/chat template. **Postprocessor chính thức thêm một `<|endoftext|>`151643**: full-input count phải gồm token này; overlap count là content-only, không thêm token cuối giả cho overlap. Không suy token từ ký tự, không decode IDs làm raw. Kiểm special literal, Unicode multi-token/codepoint, CRLF/BOM, dài không whitespace, impossible cap, không truncate/padding.
4. Profile local là variant target320 mềm/overlap128 mong muốn/hard448 full input, không baseline không overlap/64 cũ. Parent<=448 giữ nguyên dù >320; parent dài tách đúng cap; overlap thực tế có thể thấp hơn128. Kiểm histogram và overhead, không kết luận chất lượng retrieval tối ưu từ cấu hình này.
5. Thực sự lấy **middle child của parent bị tách** gọi `PassageReader.open_context`; kiểm hit riêng, full parent + previous/next theo offsets/source order, marker nhảy/lặp/quotation không dùng số cộng trừ, đầu/cuối file. Heading và whitespace xen giữa không mất trong raw envelope. Diagnostic không đồng nghĩa M4 đã giao/agent đã đọc. Không đòi M2 triển khai payload caps/ledger của M4.
6. Khóa mẫu trước khi đọc: seed20261106,20 random +20 risk duy nhất; loại M0 discovery/holdout khỏi đọc thủ công và tách các ca regression đã exposed. Mỗi án tối đa3vùng. Rủi ro gồm parent dài, Unicode, fallbackwordboundary, marker nhảy/lặp, unknown/quoted, unnumbered và không preview. Lưu exact raw trước/sau, offsets, hash, sampling reason; đừng gán usefulness PASS chỉ vì số ký tự/anchor coverage. Nếu chỉ chạy rules, gọi đúng là mechanical check; đánh giá nội dung cần nhận xét cụ thể hoặc unresolved.

## Kết luận và bàn giao

Tạo `REPORT.md`, `findings.json`, `commands_and_results.json`, audit script/results, sampling manifest và evidence các vùng đã review. Mỗi lỗi phải có ID, mức độ, source/profile/hash/spans, expected/actual và lệnh tái hiện. Phân biệt lỗi production, giới hạn thiết kế đã công khai và lỗi của script review. Không dùng retry/fix review script làm bằng chứng production sai.

Kết luận `ready_with_documented_limits`, `fixes_required_before_next_stage` hoặc `insufficient_evidence`. Gate local token-valid khác gate tương thích endpoint: Modal engine/template/effective limit chưa khóa, nên không tuyên bố embedding/runtime ready. Protocol PASS không chứng minh ownership, legal source hay noticed prediction chính xác. Không thực hiện bước tiếp theo.
