# Checkpoint CM0–CM1 — 14/11/2026

**Cập nhật 15/11/2026:** AG đã review v2, báo 19/19 PASS, 0 finding chặn.
Main đối chiếu report/code/source hashes đạt, chốt engineering offline theo
`CM1_V2_ACCEPTANCE.md`. Các đoạn “chờ review” phía dưới là checkpoint lịch sử.
Chưa triển khai CM2 hoặc chạy inference.

## Cập nhật sau AG review: sửa CM1 rules v2

Người dùng giao ghi bảng điều hướng vào kế hoạch và sửa CM1. Đã thực hiện trong
`core.py`/tests/README; không mở CM2 hoặc đổi production. Phần báo cáo v1 bên dưới
giữ làm checkpoint trước sửa; số token/source binding mới lấy từ evidence v2 này.

- `Session.allowed_actions` là nguồn quy tắc chung để sinh schema và host kiểm
  dispatch. Read enum chỉ có B thuộc need hiện tại; khi reading chỉ cho B hiện
  tại, không cấp đổi need. Safe stages cho chuyển sang need khác, không có noop.
- Card có `action_available`, `read_allowed`, `belongs_to_current_need`; model
  không phải đoán từ schema ẩn để phân biệt browse-only với hành động hợp lệ.
- Prompt tools có description/when/result, object schema giữ required/bounds/
  additionalProperties; choices_from chỉ rõ card/control được phép chọn.
- Cursor giữ back_history ở host manifest, next theo số card thực; previous về
  đúng trang đã xem kể cả token-shrink và resume, không lùi cố định 5 mục.
- `needs_context_delivered` chỉ current need đã hiển thị; `need_list_items_delivered`
  chỉ cards trên trang needs đã giao. Success receipt mới cập nhật; unknown không
  cập nhật và chặn bước tiếp. Cả hai không chứng minh hiểu hoặc giải quyết need.

Kiểm cuối: **19/19 tests PASS, 0 skip**, 1,709 giây. Reviewer độc lập kiểm thêm
pool nhiều needs, pure policy/schema ở các stages, reading→missing→switch,
next/previous khi trang co sau resume, unknown và mô tả/flags tool: không còn lỗi
chặn được xác nhận trong phạm vi sửa. Không có controller/embedding/retrieval mới.

Evidence cuối:

- `cache/cm1-rules-replay-20261114-v2/report.json`: result view **1.272 token**,
  supplied raw A/B view **2.198 token**, 3 candidates, raw-preserved/resume-equal,
  source hashes không đổi, code bindings khớp bản cuối.
- `cache/cm1-rules-stress-20261114-v2/report.json`: 3/50 duyệt đủ; 500/10.000 chỉ
  first-page như phạm vi trước. Peak tương ứng 1.074/1.261/1.244/1.229 token.

Các view này vẫn chỉ có context commands, không tương đương prompt đầy đủ M6.
Callbacks thực cho search/read/no-hit/error/assessment và evidence lifecycle chưa
nối; các nhánh đó được ghi trong kế hoạch cho CM2–CM3, không giả lập thành tool
đã triển khai. VERSION/scope/code hash đổi nên cần namespace mới, không resume
session v1; không sửa bất kỳ report/run cũ nào. AG có thể kiểm hồi quy v2 theo README.

## Checkpoint v1 trước sửa

Trạng thái: có prototype offline và evidence local, **chờ AG review cuối CM1**.
Không nghiệm thu CM2/CM3, chưa tích hợp vào live runner và không đo recall/model
behavior. Không đổi production; hai diff `evidence.py`/`modal_qwen.py` có trước task.

## Kết quả CM0

Đếm bằng tokenizer/chat template pin và instructions của bộ thử nghiệm hiện tại:

| Mẫu đã lưu | Tổng input | Raw bytes | Removal delta m6 | Removal delta tools |
|---|---:|---:|---:|---:|
| Payload sau search | 7.399 | 0 | 5.834 | 692 |
| Payload sau đọc B giả lập | 8.285 | 1.347 | 5.168 | 1.384 |

