# Kiểm tích hợp M6 hybrid

Profile `channel=hybrid` chuyển issue do controller sinh sang đường M3 sparse hybrid đã nghiệm thu. Giữ BM25 cấp án, BM25 passage, dense exact, RRF k=60 và coverage. Host giữ tham số tìm kiếm và mở passage theo refs từ kết quả M3. Mỗi embedding có cap input/request riêng và liên kết từ action M6 sang ledger M3.

97 kiểm thử local liên quan đạt, gồm hai issue khác nhau, mở dense lead để assess, cap token trước gọi, giữ usage khi dense lỗi và resume sau embedding bị ngắt. Lượt review độc lập bị gián đoạn do giới hạn dịch vụ agent.

- [Lượt Qdrant local đạt](cached_run_v2/report.json) với query case `095448.txt`, vector passage đã cache, đúng thứ tự RRF ba án, 5 lượt controller giả lập và một assessment qua validator. Hybrid mất 35,06 giây, trong đó Qdrant exact mất 27,72 giây. Tokenizer đếm 52.338 input token qua các lượt giả lập. Resume giữ nguyên một lượt hybrid. Có 0 request Modal.
- Lượt Qdrant local đầu dừng với HTTPError sau 123,20 giây và 0 embedding. Giữ [ledger lỗi](cached_run_v1/embedding_events.sqlite3). [Replay từ kết quả Qdrant đã lưu](recorded_replay_v1/report.json) cũng đi đủ vòng M6.
- [Preflight live](live_preflight_v1/plan.json) sẵn sàng với 9.199 input token ở payload đầu và 0 request model. Profile giới hạn một embedding và tám lượt controller. [Lệnh chạy cho người dùng hoặc AG](../../docs/M6_ADAPTIVE.md).

Gate còn lại là chạy controller và query embedding live. Số token replay thuộc prompt giả lập. Chưa có số đo chất lượng COLIEE hay so sánh M5/M6.
