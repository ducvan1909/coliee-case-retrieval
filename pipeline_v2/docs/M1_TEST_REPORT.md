# Kiểm thử nghiệm thu M1 — 05/11/2026

Bundle được kiểm: `../artifacts/m1_20261105_v1/`. Tester chỉ sửa các file test trong `tests/` và báo cáo này; không sửa production code hoặc dữ liệu nguồn.

## Lệnh và kết quả

- `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -v` — **21/21 PASS**, gồm 6 M0 regression và 15 M1 tests; 1,462 giây local.
- `.venv/Scripts/python.exe -m pipeline_v2.m1 validate --repo-root . --bundle pipeline_v2/artifacts/m1_20261105_v1` — **PASS**, 7.708 sources; 105,161 giây local.

## Phạm vi kiểm tra

- UTF-8 boundary mapping với BOM, CRLF, dấu tiếng Pháp và emoji; round-trip mọi character boundary; từ chối byte offset giữa codepoint và UTF-8 lỗi.
- Structural units tạo partition liên tục phủ đúng toàn bộ raw bytes; `[2012]` được giữ là citation-year observation; quote marker được ghi sidecar với parent và uncertainty, không khẳng định route.
- Metadata raw spans khớp chính xác giá trị; candidate metadata trùng lặp được giữ như nhiều quan sát chưa xác minh danh tính án. Thiếu metadata giữ `unknown`.
- Ba fixture chẩn đoán đã exposed: `061295` quote markers và attribution cue; `067620` paragraph `[1]` EN/FR có vùng riêng; `062436` mở được heading `The Respondent`, không gán speaker/holding.
- Reader trả nguyên văn từ nguồn có hash, unit và byte/character offsets; từ chối offset lỗi, unit lạ, neighbor count âm và source drift.
- M1 build tái lập, write-once, validate; reader phát hiện source record, registry và manifest bị sửa rồi tự reseal.
- M0 regression vẫn PASS sau khi thêm M1.

## Giới hạn

Đây là kiểm protocol, offset và ba cấu trúc đã biết; không phải kiểm thủ công đại diện trên 7.708 bản án, không chứng minh phân đoạn ngữ nghĩa đúng, và không đánh giá noticed-case labels. 72.487 quote-marker sidecars là **ứng viên quan sát được**, không phải 72.487 quan hệ citation đã xác minh. Báo cáo corpus cho thấy 28.046 vùng unnumbered (`structure_unknown`), cùng nhiều uncertainty khác; chúng được giữ đọc được, không bị xem như paragraph đã phân loại. Không có inference, model/API, index M2 hoặc test labels.