Input tối thiểu instructions/template đo được 346 token. Removal deltas là đo bỏ
từng field, không cộng được. Registry chiếm nhiều hơn raw trên hai mẫu này;
không suy ra mọi run đều như vậy. Giữ hard cap 8.500/512, soft target thử 7.900.

## Kết quả CM1

`core.py` có canonical Snapshot adapter, bounded views, separate durable Session,
phân trang needs/pool/results, focus state, schema+canonical binding manifests,
success/unknown/error receipts offline, validate commands và dispatch intents.
Full pool giữ ở host; first-seen archive khác native operation rank. Lead để đọc
được resolve theo need, tránh một case dùng nhầm lead của need khác.

Manifest/view write-once trước admission; schema/hash/config/source revision,
counter binding và core code hash được bind. Có single-writer guard, kiểm snapshot
mutations, stale response/cursor, duplicate commands, tampered artifacts. Receipt
success mới tăng delivered-view counts; unknown chặn bước tiếp. Cảnh báo lặp
không tự chuyển focus hoặc thay quyết định model/AG.

Replay cuối: `cache/cm01-replay-20261114-final/report.json`:

- Adapter lấy toàn bộ 3 candidates và 1 need chưa assessment từ ledger thực.
- View kết quả: **1.077 token**, ba candidates giữ rank gốc.
- View nhận nguyên raw A/B đã cấp: **2.079 token**, raw/refs/pending giữ nguyên.
- Dispatch intent đọc `012856.txt` bind canonical need/lead; không thực thi tool.
- Reopen session cho cùng focus; source artifacts giữ hash; code binding khớp bản cuối.
- Local replay 10,506 giây; 0 controller/embedding/retrieval requests mới.

**Các token mới không tương đương một lượt M6 đầy đủ:** view hiện chỉ có context
commands, không chứa toàn bộ catalog/schema tìm/đọc/assessment hiện hành. CM1
chứng minh projection và dispatch binding, không chứng minh mức giảm token cho
runner có cùng khả năng. Tích hợp map và source/assessment tool thật thuộc CM2/CM3.

Stress cuối: `cache/cm01-stress-20261114-final/report.json`, 19,042 giây:

| Canonical candidates | Số trang đã render | Phạm vi | Peak input |
|---|---:|---|---:|
| 3 | 1 | Duyệt đủ | 876 |
| 50 | 10 | Duyệt đủ, không mất/lặp | 1.026 |
| 500 | 1 | Chỉ first-page stress | 1.002 |
| 10.000 | 1 | Chỉ first-page stress | 1.014 |

Không claim đã duyệt hết 500/10.000 hoặc host CPU/RAM bounded. Chưa nối cập nhật
snapshot động vào một session; revision khác phải dùng namespace mới. Chưa nối
source/tool result callbacks để cập nhật assessment/no-hit/failed stages; record
missing evidence là đường kết thúc bước offline hiện có, không tự tạo assessment.

## Kiểm thử và review

Lệnh: `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v1/tests -p 'test_*.py' -q`.
**13 tests PASS, 0 skip**, 32,606 giây trên lượt cuối. Kiểm traverse, page shrink,
bound pools, need status, stale refs/cursors/config/counter, collisions/mutations,
single writer, repeat warnings, raw-preserve-or-unfit, focus và resume.

Reviewer độc lập ban đầu phát hiện handle current-need trùng và SQLite connection
lifetime; đã sửa idempotent same binding và close connections. Reviewer và
implementer sau đó cùng bị giới hạn sử dụng, không review được bản cuối. Main
hoàn thiện code/tests/CLI và kiểm local; **không gọi kiểm Main là review độc lập**.
AG cần đối chiếu theo `AG_CHECK.md` trước khi mở CM2.

Output v1/v2 là checkpoint trước sửa cuối, được giữ nguyên. Chỉ dùng `-final`
và bindings trong report để đối chiếu bản hiện hành. Không chỉnh run/evidence cũ.
