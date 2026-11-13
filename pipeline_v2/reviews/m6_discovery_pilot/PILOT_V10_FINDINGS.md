# Pilot v10: lỗi kiểm phản hồi trước retrieval

Cả ba query nhận phản hồi Modal với `finish_reason=stop`. Mỗi ledger có bốn event: tạo run, nhận request, ghi kết quả request và dừng. Tổng usage là 3 request controller, 16.179 input token và 147 output token. Không có action, embedding hoặc lượt tìm hybrid. [Gold diagnostic](runs_v10/gold_diagnostic.json)

`0/12` là độ phủ candidate pool của pilot. Điểm dừng của hệ thống nằm trước retrieval. Cờ `first_gap=retrieval` trong bản chấm v10 chỉ cho biết án gold chưa vào pool. Nó không chỉ ra bước gây lỗi.

Receipt xác nhận provider đã trả kết quả. Run v10 chỉ ghi `transport_error`, nên không thể xác định từ artifact liệu phản hồi lỗi JSON, vi phạm schema, gửi issue không hợp lệ, dùng handle sai hay gặp lỗi bên trong quá trình dịch action. Các run v10 giữ nguyên để đối chiếu.

Kiểm local với phản hồi mẫu hợp lệ trên ba payload v10 đã lưu xác nhận các handle được cấp có thể đi qua validator. Lượt chẩn đoán mới giữ schema và caps, bổ sung `request_result.m6_reply` chứa raw reply và lý do bị từ chối, kèm stage và đường dẫn trường khi có. Bộ chấm ghi riêng có action tìm hay chưa. Chạy query đầu trong `runs_v11` và đọc ledger trước khi chạy hai query sau. [Lệnh chẩn đoán](README.md)

`runs_v11/017984.txt` ghi raw reply có `issue="w"` và handle hợp lệ `p000002`. Host từ chối tại `args.issue` với `minLength`. Điều này chưa cho biết model ưu tiên một ký tự hay grammar chỉ cho phép chuỗi đó. Cấu hình deployment chọn XGrammar, nhưng receipt v11 chỉ chứng thực phiên bản vLLM. [Ledger v11](runs_v11/017984.txt/events.sqlite3) · [Phép thử grammar](ISSUE_GRAMMAR_CANARY.md)
