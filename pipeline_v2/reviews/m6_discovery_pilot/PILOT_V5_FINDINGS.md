# Kết quả pilot M6 hybrid và bản sửa controller

Pilot discovery `runs_v5` có ba run terminal, 10 request controller, 55.216 input token, 787 output token, một embedding 32 token và 0 retry. Có 0/12 gold vào candidate pool. Selector chưa có nên final F1 là null. [Báo cáo đối chiếu gold](runs_v5/gold_diagnostic.json)

| Query | Dấu vết | Điểm cần sửa |
|---|---|---|
| `017984.txt` | Action seq 4 dừng `complete_policy` ngay lượt đầu | Controller cho báo hoàn tất trước khi thực hiện search |
| `090579.txt` | Seq 4 tìm `t`, seq 8 và 12 mở hai B, rồi chạm cap payload | Schema chấp nhận query thoái hóa. Sau khi mở B, raw A chưa được nạp lại trước lần mở kế tiếp |
| `021095.txt` | Seq 16, 20, 24 lặp continuation đã thực thi | Catalog vẫn cấp cursor cũ. Khi payload thiếu raw A, tool tìm theo issue tạm thời không khả dụng |

Chỉ `090579.txt` thực sự chạy hybrid. Embedding RPC mất khoảng 5.079 giây trong khi remote inference ghi 0,63 giây. Chênh lệch cho thấy thời gian nằm chủ yếu ngoài inference. Ledger hiện không tách riêng bao nhiêu là queue, cold start hay thời gian chờ khác. Kết quả này đo hành vi của controller trên pilot nhỏ. Với query `t` và top 3, không đủ bằng chứng để quy 12 miss cho xếp hạng M3.

Controller revision v2 chỉ mở `complete_policy` sau một search đã trả kết quả, từ chối issue dưới hai từ hoặc bốn ký tự trước retrieval, bỏ các navigation binding đã chạy và tính reload không có tiến triển vào ngưỡng dừng. Prompt hướng model đánh giá cặp đã mở, hoặc nạp lại raw A/B nếu thiếu, trước khi mở thêm B. Các thay đổi chưa xác nhận cải thiện recall live.

`runs_v5` giữ nguyên. Dùng `runs_v7` cho lượt kiểm tiếp, giữ cùng query và caps để đọc thay đổi về hành vi. Kiểm query đầu trước khi chạy tiếp. [Quy trình chạy và đối chiếu](README.md)
