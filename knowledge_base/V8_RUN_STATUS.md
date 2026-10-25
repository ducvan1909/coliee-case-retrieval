# Trạng thái lần chạy pilot V8

Ngày 2026-09-26, đã chạy case đầu tiên `099980` trong
`outputs/pilot_v8/calibration/099980`. Batch dừng tại case này theo điều kiện
giao thức; bốn case còn lại chưa được gọi.

- `execution_status=incomplete`, `protocol_status=failure`.
- 8 request logic: 7 lượt reader và 1 lượt protocol repair.
- Reader đã được cung cấp toàn bộ 14 cửa sổ; độ phủ hợp khoảng ký tự là
  khoảng 99,67%. Không có thao tác tạo item nào được áp dụng.
- Lượt `reader:6` trả `action=read`, `read_window_ids=[]` khi không còn cửa sổ
  chưa đọc. Validator báo `requested_window_not_unread`.
- Lượt protocol repair trả `control_patch={}` và dùng ID của lỗi control trong
  `repairs[]`, trong khi danh sách rejection của operation rỗng. Host ghi
  `invalid_repair_entry`, giữ lỗi chưa giải quyết và dừng đúng.
- `case.json` ghi `output_status=empty_output` vì chưa có item trong bản nháp;
  đây **không phải** một KB cuối rỗng hợp lệ vì finalizer chưa chạy.
- `quality_status=not_evaluated`. Không có cơ sở chấm ngữ nghĩa đầu ra cuối.
- Sổ chung tăng dự phòng từ 105,75 lên 107,75 USD; đây là dự phòng nội bộ,
  không phải chi phí Modal thực tế.

Không sửa response, checkpoint hoặc nhãn của V8. Bước kế tiếp cần một phiên
bản/experiment mới: cho protocol repair của lỗi control ví dụ patch cụ thể
(`action=finalize` khi `read_window_ids=[]`), và báo trạng thái output chưa
hoàn tất tách khỏi `empty_output` hợp lệ. Sau đó mới thử lại và đánh giá năm
án; không dùng lần chạy này để kết luận về chất lượng AU.
