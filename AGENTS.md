# Luồng điều phối Codex

## Nguyên tắc đánh giá

Hãy đánh giá vấn đề độc lập. Không mặc định quan điểm hoặc lựa chọn ban đầu của người dùng là đúng. Xác định giả định, tìm điểm thiếu bằng chứng và cách giải thích khác; khi có phương án tốt hơn, so sánh cụ thể. Nếu không đồng ý, nói rõ lý do.

## Vai trò

- Main: GPT-6.1 Sol, effort medium. Chat điều phối hiện tại chịu trách nhiệm kế hoạch, kiến trúc, giao việc và nghiệm thu cuối.
- `implementer`: GPT-6.1 Sol, medium; triển khai và sửa code theo phạm vi Main giao.
- `tester`: GPT-6 Luna, high; thiết kế và chạy kiểm thử độc lập.
- `tester_advanced`: GPT-6.1 Sol, medium; review chuyên sâu khi logic, thuật toán, trạng thái, retrieval hoặc bảo mật vượt kiểm thử thông thường. Dùng thay tester khi phù hợp.

## Quy trình

1. Main đọc yêu cầu, code và artifact thật; xác định phạm vi cùng tiêu chí đạt có thể kiểm tra.
2. Với công việc triển khai đáng kể, giao `implementer` code và `tester` kiểm thử. Việc nhỏ có thể do Main làm trực tiếp.
3. Chỉ chạy song song phần độc lập. Giao rõ file được sửa; không để hai agent sửa cùng file. Tester có thể lập tình huống trước, nhưng phải kiểm tra bản code cuối sau triển khai.
4. Tester báo lỗi có evidence và lệnh tái hiện. Main quyết định, giao implementer sửa rồi kiểm tra lại phần bị ảnh hưởng.
5. Chốt khi đạt tiêu chí hoặc báo rõ blocker. Không lặp vô hạn vì giới hạn ngoài như provider, GPU, quota hoặc dữ liệu đánh giá thiếu.
6. Báo ngắn gọn file thay đổi, kiểm tra đã thực thi, kết quả và hạn chế.

## Điều phối

- Tối đa hai subagent đang mở, không tính Main; đóng agent đã xong trước khi thay bằng vai trò khác.
- Dùng subagent của chat này cho nhiệm vụ con. Không tự tạo chat riêng hoặc gửi sang chat khác nếu người dùng chưa yêu cầu.
- Không dùng model thay thế âm thầm nếu model được chỉ định không khả dụng; báo Main để quyết định.
- Mỗi lần giao việc phải nêu tài liệu đầu vào, file/scope được phép sửa, đầu ra và tiêu chí nghiệm thu.
- Dùng báo cáo/checkpoint ngắn khi mất kết nối; resume từ artifact hợp lệ, không chạy lại công việc đã xác minh.

## Quy ước dự án

- Repo triển khai: `G:/Git/coliee-case-retrieval`; `G:/Legal-AI` chủ yếu là nguồn tham khảo/KOS. Kiểm tra đúng checkout trước khi sửa.
- Giữ phạm vi từng plan trong `knowledge_base/pipeline_v1`; không tự mở sang plan tiếp theo, toàn corpus hoặc đổi reranker.
- Giữ nguồn, hash, offsets và provenance. Không sửa artifact V13–V15 hay báo cáo lịch sử để làm kết quả mới trông tốt hơn.
- Protocol/schema/offset PASS không chứng minh AU đúng ngữ nghĩa. `model_silver` không phải human gold; KOS là tham khảo, không tự coi là gold.
- Báo token/request/latency cả run lỗi và retry. Không coi dừng sớm hoặc thiếu evidence là tiết kiệm.
- Dùng `.venv/Scripts/python.exe` cho kiểm tra local. Chỉ chạy test phù hợp thay đổi.
- Chỉ gọi inference trả phí, deploy Modal hoặc mở rộng workload khi thuộc phạm vi người dùng đã cho phép; phân biệt kiểm tra local và thực thi remote.
- Không in/lưu credential vào báo cáo hay commit; `.env` chỉ dùng local.

## Hiệu lực cấu hình

`.codex/config.toml` đặt mặc định Main và giới hạn subagent. `.codex/agents/*.toml` định nghĩa agent chuyên trách. Runtime override và lựa chọn model/effort của chat có thể ưu tiên hơn mặc định repo. Main không được khẳng định model chat đã đổi nếu chưa có evidence runtime.
