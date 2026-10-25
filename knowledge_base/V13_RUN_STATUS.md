# Pilot V13: trạng thái calibration (2026-09-28)

Experiment hiện tại: `outputs/pilot_v13_extract_before_navigate_local_scan`.
Các lần thử V13 trước đó được giữ trong thư mục riêng để truy nguyên lỗi
chồng lấn đoạn/câu, phạm vi rà nguồn, schema phân loại quá lớn và trần rà
nguồn. Không gộp kết quả của chúng với experiment hiện tại.

## Kiểm tra triển khai

- 115 unit test KB, `compileall`, kiểm tra khoảng trắng và preflight đạt.
- Chín capability probe của experiment hiện tại đạt trên endpoint Modal.
- Đầu ra V13 dùng `quality_status=not_evaluated`; `completed` chỉ là trạng
  thái thực thi.
- Mức 0,25 USD/request là dự phòng nội bộ. Không có số liệu chi phí Modal
  thực tế trong báo cáo.

## Kết quả từng án

| Án | Trạng thái | Brief / AU cuối | Nguồn đã cấp | Lượt rà nguồn | Nhận xét |
|---|---|---:|---:|---:|---|
| `013948` | `completed / nonempty` | 0 / 5 | ~99% ký tự; 0 cửa sổ chưa đọc | 15 | Mọi excerpt và vị trí khớp nguồn; không có lỗi giao thức. |
| `099980` | `completed / empty_output` | 0 / 0 | ~43% ký tự; 8 cửa sổ chưa đọc | 0 | Các bản đánh giá nguồn nêu nhiều cơ hội AU cụ thể nhưng model không tạo anchor. Cần xem là omission, không coi rỗng là chất lượng đạt. |
| `045155` | `incomplete` | 3 AU active là bản nháp | ~98% ký tự; 0 cửa sổ chưa đọc | 8 | Treatment của `045155:aus:002` là `applies`, nhưng evidence chỉ có authority và không có court response; host bác và dừng batch. |
| `011904`, `013009` | Chưa chạy | — | — | — | Circuit breaker dừng sau lỗi ở `045155`. |

Đánh giá sơ bộ theo nguồn của `013948` (agent review, chưa phải human gold):
`013948:aus:004` chọn câu liệt kê câu hỏi tranh chấp làm nội dung chính, phù
hợp `brief/issues` hơn AU; `013948:aus:002` và `013948:aus:003` có nguồn và
nội dung gần trùng. Attribution của đoạn trích quy định trong
`013948:aus:002` cần kiểm tra riêng. Không dùng số lượng 5 AU làm bằng chứng
chất lượng.

`099980` có lập luận về Rule 303, section 69 PSEA, chuẩn chứng minh và giới
hạn quyền của Commission trong nguồn. Các `batch_assessment` đã gọi tên các
vùng này nhưng cả reader và lượt sửa lựa chọn đều trả `new_items=[]`. Đây là
minh chứng rằng tách xét nguồn khỏi điều hướng chưa đủ buộc model chuyển cơ
hội được nêu thành anchor có căn cứ. Không tạo AU tự động từ lời đánh giá đó.

`045155` có lỗi cấu trúc/quan hệ evidence ở treatment. Response chọn
`applies` cho `045155:aus:002` với `P0052` là authority và các nguồn còn lại
đều `none`; thiếu court response. Không tự đổi thành `unknown` hoặc phát lại
request trong cùng experiment.

Báo cáo chi tiết: `outputs/pilot_v13_extract_before_navigate_local_scan/report.json`.
Bộ đối chiếu KOS: `outputs/pilot_v13_extract_before_navigate_local_scan/comparison/review_bundle.json`.
Bộ đối chiếu chứa cả bản nháp chưa hoàn tất của `045155`, nên phải đọc cùng
trạng thái thực thi; KOS không phải gold.

## Cổng tiếp theo

Đợt này chưa đạt cổng năm án: một kết quả rỗng có omission rõ, một án dừng
trước finalizer và hai án chưa chạy. Giữ artifact hiện có để sửa chính sách
tạo anchor từ nguồn đã xét và hướng dẫn treatment có đủ court response, rồi
đánh giá lại bằng experiment mới. Chưa mở tập 20 án hoặc retrieval.
