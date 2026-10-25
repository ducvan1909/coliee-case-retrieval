# Split policy V1

## Vai trò

- `calibration` (5 án): tái hiện lỗi đã biết và sửa contract. Có thể xem lặp lại. Không dùng để tuyên bố chất lượng tổng quát.
- `development` (20 án): phát triển rule/parser/prompt ở các kế hoạch sau. Không phải holdout.
- `holdout` (40 án): đánh giá khóa. Không dùng để thay rule, prompt, threshold, label mapping hoặc chọn model.
- Phenomenon supplement nếu cần phải được báo riêng, không thay case holdout sau khi đã xem kết quả và không nhập vào metric chính nếu không được khóa trước.

## Quy tắc tái lập pilot

Với từng corpus split `train` và `test`:

1. Chỉ lấy file `*.txt`; `case_id` là stem sáu chữ số.
2. Xếp tăng dần theo `(byte_length, case_id)`.
3. Với `n` file, dải thứ `i` là lát `[i*n//3 : (i+1)*n//3]`, lần lượt `short`, `medium`, `long`.
4. Trong mỗi dải, xếp theo SHA-256 của chuỗi UTF-8 `lynx-round2:{split}:{band}:{case_id}` và lấy 10 phần tử đầu.
5. Nối ba dải theo thứ tự short–medium–long. Phần tử có chỉ số toàn cục chia hết cho 3 vào development; phần còn lại vào holdout.

Quy tắc dùng metadata source và hash salt, không đọc label.

## Leakage và trùng case

- Mọi case ID chỉ được xuất hiện trong một vai trò khóa.
- Calibration không được trùng development/holdout; development không được trùng holdout.
- Trong input KOS đã chọn, hai file khác path nhưng cùng SHA-256 làm fail gate; thay đổi/thêm/bớt file làm tree hash lệch manifest.
- Gate tái dựng đủ 60 pilot case từ raw corpus metadata theo policy đã khóa, đối chiếu assignment SHA-256, format/existence của case ID và duplicate source hash trên 5 calibration + 60 pilot case.
- Việc tạo registry pilot ban đầu không được đọc label, gold noticed-case, KOS, output V13–V15 hoặc model output.
- Validator hiện tại đọc file KOS để hash nhưng không dùng `gold_noticed`, `gold_for_queries`, AU/NN/CiteSite hiện có làm nhãn đánh giá. KOS calibration không phải holdout độc lập.
- Annotation/gold của holdout chỉ được mở ở pha đánh giá đã khóa; kết quả holdout không được dùng để chỉnh hệ thống rồi báo lại trên cùng holdout.
- Metadata về độ dài/split được phép dùng vì là biến phân tầng đã công bố trước.

## Invalidation

Đổi file KOS đã chọn, inventory/tree-hash contract, thuật toán chia dải, salt, số lượng chọn hoặc assignment đều tạo version manifest mới. Không sửa manifest V1 tại chỗ chỉ để làm cho check pass.

