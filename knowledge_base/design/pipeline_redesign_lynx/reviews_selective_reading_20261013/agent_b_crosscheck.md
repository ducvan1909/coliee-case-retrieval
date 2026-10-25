Tôi đồng ý giữ batch-plan nhiều vùng và chỉ replan theo trigger rõ. Evidence p59 do reviewer A cung cấp củng cố nhu cầu discovery **bên trong block dài**, nhưng chưa chứng minh policy sampling sẽ tìm đủ AU. Ba điểm yếu còn material:

1. **P1 — Thêm assessment fields có thể vượt output cap hoặc tạo “đủ trường giả”.**  
   Attribution/response/condition/exception/limit không luôn hiện diện hoặc xác định được trong vùng đọc. Ép mỗi component có status và witness làm output phình, dễ truncation; model cũng có thể chọn `not_applicable` để hoàn tất schema.  
   **Sửa:** Mỗi component phân biệt `supported`, `unresolved`, `not_applicable`; absence chỉ áp dụng trong phạm vi đã assessment, không toàn án. Host chia batch theo cả input và output reservation.  
   **Phép phân xử:** Region nhiều AU, mỗi AU có qualification khác nhau; cap phải cho kết quả đầy đủ hoặc giữ phần chưa commit unresolved, không âm thầm bỏ component/AU.

2. **P1 — Witness predicate vẫn dễ đánh đồng source validity với semantic support.**  
   Quote nằm trong TARGET chỉ chứng minh địa chỉ/ownership kỹ thuật. Nó chưa chứng minh claim, speaker hay việc tòa chấp nhận proposition; response ở xa và exception phía sau có thể đảo nghĩa. Tách primary/supporting refs là cần thiết nhưng chưa đủ.  
   **Sửa:** Tách host predicate `source_valid` khỏi model assessment về support từng component; không tự suy semantic support từ membership. Publication gate phải xử lý rõ component unresolved.  
   **Phép phân xử:** Cùng primary quote, thay previous attribution hoặc later exception; source checks vẫn PASS nhưng semantic/publication outcome phải thay đổi phù hợp.

3. **P2 — Within-block discovery có thể tái tạo chi phí đọc toàn văn qua nhiều lượt nhỏ.**  
   Sampling nhiều cửa sổ cộng overlap, catalog và context expansion có thể đắt hơn một region rộng. First/last previews trùng nhau còn tiêu ngân sách mà không tăng thông tin.  
   **Sửa:** Deduplicate previews/spans; reserve discovery theo token, ghi unique/repeated source tokens. Seed/policy fingerprint bảo đảm replay, không chứng minh recall. Host chuyển sang wide-read có cap khi chi phí cửa sổ tích lũy bất lợi.  
   **Phép phân xử:** So windows với wide-read trên cùng block, tính toàn bộ overhead. Query-lazy tương lai không được tính là đã cứu AU bị bỏ sót hôm nay.
