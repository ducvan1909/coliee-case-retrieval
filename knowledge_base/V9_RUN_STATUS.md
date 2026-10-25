# Trạng thái lần chạy pilot V9

Ngày 2026-09-26, đã chạy `099980` trong `outputs/pilot_v9/calibration/099980`.
Batch dừng ở case này; bốn án calibration còn lại chưa được gọi.

- `execution_status=incomplete`, `protocol_status=failure`,
  `output_status=incomplete`, `quality_status=not_evaluated`.
- Reader đã hoàn tất lượt đọc và chuyển sang sửa lựa chọn nguồn. Lỗi V8
  `read_window_ids=[]` ở cuối vòng đọc không tái diễn.
- Lượt sửa lựa chọn trả 9 thao tác. Host áp dụng 6 thao tác hợp lệ, để lại bản
  nháp 4 brief và 2 AU. Ba AU khác bị bác vì `response_source_ids` chưa nằm
  trong `source_refs` (`treatment_source_not_selected`).
- Protocol repair bổ sung các nguồn còn thiếu vào ba AU, nhưng cả ba entry
  thiếu trường bắt buộc `resolution:"replace"`. Host ghi
  `repair_error_code=invalid_replacement`, giữ ba rejection chưa giải quyết
  và dừng trước lượt sửa phân loại/finalizer.
- `case.json` và report V9 đều dùng `output_status=incomplete`. Các mục đang
  lưu là bản nháp; chưa có KB cuối để đánh giá ngữ nghĩa.
- Có 9 request logic được ghi dự phòng 0,25 USD/request; sổ chung tăng từ
  107,75 lên 110,00 USD. Đây là dự phòng nội bộ, không phải chi phí Modal.

Response, checkpoint và case gốc được giữ nguyên. Trường hợp này cho thấy
prompt sửa *operation* cần một ví dụ JSON đầy đủ chứa `resolution`, và bài
kiểm thử cần tái hiện chính entry thiếu trường đó. Không sửa prompt trong
experiment V9 để chạy lại calibration.

## Lần chạy `pilot_v9_operation_fix`

Ngày 2026-09-26, đã chạy mới `099980` với prompt
`kb-pilot-v9-operation-repair-2` và endpoint tài khoản `g38180254`. Batch tiếp
tục dừng ở case đầu; bốn án còn lại không được gọi.

- Các lỗi mục tiêu đã được sửa trong code và fixture: hợp đồng repair bắt buộc
  `resolution`, và lỗi treatment chỉ rõ danh sách cùng handle chưa nằm trong
  `source_refs`.
- Lần chạy thật không phát sinh operation rejection. Bản nháp có 4 brief và 3
  AU sau 3 response chính; vì vậy lần chạy này chưa trực tiếp kích hoạt lại
  tình huống thiếu `resolution` cũ.
- Request tiếp nối của `selection_repair` sai ở hai điểm: tiếp tục yêu cầu đọc
  cửa sổ dù đây là continuation, và đánh dấu `item_checks[2].decision=update`
  nhưng không gửi operation update tương ứng.
- Host tạo `allowed_control_patch_fields=["action","item_checks[2]",
  "read_window_ids"]`. Đây là lỗi hợp đồng host mới lộ ra: đường dẫn phần tử
  `item_checks[2]` không phải tên trường top-level có thể chép trực tiếp vào
  `control_patch`.
- Model làm đúng payload sai đó và trả khóa `item_checks[2]` trong
  `control_patch`. Khi ghép lại response, khóa này trở thành trường ngoài hợp
  đồng, nên hai protocol error vẫn chưa giải quyết và case dừng trước các vòng
  sửa phân loại/finalizer.
- Trạng thái cuối là `execution_status=incomplete`, `protocol_status=failure`,
  `output_status=incomplete`, `quality_status=not_evaluated`; không có
  `empty_output` hợp lệ. Tổng dự phòng nội bộ của lần chạy là 1,00 USD cho bốn
  request logic; sổ chung hiện là 113,25 USD.

Artifacts và report của experiment được giữ nguyên. Không sửa prompt hoặc chạy
lại trong cùng experiment này.
