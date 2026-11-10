# Kiểm thử độc lập M1 Revision 2 — 05/11/2026

Bundle được kiểm: `pipeline_v2/artifacts/m1_20261105_v2/`.

## Lệnh và kết quả

- `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v` — **31/31 PASS**, gồm 6 kiểm thử M0 và 25 kiểm thử M1; 2,309 giây local.
- `.venv/Scripts/python.exe pipeline_v2/reviews/m1_revision2_validation/scripts/scan_marker_coverage.py --bundle pipeline_v2/artifacts/m1_20261105_v2` — **PASS**, quét độc lập raw bytes của 7.708 án, không gọi parser M1; khoảng 13,8 giây wall time.
- `.venv/Scripts/python.exe -m pipeline_v2.m1 validate --repo-root . --bundle pipeline_v2/artifacts/m1_20261105_v2` — **PASS**, 7.708 nguồn; 153,591 giây local.
- `.venv/Scripts/python.exe -m py_compile pipeline_v2/reviews/m1_revision2_validation/scripts/scan_marker_coverage.py` — **PASS**.

Trong lần chạy targeted đầu tiên, một assertion còn dùng tên classification của bundle v1 nên thất bại. Assertion đã được cập nhật theo contract R2; targeted suite sau đó đạt 25/25 và full suite đạt 31/31. Không có lỗi production được phát hiện từ lần assertion đó.

## Kiểm độc lập raw marker

Raw-byte scanner không import `parse_source` hay hàm kiểm coverage của production. Nó so vị trí marker với M0 hash và units/citation observations đã lưu; kiểm tra marker được ánh xạ đúng một lần, nằm trong unit riêng, role thuộc enum, evidence refs không rỗng, relation trỏ đúng unit khi attribution ID có giá trị, và paragraph không chứa marker tiếp theo.

- 356.999 marker đầu dòng: 356.973 paragraph units + 26 citation observations có reporter evidence.
- Kết quả: 0 marker thiếu/trùng, 0 paragraph nuốt marker sau, 0 lỗi tham chiếu trong phép quét.
- 1.237 relation/paragraph được gắn `quoted`; 355.736 giữ `unknown`; không có `current_case` được khẳng định ở corpus bundle này.
- 7.708 source bytes khớp hash và độ dài M0.

## Phạm vi và giới hạn

Regression tests bao gồm gap/repeat/backwards marker, `[1]` trong quotation, bản tiếng Pháp bắt đầu `[2]`, marker không có khoảng trắng sau `]`, citation `[2012] FC 9` so với marker `[2012]` đứng riêng, generic `following:` không đủ để tạo quotation, first-person court voice không đủ để chuyển ownership, các heading uppercase và 8 fixture đã exposed.

PASS chứng minh tính toàn vẹn, khả năng giữ riêng marker quan sát được và tính tái lập bundle. Nó không chứng minh phân loại `quoted` đúng về ngữ nghĩa trên toàn corpus, không xác định nguồn án trong quotation, và không đo AU/retrieval quality. Role hiện dùng thận trọng: explicit local quotation evidence có thể thành `quoted`; các trường hợp còn lại chủ yếu là `unknown`. Ownership thủ công toàn corpus chưa được review.
