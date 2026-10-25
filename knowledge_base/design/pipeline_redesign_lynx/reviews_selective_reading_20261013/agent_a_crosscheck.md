H/P/I là đối chứng hợp lý, nhưng còn ba điểm yếu đáng kể; đây là phản biện thiết kế, chưa phải validation.

1. **Shortlist có thể thành hard filter trên thực tế.** P chỉ chọn trong shortlist H cấp thì khả năng phát hiện AU bị giới hạn bởi H; planner tốt cũng không cứu được vùng chưa được đưa vào.  
   **Sửa:** ngoài shortlist ưu tiên, host cấp discovery độc lập theo ordinal và vị trí trong block dài, gồm vùng không citation/heading. Cho P đề nghị nhảy vùng ngoài shortlist bằng navigation ID; host giới hạn số lần và kích thước.  
   **Phép quyết định:** đặt proposition citation-free giữa block không heading, ngoài shortlist; hoán đổi vị trí dưới cùng budget. So H, H+discovery và P+discovery về tỷ lệ đọc đúng vùng và giữ qualification. Nếu P chỉ cải thiện vùng H đã chọn, chưa chứng minh lợi ích khám phá.

2. **“Planner một lần” chưa giải quyết context xa; interactive chỉ dành nghiên cứu có thể khiến production mắc kẹt.** Speaker ở đầu, proposition ở giữa, phản bác ở cuối không thể luôn xử lý bằng expansion lân cận.  
   **Sửa:** cho host thực hiện một batch context-resolution theo obligations: gom câu hỏi attribution/response/exception, chạy local search có cap, rồi gửi chung vùng nguồn được chọn trong lượt assessment kế tiếp. Chỉ replan hữu hạn khi batch đó vẫn thiếu; hết cap giữ unresolved. Find hits không thành evidence trước khi đọc.  
   **Phép quyết định:** phân tán các thành phần qua nhiều block; đo AU sai attribution, unresolved, tổng lượt và token. So expansion tuần tự với batch resolution; không chỉ đếm số tool calls.

3. **Budget có cap vẫn có thể “đạt” bằng giảm chất lượng hoặc chọn denominator sai.** Khoảng 70k token của 30 targets không phải baseline toàn án.  
   **Sửa:** khóa baseline exhaustive theo từng án trước pilot; cap navigation/search riêng nhưng reserve assessment/context, tính cả lỗi và resume. Acceptance profile phải có phiên bản; giao dịch assessment commit trước next intent.  
   **Phép quyết định:** cùng ngân sách, so H/P về proposition retention và qualification trên reference xác định rõ; crash giữa commit/action phải không lặp assessment. Model-silver chỉ chứng minh agreement tương đối, không chứng minh đủ AU.
