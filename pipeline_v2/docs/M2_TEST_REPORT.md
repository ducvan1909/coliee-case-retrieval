# Kiểm thử độc lập M2 Navigation — 05/11/2026

## Phạm vi

Kiểm tra M2 navigation, exact previews, anchors, source-order neighbor mapping và khả năng mở parent/context. Phần embedding/tokenizer chưa được chọn nên token counts, token-validated chunks, dense và agent payload budget phải giữ `not_ready`. Không chạy inference, không xây index và không chạy M3/M4.

Bundle đã kiểm: `pipeline_v2/artifacts/m2_navigation_20261105_v1/`.

## Kết quả

- `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v` — **48/48 PASS**, gồm M0 6, M1 25, M2 core/API 13 và M2 bundle/store 4; 2.921 giây.
- `.venv/Scripts/python.exe -m py_compile pipeline_v2/reviews/m2_navigation_validation/scripts/audit_bundle.py pipeline_v2/tests/test_m2_navigation_core.py pipeline_v2/tests/test_m2_navigation_store.py` — **PASS**.
- `.venv/Scripts/python.exe -m pipeline_v2.m2 validate --bundle pipeline_v2/artifacts/m2_navigation_20261105_v1` — **PASS**, 7,708 nguồn; `local_elapsed_seconds=353.348367`.
- `.venv/Scripts/python.exe pipeline_v2/reviews/m2_navigation_validation/scripts/audit_bundle.py --m2-bundle pipeline_v2/artifacts/m2_navigation_20261105_v1` — **PASS**, kiểm tra độc lập raw/M1 trên toàn corpus.

Build receipt: `pipeline_v2/artifacts/m2_navigation_20261105_v1.build-receipt.json`; build exit 0, thời gian local 296.350545 giây. Tester không chạy build trùng.

## Số lượng được kiểm độc lập

- 7,708 bản án; 382,343 content units (356,973 paragraph; 25,370 unnumbered).
- Toàn bộ 48,990 heading còn trong map và span/text/hash khớp raw.
- 481,926 preview khớp đúng lát cắt UTF-8 của nguồn, tối đa 240 Unicode codepoints mỗi preview.
- 216,946 anchor: 215,688 placeholder và 1,258 quote-cue fragments; 1,237 source quote cues khớp chính xác nguồn M1, gồm full span, hash, unit refs và fragment giao với từng content unit.
- 698,530 liên kết paragraph trước/sau được đối chiếu lại theo thứ tự M1; không dựa vào số marker.
- 355,736 paragraph `unknown` vẫn có trong map; 55 content unit không có preview vẫn có lý do và không bị loại.
- Token count còn null; token chunks, dense, agent payload budget vẫn `not_ready`.

## Các lỗi trong vòng kiểm thử và xử lý

Lệnh targeted đầu tiên `.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m2_navigation_core -v` trả **2 FAIL, 1 ERROR**. Một lỗi production đã xác nhận: preview opening chưa bỏ marker/placeholder-only line trước khi chọn phần đọc, gồm trường hợp BOM. Implementer đã sửa và test BOM + CRLF + Unicode, placeholder-only line đều PASS trên bản cuối. Hai assertion về `unnumbered` đặt văn bản thường giữa hai marker vào cùng paragraph; M1 đúng khi giữ phần đó trong paragraph cha, nên fixture được chuyển thành unnumbered unit đứng trước marker. Đây là lỗi giả định của fixture, không phải production bug. Bản cuối targeted core/API đạt 13/13.

Các test M2 bổ sung kiểm việc mở context dùng parent đầy đủ và hàng xóm theo source order; giữ cả anchor khi preview chỉ thấy một phần; dùng slot preview thứ hai khi window gộp vượt cap; phân trang không làm mất row/anchor; write-once và deterministic; từ chối artifact bị sửa rồi reseal, source drift và profile drift.

## Giới hạn diễn giải

PASS chứng minh protocol, coverage, provenance, pagination và ánh xạ raw/context. Nó **không** chứng minh `unknown/quoted` đúng ngữ nghĩa, anchor cue thật sự là citation, preview hữu ích cho lập luận pháp lý, hay hệ thống đạt chất lượng retrieval. Tiếng Pháp được giữ nguyên như nguồn; chưa có xử lý/ngữ nghĩa riêng. Chunking theo token vẫn chưa thể đánh giá khi tokenizer/model chưa chọn.
