# Kiểm tra lại cổng giao thức V7

Đây là bản kiểm tra sau khi đã lưu kết quả V7; không thay đổi `pilot_v7_au_priority`.

`099980` đã được báo `completed/valid` nhưng lượt `selection_repair_0` không hợp lệ.
Response thô gồm hai JSON nối tiếp nên không parse được. Nội dung đó yêu cầu mở
cửa sổ 1. Host biến response lỗi thành control mặc định `complete` với
`operations=[]`. Protocol repair trả `control_patch={}` và một `rejection_id`
không có trong danh sách hợp lệ. Host vẫn đánh dấu lỗi control đã giải quyết;
`invalid_repair_entry` chỉ nằm trong log repair, không tham gia điều kiện dừng.
Do đó cửa sổ 1 không được mở và trường hợp này **không đạt cổng kỹ thuật**.

Các tệp chứng cứ cần giữ nguyên:

- `outputs/pilot_v7_au_priority/calibration/099980/responses/selection_repair_0.raw.json`
- `outputs/pilot_v7_au_priority/calibration/099980/responses/selection_repair_protocol_repair_0.json`
- `outputs/pilot_v7_au_priority/calibration/099980/checkpoint.json`
- `outputs/pilot_v7_au_priority/calibration/099980/case.json`

`outputs/pilot_v7_au_priority/AGENT_REVIEW.md` được lập trước khi phát hiện lỗi
này. Nhận định “năm case đều completed/valid” và “cổng kỹ thuật đạt” trong đó
không còn đúng. Các nhận định ngữ nghĩa vẫn là đánh giá sơ bộ của agent, không
phải nhãn gold. V8 sử dụng experiment mới và không sửa các phản hồi V7.
