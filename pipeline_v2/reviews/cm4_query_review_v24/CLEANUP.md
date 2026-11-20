# CM4 cleanup: catalog và hướng dẫn hiện hành

Ngày 19/11/2026. Engine `cm4-query-review-v25`, source gate `cm4-source-gate-v4`, live CLI vẫn `cm4-live-v2`.

## Đã bỏ khỏi CM4 hiện hành

- Gate aliases `has_source_signal` / `no_source_signal`: không nằm trong schema và host từ chối nếu gửi trực tiếp. Chỉ còn `search_needed`, `no_search_needed`, `need_more_context`.
- Tool citation, chọn/hoãn/resume/đóng anchor draft và reload chung từ luồng cũ: không được công bố trong catalog CM4. Catalog cuối lọc cả decoder schema, model tools và các gợi ý navigation/recovery. Không tạo tool đóng draft trong gate-enabled runtime.
- Chỉ dẫn phải ghi thiếu evidence trước khi đổi candidate: thay bằng quyền so sánh candidate trong active query. Chỉ dẫn duplicate đổi need của luồng cũ không áp cho CM4.
- Lịch sử v1–v24, lệnh run namespace cũ và bảng tool legacy không còn trộn trong `CM4.md`, `MODEL_CONTEXT_FLOW.md`, `README.md` hiện hành.

CM2/CM3 offline replay và các tests anchor riêng vẫn tồn tại để kiểm nguồn/khôi phục thí nghiệm; chúng không phải tool API hoặc prompt CM4 live. Không xóa shared evidence/anchor validators hoặc reports/sealed artifacts chỉ vì code từng dùng ở luồng cũ.

## Tài liệu

- Hiện hành: `experiments/context_manager_v2/CM4.md`, `MODEL_CONTEXT_FLOW.md`, `README.md` và `AG_CHECK.md` ở thư mục review này.
- Lưu trữ: `CM4_HISTORY.md`, `MODEL_CONTEXT_FLOW_HISTORY.md`, `OFFLINE_REPLAY.md`, `AG_CHECK_HISTORY.md`; hướng dẫn hiện hành dẫn rõ sang checklist mới, không dùng các bản lưu trữ cho live. `LIVE_*.md`, báo cáo và acceptance lịch sử được liệt kê riêng trong README, giữ nguyên kết quả kiểm ở revision đó.
- Root handoff/PROGRESS có checkpoint cleanup mới dẫn đến contract hiện hành; những đoạn lịch sử cũ không phải lệnh chạy tiếp.

## Kiểm tra

- Suite toàn bộ CM4 trên code cuối, gồm bốn tests catalog mới: **126 tests PASS**, **197.352s**, không skip. Lệnh: `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q`.

- Suite CM4 regression sau bỏ aliases: **122 tests PASS**, 215.100s, không skip.
- `test_current_catalog` + `test_query_review_acceptance` trên code cuối sau sửa recovery guidance: **14 tests PASS**, 20.389s. Bốn tests catalog là mới; mười acceptance tests trùng phạm vi suite regression, không cộng thành 136 tests độc lập.
- `git -c core.whitespace=cr-at-eol diff --check`: PASS.
- Liên kết trong bốn hướng dẫn hiện hành README/AG_CHECK/CM4/MODEL_CONTEXT_FLOW: PASS.
- Fresh prepare cuối: `cache/cm4-current-catalog-v25-final-20261119-212126026`, exit 0, ready **2.286 input tokens**, **213.659s**, **0 controller/embedding requests**. `plan.code_binding == live.binding()` sau cleanup: **True**, guard warn. Không inference/deploy.
- Prepare v25 trước đó cũng ready nhưng được thay bằng namespace final vì code đổi trong lúc kiểm; không chỉnh plan cũ để khớp. Các preflight v24 cũ không còn hợp lệ cho code hiện tại.

`test_current_catalog.py` thêm các kiểm tra: schema chỉ có ba decisions mới; host từ chối aliases cũ; tool catalog/recovery bỏ tên cũ; các view trước search/survey/review không công bố tool legacy hoặc route không được cấp.

## Chạy tiếp

Dùng lệnh trong `AG_CHECK.md` với namespace mới. Plan v24 đã prepare trước cleanup có binding cũ và không được chạy bằng code v25. Không dùng archived commands để resend admission unknown. Codex chỉ kiểm local; người dùng/AG chạy thật.
