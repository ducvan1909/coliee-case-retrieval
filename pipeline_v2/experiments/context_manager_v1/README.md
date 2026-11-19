# CM0–CM1: context manager offline

Contract hiện hành: **`cm01-offline-v2`**; code/config/counter binding đổi nên các
session trước cần giữ nguyên làm evidence và tạo namespace mới cho bản v2.
Triển khai thử nghiệm riêng. Không import vào production, không có lệnh inference
hay deploy. Xóa thư mục không đổi đường chạy thật. Đọc thiết kế ở
`../uncapped_probe/CONTEXT_MANAGEMENT_DESIGN.md`. Dừng ở checkpoint AG cuối CM1.

## Phạm vi

- CM0 đo exact prompt tokens của hai payload đã lưu bằng tokenizer/chat template
  pin, cùng removal deltas theo field (không cộng được).
- CM1 `Snapshot.from_events` giữ exact per-search needs, operation ranks, toàn
  unique pool và trạng thái need–candidate. Không đọc labels, không gộp needs ngữ nghĩa.
- `Session.compile` tạo view tối đa 5 cards/token cap, `pool` để tra kho first-seen,
  `candidates` theo need đang focus, `results` theo operation mới nhất của focus,
  `needs` để chọn focus. `query`/`assessment` mới là view context, không thực thi
  source reader hoặc assessment; map navigation đầy đủ chưa nối ở milestone này.
- Scope/revision/config/tokenizer/code-bound handles và cursor, immutable view/
  manifest, schema enum đầy đủ trong manifest, separate append-only SQLite journal.
- `receipt` là acknowledgment của offline simulator, không phải provider receipt.
  Unknown chặn bước mới; offered không được tính đã giao trước success receipt.
- `command` validate đúng manifest mới nhất đã thành công, trả dispatch intent
  `read_case_passages` với canonical need/candidate/lead đúng need. **Không execute.**
  Khi đang reading, chuyển focus cần ghi missing evidence trước; chưa có callback
  kết quả assessment/tool hay merge snapshot động — thuộc tích hợp CM2/CM3.
- `Session.allowed_actions(handles, focus)` là policy dùng chung cho schema và
  host dispatch. Card ngoài need hiện tại trong kho tổng chỉ để xem, không được
  cấp enum đọc. Khi đang đọc B, chỉ cho đọc tiếp B đó; đổi B/need chỉ được cấp
  sau ranh giới ready/assessed/missing_evidence/error/no_hit. Không cấp action
  chọn lại cùng need để tránh vô tình xóa trạng thái reading. Đang reading có
  action ghi rõ evidence thiếu; callback tool/assessment thật vẫn để CM2/CM3.
- Điều hướng trang không đổi focus, vẫn được dùng khi reading. Cursor giữ
  `back_history` exact của đường đã đi, bind mode/focus/revision trong scope;
  Previous quay đúng vị trí trang đã xem trước đó cả khi token cap làm mỗi
  trang có số mục khác nhau. Next tăng theo số card thực sự được trả.
- View tách `needs_context_delivered` (need đã có ở phần focus/context) và
  `need_list_items_delivered` (mục thực sự được giao qua trang needs).
  Success receipt offline mới tăng các tập này; admission/unknown/error không
  tăng. `seen_needs`/`shown_need_ids` chỉ là union tương thích nội bộ, không phải
  chứng cứ đã duyệt danh sách needs. Không suy đã đọc raw từ candidate cards.
- Mỗi tool context có mô tả, điều kiện dùng, kết quả và `choices_from` trong
  prompt, cùng types/required/bounds. Decoder/host giữ full enum trong manifest.
  Nếu cần đổi need khi đang reading, ghi missing evidence rồi mở needs view và
  chọn need khác; không tự tạo assessment để vượt ranh giới.
- Raw caller cấp giữ nguyên hoặc unfit; CLI replay kiểm thêm raw trực tiếp với
  corpus/hash. Public Session kiểm integrity và nguồn đã bind, không thay source
  reader/validator production. Không tự pin/park/clip/reload evidence mới.
- Cảnh báo lặp cùng view/focus/raw trên snapshot không đổi; không tự luân phiên
  needs hoặc dừng thay model/AG. Đây là cảnh báo bảo thủ, chưa đo hiệu quả hành vi.

## Lệnh kiểm local

Chạy ở repo root, dùng `.venv/Scripts/python.exe`. Mỗi output phải là thư mục mới.

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v1/tests -p 'test_*.py' -q

$cmMeasure = 'cache/cm0-ag-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v1.cli measure --output-dir $cmMeasure

$cmReplay = 'cache/cm1-ag-replay-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v1.cli replay --output-dir $cmReplay

$cmStress = 'cache/cm1-ag-stress-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v1.cli stress --output-dir $cmStress
```

`measure`/`replay` mặc định đọc run `cache/m6-uncapped-021095-20261114-200422096`
và payloads ở `cache/ag-payload-check-20261114-215317655`. Có thể chỉ định
`--source-run` và `--payload-dir`, nhưng phải đúng nguồn/query có cùng bindings.
Không có fallback dữ liệu giả khi thiếu artifact: lỗi phải được giải quyết hoặc
báo thiếu. Các tests unit không cần các run này; CLI thật cần tokenizer và raw corpus.

Report ghi exact counter binding, code hashes, chi phí local, source hashes và
0 controller/embedding/retrieval mới. Không ghi credentials/env. Kiểm exit code
trước khi đọc report; giữ thư mục lỗi, không sửa lịch sử để có PASS.

## Giới hạn so sánh và bước tiếp theo

CM1 views **chưa có đầy đủ source/assessment tool catalog của runner M6**. Token
của chúng không được coi là mức giảm trên một lượt inference tương đương; chỉ
chứng minh projection nhỏ và raw-preserving. Cần CM2/CM3 để tích hợp tool thật,
pin/park evidence và đo final prompt có cùng khả năng làm việc.

Stress giữ 3/50/500/10.000 canonical candidates; runtime duyệt hết 3 và 50, còn
500/10.000 mới kiểm first page. Chưa benchmark full traversal lớn hoặc chi phí
host theo lịch sử dài. Replay Session hiện duyệt journal/manifests nên không có
cam kết CPU/RAM bounded. Prompt nhỏ không chứng minh context hữu ích hoặc hết bias.

Đọc `AG_CHECK.md` và `REPORT.md` để review. Không chạy CM2/live trước checkpoint.
