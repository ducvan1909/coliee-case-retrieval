# K0: chẩn đoán AU rỗng — 2026-10-23

## Kết quả

| Kiểm tra | Kết quả |
|---|---|
| CPU native 2 grammar probe: 8 positive/6 negative, 570 token | PASS, không có mask chặn token AU; EOS đúng |
| CPU exact grammar 5 request K0 cũ | PASS, cả5 cho phép AU không rỗng |
| Endpoint synthetic + grammar K0 | JSON hợp lệ nhưng 0 AU, thất bại positive control |
| Endpoint cùng synthetic, bỏ grammar | Sinh quy tắc đúng nội dung notice/opportunity to respond và ngoại lệ emergency; sai envelope AU/keys và limits là array, không phải contract K0 |
| Endpoint cùng nguồn011904, authoring một lượt | 0 AU dù đã bỏ search/open khỏi action |

3 POST chẩn đoán, không retry; input2478 + output199 =2677 token provider. Không chạm output800 hoặc input6000, finish_reason đều stop, reasoning_content null. Local30test PASS. K0 package/workload/live checkpoint giữ nguyên hashes.

## Diễn giải

Không thấy lỗi cú pháp grammar hoặc token mask CPU khiến nhánh AU không thể sinh. Runtime xác nhận SGLang0.5.19/XGrammar0.2.1 và stop248044/248046 trùng CPU. Tuy nhiên CPU replay không chứng minh phân bố logits lúc generation. Synthetic có/không grammar khác hành vi dù prompt/nguồn giống nhau, nên cần ưu tiên tương tác model–contract–constrained decoding. Không đủ bằng chứng kết luận XGrammar hỏng, model không biết pháp lý, hoặc chỉ lỗi planner.

Nguồn thật có các điểm pháp lý như không buộc tự đặt mình vào nguy hiểm khi tìm bảo vệ và yêu cầu bảo vệ hiệu quả; outputrỗng không thể xem là thành công semantic. Bỏ navigation vẫn không cóAU nên chỉ sửaplanner chưa giải quyết được lỗi trong phép thử này. Nguồn tổng hợp ngoài grammar cho thấy model nhận ra rule/exception nhưng không tự giữ đúng wire. Chưa có AU thật để chấm grouping/attribution/qualification. Không mở K1 hoặc coi tokenít là tiết kiệm.

## Thử tiếp đề xuất, chưa thực hiện

Giữ nguồn tổng hợp, model và caps; đưa một ví dụ JSON đầy đủ chỉ dạy cấu trúc, rồi so cùng grammar với prompt hiện tại. Nếu vẫnrỗng, đối chứng grammar JSON tổng quát/JSON schema nhỏ, giữ host validation. Không bắt AU không rỗng trên bản án thật. Chỉ quay lại authoring/navigation sau khi positive control tạo được AU hợpcontract và giữ ngoại lệ.

## Vận hành và giới hạn chi phí

Warmupclient339s mớiready; health503/no upstreams available, log có Durable gateway startup failed rồi container khởi động lại. Đây là lỗi startup trước probe, không phải grammar K0 chạy lâu. Requestinference server tổng khoảng5.25s; thời gian chờ gồm coldstart/gateway và poll. Runtime của container phục vụ thành công ghi 1 internalwarmup40token; cộng phần quan sát được là2717token. Không biết usagewarmup của container thất bại trước đó, nên không coi2717 là chi phí toàn bộ đợt. Không deploy hoặc sửa server.
