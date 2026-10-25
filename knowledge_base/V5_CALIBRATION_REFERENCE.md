# Bảng tham chiếu calibration V5

Tài liệu này dùng để kiểm tra đầu ra sau khi chạy, không được đưa vào prompt và
không phải gold. Các dòng dưới đây chỉ là giả thuyết kiểm tra rút từ hiện tượng
V4; người đánh giá phải đọc lại nguyên văn và có thể bác chúng.

| Case | Hiện tượng V4 cần hồi quy | Ứng viên nguồn cần đọc trực tiếp | Câu hỏi kiểm tra V5 |
|---|---|---|---|
| 013948 | `found` nhưng không có operation/AU | `s-1571876439f1-00006216-00006633`, `s-1571876439f1-00010237-00010556`, `s-1571876439f1-00010619-00010766`, `s-1571876439f1-00010828-00010960` | Lượt bổ sung có tạo AU đủ căn cứ hoặc sửa outcome nhất quán không? |
| 045155 | `found` nhưng không có operation/AU | vùng ký tự 23649–32061 mà finalizer V4 tự khai đã kiểm tra | Có cơ hội AU thật hay V4 chỉ nêu ứng viên trong reasoning? Outcome rỗng phải được kiểm tra trực tiếp. |
| 011904 | Control sai nhưng năm operation hợp lệ | AU V4: 3958–4329 và 5394–5679 | Chỉ vá `read_window_ids`; không mất operation, không dùng rejection `envelope`; `applies` có thật sự được chứng minh không? |
| 013009 | Một operation treatment sai làm repair hỏng cả lượt | AU V4: 7964–8332 và 11268–11511 | Operation hợp lệ còn nguyên; operation sai được sửa độc lập; verifier chỉ dùng handle và không tự gọi bác lập luận đương sự là `rejects` authority. |
| 099980 | Có hai AU nhưng treatment còn đáng ngờ | 542–728 + 839–1026; 8921–9206 + 9333–9432 | Citation/quyền hạn có đủ cho `applies` không; khác biệt tình tiết có thật sự là `distinguishes` authority không? |

Khi nghiệm thu, ghi riêng: item accepted, needs_review, rejected, lỗi giao thức,
đầu ra rỗng, cơ hội AU bị bỏ sót và phần nguồn chưa đọc. Số AU hoặc coverage
không thay thế đánh giá nội dung.
