# Tiêu chí đánh giá noticed case — COLIEE Task 1

Cập nhật: 05/11/2026. Đây là rubric nghiên cứu rút từ batch 3 query, 19 cặp gold; chưa phải bộ quy tắc chính thức hoặc đã kiểm chứng trên toàn corpus.

## Ý chính

**B là nguồn mà A thực sự viện dẫn và sử dụng trong một ngữ cảnh cụ thể.** Cùng chủ đề, cùng kết quả hoặc cùng câu chữ chưa đủ để xác nhận.

[Mô tả chính thức Task 1](https://coliee.org/COLIEE2026/tasks/task1) xác định noticed theo quan hệ được query viện dẫn. Khi chấm benchmark, **file nhãn chuẩn trong data/ vẫn quyết định đáp án**; rubric này không thay thế gold.

## Sáu câu hỏi cần kiểm tra

| Tiêu chí | Câu hỏi |
|---|---|
| Đúng án | A dẫn đúng quyết định B, hay một quyết định khác cùng tên? |
| Đúng vị trí A | Citation nằm ở đâu trong A, phục vụ vấn đề gì? |
| Đúng nội dung B | Đoạn nào của B cung cấp nguyên tắc hoặc lập luận A sử dụng? |
| Đúng chức năng | A nêu, áp dụng, phân biệt, bác bỏ hay dẫn B để giải thích lịch sử tố tụng? |
| Đúng nguồn | A dẫn B, hay A và B chỉ cùng dẫn một án C? |
| Đủ phân biệt | Attribution, pinpoint hoặc chi tiết nào giúp chọn B thay vì các án tương tự? |

**Làm theo thứ tự:** định vị citation trong A → xác định B → tìm đoạn nguồn trong B → kiểm chủ thể và chuỗi trích dẫn. Không chọn đoạn B giống nhất rồi suy ngược rằng A đã dùng nó.

## Những điều dễ nhầm

- Noticed không bắt buộc cùng tình tiết, cùng kết quả hoặc được trích nguyên văn. Một đoạn A có thể viện dẫn nhiều B cho cùng nguyên tắc.
- B có thể trích C mà vẫn được A viện dẫn. Ghi riêng A→B và B→C; không gán lời C cho B.
- Đọc heading để phân biệt lời tòa với lập luận đương sự. Citation của đương sự không tự trở thành nguyên tắc tòa tiếp nhận.
- Số đoạn trong quotation có thể thuộc C, không phải B. File song ngữ có thể lặp số đoạn.
- Citation index giúp xác định A dẫn B ở đâu; không tự xác nhận số đoạn nguồn trong B.

## Cách kết luận

- **Có căn cứ mạnh:** attribution A→B và nội dung nguồn được kiểm chứng.
- **Có khả năng:** nội dung phù hợp nhưng còn thiếu dấu hiệu xác định nguồn.
- **Chỉ tương đồng:** chưa chứng minh được A sử dụng B.
- **Mapping bị phản chứng:** sai quyết định, chủ thể, pinpoint hoặc nguồn được quy thuộc.

“Chưa xác minh” không đồng nghĩa “không noticed”. Citation mạnh nhưng ngoài gold phải ghi riêng, không tự sửa nhãn.

## Hồ sơ tối thiểu và hướng thiết kế

Mỗi liên kết cần có: **đoạn A + attribution → đoạn B + tác giả/quote-chain → cách A sử dụng nội dung**, kèm nguồn, nguyên văn, offsets và giới hạn. Hash/offset PASS chỉ xác nhận bytes, không xác nhận ngữ nghĩa.

Similarity hỗ trợ tìm kiếm; bước quyết định phải kiểm quan hệ nguồn. Sau đó tổng hợp các liên kết theo ngữ cảnh lên cấp bản án. Cách làm này còn cần kiểm chứng trên query mới trước khi dùng làm quy tắc dự đoán gold.

Tham khảo: [hồ sơ liên kết V3](coliee_task1_verified_gold_passages_v3/links.json), [bản đồ vị trí citation](coliee_task1_verified_gold_passages_v3/citation_location_map.json). Đây là annotation AI hỗ trợ, không phải passage-level human gold; cần kiểm với văn bản nguồn.
