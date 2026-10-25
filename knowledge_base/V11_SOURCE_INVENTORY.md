# Nguồn tham chiếu trước pilot V11

Lập từ năm bản án gốc trước khi chạy hai nhánh V11. Đây là danh sách cơ hội AU
để đánh giá calibration, do Codex nhận định; không phải human gold, không bảo đảm
đã liệt kê hết AU hữu ích và không được đưa vào prompt xây KB. `start` là tọa độ
ký tự của cụm mở đầu trên chuỗi nguồn UTF-8 đã giải mã; khi chấm phải đọc cả
đoạn cha và ngữ cảnh để xác định ranh giới AU.

| Án | start | Cụm mở đầu trong nguồn | Cơ hội cần kiểm tra |
|---|---:|---|---|
| `011904` | 8358 | “While the burden placed on claimants” | Điều kiện và giới hạn nghĩa vụ tìm bảo vệ của nhà nước; tòa không buộc người yêu cầu tự đặt mình vào nguy hiểm. |
| `011904` | 11687 | “I find Madam Justice Gauthier's approach” | Cách tòa đánh giá giả định về bảo vệ nhà nước tại Mexico và chứng cứ về khả năng bảo vệ thực tế. |
| `011904` | 15595 | “While the Board refers to the document” | Nghĩa vụ xem xét chứng cứ trái chiều về hiệu quả bảo vệ, thay vì chỉ nêu nỗ lực lập pháp. |
| `013009` | 7970 | “The issue of the admissibility of evidence” | Ranh giới sử dụng cáo buộc hình sự chưa xét xử trong quyết định hành chính. |
| `013009` | 9097 | “In my view, the similarities between the facts” | So sánh án được viện dẫn với vụ hiện tại và yêu cầu công bằng thủ tục khi dùng cáo buộc. |
| `013009` | 12230 | “I find that the officer erred” | Kết luận áp dụng về sai sót của officer; cần nối với lý do trước đó, không lưu riêng kết quả trần trụi. |
| `013948` | 13786 | “Because the Board did not rule on the issue” | Giới hạn hiệu lực quyết định cũ của Board đối với đánh giá rủi ro theo section 97. |
| `013948` | 14273 | “It is trite law that in PRRA applications” | Gánh nặng chứng minh của người yêu cầu PRRA. |
| `013948` | 15071 | “The PRRA officer was not required to take” | Officer đánh giá theo hồ sơ đã nộp; không phải tự tìm chứng cứ từ hồ sơ tị nạn cũ. |
| `045155` | 18540 | “The policy reasons for requiring applicants” | Quy tắc dùng hết biện pháp nội bộ và ngoại lệ khi chính cơ quan bị chất vấn không thể xét grievance đáng tin cậy. |
| `045155` | 23327 | “The disclosure obligations ought to be” | Nghĩa vụ tiết lộ ít nhất nội dung chính của cáo buộc để người bị ảnh hưởng trả lời. |
| `045155` | 23658 | “As a result, it is my view that the failure” | Tòa áp dụng nghĩa vụ tiết lộ vào việc giữ kín cáo buộc RCMP/CSIS. |
| `099980` | 75879 | “For all of the above-mentioned reasons” | Tòa giải thích vì sao quyền điều tra gian lận cần bảo đảm thủ tục cao hơn. |
| `099980` | 93242 | “In my view, the rules of procedural fairness required” | Yêu cầu tiết lộ tài liệu dự định dùng trước phỏng vấn người bị điều tra. |
| `099980` | 109086 | “Given the reasons provided above” | Phạm vi quyền chọn biện pháp khắc phục và chi phí sau khi xác định vi phạm. |

Các bẫy đánh giá từ nguồn: `045155` có headnote mô tả kết luận nhưng AU nên ưu tiên
phần thân chứa chính lập luận của tòa; `013948` có nhiều đoạn thuật lại PRRA
officer và Board, không mặc định là lời tòa; `099980` có phân tích về thẩm quyền
nhưng tòa nói rõ chưa đưa ra phán quyết cuối cùng về vấn đề đó. Một marker
`<FRAGMENT_SUPPRESSED>` không tự xác nhận nội dung pháp lý hoặc danh tính án.
