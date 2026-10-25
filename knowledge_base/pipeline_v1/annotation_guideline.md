# Annotation guideline tối thiểu V1

## Nguyên tắc

1. Raw source sau giải mã `utf-8-sig`, SHA-256 raw bytes và offset codepoint là nguồn sự thật.
2. Mọi span là nửa mở `[start_char, end_char)` và phải khớp nguyên văn source. Không normalize whitespace trong evidence.
3. `SourceBlock` là đơn vị địa chỉ/cấu trúc, không mặc nhiên là AU. Block leaf phải có thứ tự, không chồng lấn; coverage đầy đủ sẽ được đánh giá ở bước parser sau.
4. `AuthorityUnit` chỉ được accepted khi proposition và evidence có thể truy về source; candidate hoặc review cũ không tự thành gold.
5. Attribution phải gắn với từng evidence span. Không suy ra `current_court` chỉ vì văn bản nằm trong bản án.
6. Condition, exception và limit là span riêng. Không nhập chúng vào proposition theo cách làm mất địa chỉ nguồn.
7. Khi thiếu context cụ thể, tạo `ContextObligation`; không âm thầm accepted AU hoặc no-AU.
8. `unknown`, `unresolved` và `needs_adjudication` là kết quả hợp lệ. Không ép nhãn để hoàn tất schema.

## SourceBlock

Gán một `block_type` mô tả hình thức nguồn: heading, paragraph, list item, quotation, footnote, editorial hoặc unknown. Ghi `annotation_status=adjudicated` chỉ sau review; detector/parser output phải là `candidate` hoặc `needs_adjudication`.

Các lỗi cần ghi riêng: false heading, bracket year/citation bị nhầm paragraph marker, quote/list continuation, protected citation/entity split, wrapped line, OCR noise và block quá dài.

## AuthorityUnit

- `proposition_span` là mệnh đề pháp lý chính; `evidence_spans` chứa mọi witness cần thiết.
- `kind` có thể là rule, test, interpretation, application, standard_of_review, procedural hoặc other/unknown.
- Attribution dùng role như `proposition`, `authority`, `current_court_response`, `condition`, `exception`, `limit` và speaker quan sát được.
- Với treatment của cited authority, cần cả authority witness và current-court response witness; nếu thiếu, để unknown/unresolved và tạo obligation.
- AU chạy qua nhiều SourceBlock được phép nếu spans vẫn exact và quan hệ được adjudicate.
- Duplicates/fragments phải được ghi bằng `duplicate_of` hoặc trạng thái review, không xóa evidence.

## ContextObligation

Tạo obligation khi thiếu một loại context xác định: attribution, condition, exception, limit, current-court response hoặc cross-block continuation. Phải ghi target, hướng/span cần đọc, lý do, producer/run và status. `budget_exhausted` khác `unresolved`; cả hai không được coi là satisfied.

## Mức hoàn thành của Kế hoạch 01

Chỉ cần schema biểu diễn được các nhãn trên và danh mục hard case sẵn sàng cho annotation. Chưa yêu cầu annotate đầy đủ năm case, đo F1 hay quyết định parser/model.

