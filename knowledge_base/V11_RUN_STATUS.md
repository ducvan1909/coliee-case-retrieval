# Trạng thái pilot V11 (27-09-2026)

Mã V11 và danh sách cơ hội AU từ nguồn đã được chuẩn bị. Kiểm thử cục bộ đạt
96/96; `compileall`, kiểm tra khoảng trắng và `preflight` đạt. Ba probe Control
và năm probe Guided đều đạt trên endpoint đã cấu hình.

Các experiment đã dùng cho lần xác nhận cuối là
`pilot_v11_reading_control_r2` và `pilot_v11_reading_guided_r2`. Hậu tố `r2`
giữ nguyên các artifact probe trước đó và cô lập request identity sau khi sửa
va chạm ID với một experiment V10 cũ.

Request reader đầu tiên của `099980` trong Control nhận 12 lần HTTP 503, sau
đó `RemoteDisconnected`. Ledger ghi `failed_or_uncertain` và giữ 0,25 USD dự
phòng nội bộ; không có response cache. Không thể chứng minh inference đã hoặc
chưa được thực hiện. Theo điều kiện dừng của thử nghiệm, chưa chạy Guided cho
án này hoặc bốn cặp còn lại. Chưa có đầu ra KB V11 để đánh giá ngữ nghĩa hay
so sánh tác động chính sách đọc.

Artifact: `outputs/pilot_v11_reading_control_r2/calibration/099980/failure.json`
và `checkpoint.json`; báo cáo `report` nhận diện `incomplete_without_case`.
Không tự dùng `--resume` hoặc retry request chưa rõ kết quả. Nếu quyết định
chấp nhận khả năng một inference đã xảy ra, cần cho phép rõ việc chạy request
mới, giữ artifact cũ và mở một cặp experiment mới với fingerprint không đổi.

## Cặp chạy lại được cho phép

Sau khi được cho phép rõ, mở cặp mới `pilot_v11_reading_control_r3` và
`pilot_v11_reading_guided_r3`, không thay mã hoặc cấu hình. Ba probe Control và
năm probe Guided đều đạt. `099980` hoàn tất ở cả hai nhánh, giao thức hợp lệ:
Control lưu 9 brief và 11 AU; Guided không giữ brief/AU cuối, defer 3 item.
Guided chỉ dùng 2/7 lượt mở nguồn rồi dừng; đây là quan sát của một án, không
chứng minh marker nói chung làm giảm chất lượng.

`013948` Guided dừng ở `selection:0` với `invalid_constrained_response`.
Response có `finish_reason=length`, dùng hết 4.096 completion tokens, chứa
`source_ids` lặp `P0029` nhiều lần và JSON bị cắt. Host không áp dụng response
này; Control của `013948` và ba cặp sau không chạy, đúng cổng dừng khi có lỗi
giao thức. Probe nhỏ đã đạt không bảo đảm endpoint tuân thủ schema trong
request phức tạp này. Giữ nguyên response và checkpoint để chẩn đoán; không
sửa prompt hoặc chạy lại án trong cùng experiment.

Nhận xét ngữ nghĩa sơ bộ cho `099980` (agent review, chưa phải human gold):
ba vị trí cơ hội AU đã khóa trước ở offset 75.879, 93.242 và 109.086 đều
không có trong AU cuối của cả hai nhánh. Control đã mở vùng 75.879 nhưng không
chọn; hai vùng còn lại chưa mở. Guided chưa mở cả ba vùng. Mười một AU Control
tập trung ở khoảng 61.970–69.900, gồm cả trích dẫn authority và nội dung
trông giống giá trị của Commission; vì thế số AU cao không được coi là chất
lượng tốt. Việc đọc log Guided trước khi hoàn tất đánh giá chi tiết khiến
nhận xét này không hoàn toàn mù với quá trình chạy.

Kiểm tra trực tiếp 20 excerpt của Control và 12 excerpt của Guided trong
`099980`: tất cả khớp chính xác lát cắt nguồn theo vị trí. Control dùng 10
request án, 371.807 prompt tokens; Guided dùng 7 request, 92.330 prompt
tokens. Đây là số token endpoint báo, không phải chi phí USD thực tế. AU
Control `099980:aus:008` gắn `current_court` cho đoạn mở bằng “Justice Sopinka,
speaking for the majority, stated...” rồi trích lời ông; nhãn chủ thể này sai
cho phần trích. AU kế tiếp bắt đầu giữa câu của cùng trích dẫn. Vì vậy Control
có lỗi ngữ nghĩa rõ, không thể lấy 11 AU làm bằng chứng chất lượng.

Sau khi dừng đợt r3, sửa CLI để case `incomplete` trả exit code 2 thay vì 0;
thêm kiểm thử, tổng 97/97 đạt. Đây là thay đổi mã sau experiment: không resume
r3 bằng fingerprint mới hoặc dùng r3 để tuyên bố đã chạy đủ năm cặp.
