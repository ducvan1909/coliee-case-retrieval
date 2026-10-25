# Phiếu phân xử calibration V4

Tài liệu này khóa cách đánh giá trước khi chạy `pilot_v4`. Nó không tự biến đánh
giá V3 thành gold và không được đưa vào prompt reader/verifier.

## Đơn vị đánh giá

Mỗi item phải được kiểm tra theo từng source ref và từng thành phần bắt buộc:

- selection: đoạn được chọn có đủ và không gây hiểu sai hay không;
- brief kind hoặc AU relation/treatment;
- attribution của từng source ref;
- omission: có brief/AU rõ ràng nào trong phần nguồn đã đọc nhưng bị bỏ sót không.

Mỗi kết luận dùng một trong ba mức: `definite_error`,
`defensible_alternative`, `insufficient_context`. Ghi stable source ID, tọa độ và
lý do. Không dùng “nằm trong bản án” làm căn cứ current_court.

## Quy ước attribution

- Chủ thể là nguồn của mệnh đề được lưu, không phải tác giả file.
- Lập luận/khẳng định/yêu cầu quy rõ cho đương sự là `party`.
- Tòa thuật một sự kiện tố tụng như dữ kiện có thể là `current_court`.
- Luật và án được trích là `cited_authority`; việc trích không chứng minh applies.
- Headnote chỉ là `editorial` khi có căn cứ cấu trúc/nội dung.
- Dùng `mixed` khi nhiều chủ thể thực sự không tách được bằng địa chỉ hiện có.
- Dùng `unknown` khi nguồn không đủ hoặc enum chưa biểu diễn rõ chủ thể nhúng.

## Quy ước brief và AU

- Quy phạm không phải facts; finding không tự là issues; final order không phải
  posture của chính quyết định hiện tại.
- Không ép finding pháp lý vào brief. Xét AU hoặc không lưu.
- AU gồm nguyên tắc, áp dụng, điều kiện/ngoại lệ, đánh giá chứng cứ hoặc lập luận
  thủ tục. AU không bắt buộc citation và không có quota.

## Bảng cần điền

Đánh giá toàn bộ 29 item V3, không chỉ tám item bị nghi ngờ. Mỗi dòng có:

| Trường | Nội dung |
|---|---|
| case_id / item_id / revision | Định danh kết quả V3 |
| source_refs | Stable ID và tọa độ được kiểm tra |
| component | selection, kind, attribution của một ref, relation hoặc treatment |
| proposed | Nhãn V3 |
| reviewer_1 / reviewer_2 | Kết luận độc lập nếu có hai người |
| adjudication | Kết luận cuối hoặc `pending` |
| evidence_source_ids | Căn cứ đã xem đầy đủ |
| reason | Lý do cụ thể, không dùng kết luận chung |

Nếu chỉ agent đánh giá, ghi `agent_review`; không gọi là human gold. Bất đồng phải
được giữ lại. Tám nhận định trong `outputs/pilot_v3/MANUAL_REVIEW.md` là ứng viên
hồi quy, không phải đáp án mặc định.

## Cơ hội AU

Lập danh sách riêng các đoạn trong năm án thực sự có thể tạo AU. Mỗi cơ hội ghi
source refs bắt buộc, loại nội dung, attribution dự kiến và treatment có/không áp
dụng. Danh sách này dùng để đo bỏ sót trong calibration, không được đưa vào prompt
end-to-end. Nếu không xác nhận được cơ hội AU, báo giới hạn mẫu thay vì tạo ví dụ
giả hoặc ép reader tạo AU.
