# Pilot V10: trạng thái lần xác nhận đầu

Ngày 2026-09-26, `pilot_v10` dùng `schema_version=10`, prompt
`kb-pilot-v10-constrained-choices-1`, endpoint tài khoản `g38180254` và model
`openai/gpt-oss-120b`. Ba probe cho enum động, quyết định theo item và nhánh
treatment đều qua kiểm tra schema. Probe đầu tiên bị sandbox chặn trước khi tới
endpoint; khoản dự phòng được hoàn sau khi HEAD ngoài sandbox xác nhận đường
kết nối. Request probe sau đó được ghi là retry của lần bị chặn.

Chỉ `099980` được chạy. Case dừng tại `selection:1` với
`execution_status=incomplete`, `protocol_status=failure`,
`output_status=incomplete`, `quality_status=not_evaluated`. Bốn án calibration
còn lại chưa được gọi.

Response của `selection:1` có `finish_reason=length`: request chứa 68.427
prompt token; model dùng hết 4.096 completion token, trong đó 2.054 là
reasoning token. Host lưu nguyên response thô, không áp dụng một phần và không
gọi model sửa giao thức. Bản nháp hiện có 1 brief và 1 AU; đây không phải KB
cuối để đánh giá ngữ nghĩa.

Kiểm tra trực tiếp 33 excerpt của hai item bản nháp: 33/33 khớp chuỗi nguồn
tại tọa độ ký tự; SHA-256 nguồn khớp manifest. Hai thao tác add có lịch sử.
Report nằm trong `outputs/pilot_v10/report.json`; response và checkpoint giữ
trong `outputs/pilot_v10/calibration/099980`. Tổng 6 request case và 3 probe
thành công giữ 2,25 USD dự phòng nội bộ; đó không phải chi phí Modal đo được.

Nguyên nhân cần xử lý trước một experiment mới: request sửa lựa chọn gửi lại
quá nhiều nguồn đã mở cùng schema/payload, khiến câu trả lời bị cắt ở giới hạn
output. Cần giới hạn nguồn trong mỗi lượt vào phần mới mở và ngữ cảnh của item
đang xét, đồng thời kiểm tra kích thước prompt/đầu ra dự kiến. Không sửa prompt
hoặc fingerprint rồi resume experiment này để làm đẹp calibration.

Bản sửa tiếp theo dùng `pilot_v10_scoped_source`, prompt
`kb-pilot-v10-scoped-source-2`. Kiểm tra offline với trạng thái `selection:1`
của `099980` và kích thước cửa sổ 10.000 ký tự: số đoạn gửi giảm từ 149 còn 64,
payload JSON từ 252.711 còn 108.516 ký tự, schema từ 18.691 còn 9.430 ký tự.
Đây là giảm kích thước request, không phải bằng chứng model đã hoàn tất; kết quả
`pilot_v10` cũ vẫn giữ nguyên.

Lần thử `pilot_v10_scoped_source` sau đó dừng trước request án: capability
probe dùng lại request ID dựa trên schema của `pilot_v10` cũ, trong khi cache
thuộc experiment mới chưa có. Sổ ngân sách đã có request cũ hoàn tất nên host
chặn phát lại. Không có khoản dự phòng mới cho lần lỗi này. Bản sửa định danh
probe theo experiment/fingerprint và chuyển mặc định sang
`pilot_v10_scoped_source_probe_fix`.

Năm án trong experiment này đã hoàn tất kỹ thuật: không có lỗi giao thức,
91/91 excerpt khớp nguồn, 82 thao tác có trace. Phiếu Codex review đã điền
166 thành phần nhưng giữ adjudication của con người ở trạng thái chờ. Kết quả
ngữ nghĩa còn lỗi rõ về brief kind, attribution, treatment và lựa chọn AU;
chưa mở 20 án. Xem `outputs/pilot_v10_scoped_source_probe_fix/`
`V10_CODEX_REVIEW_COMPARISON.md` để đối chiếu từng án với KOS.
