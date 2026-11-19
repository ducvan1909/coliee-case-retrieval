# AG review checkpoint CM0–CM1

Phạm vi được giao: đo context và thử nghiệm view có giới hạn, phân trang pool/needs,
focus, cursor và dispatch intents offline. **Dừng trước CM2.** Không inference,
embedding, retrieval mới, deploy hoặc sửa production/run lịch sử.

Đọc thiết kế tại `../uncapped_probe/CONTEXT_MANAGEMENT_DESIGN.md`, cùng README và
REPORT của thư mục này. CM1 chưa tích hợp live và chưa thay evidence lifecycle:
không diễn giải một intent đã được validate thành nguồn đã fetch hoặc model đã đọc.

Sau review AG đầu: core v2 đã sửa enum đúng need/stage, exact previous và tách
delivery metrics. Regression gồm 19 tests; dùng namespace mới để kiểm bản v2.
Đặc biệt đối chiếu action_available/read_allowed trên card với decoder enum,
không cho lựa chọn hợp lệ theo schema nhưng bị chặn vì điều kiện stage đã biết.
Kiểm reading→missing→need khác, previous sau token-shrink/resume, và unknown
không tăng hai loại needs delivery. Evidence mới nằm ở phần cập nhật đầu REPORT.

## Review cơ chế

### Lệnh kiểm hồi quy v2

Chạy từ repo root bằng PowerShell. Đây chỉ là kiểm offline, không chạy model:

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v1/tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'CM1 v2 tests failed; keep logs and stop' }

$cm1Review = 'cache/cm1-v2-ag-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v1.cli replay --output-dir "$cm1Review-replay"
if ($LASTEXITCODE -ne 0) { throw 'CM1 v2 replay failed; keep output and stop' }
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v1.cli stress --output-dir "$cm1Review-stress"
if ($LASTEXITCODE -ne 0) { throw 'CM1 v2 stress failed; keep output and stop' }
Get-Content "$cm1Review-replay/report.json"
Get-Content "$cm1Review-stress/report.json"
```

Expected trên source v2 đã bàn giao: 19 tests PASS/0 skip; replay có 3 candidates,
raw_preserved/resume_equal/source_unchanged đều true; counters requests mới bằng
0. Main đo result view 1.272 token và supplied A/B view 2.198 token. Đối chiếu
code/counter bindings trước khi dùng các số này làm kỳ vọng, không sửa output
để khớp. Không cần chạy lại CM0 measure nếu counter/source bindings không đổi.

- Full pool/needs/canonical bindings nằm ngoài model view; mọi mục có đường mở
  lại. Giữ nguyên per-search need IDs, không tự gộp theo ngữ nghĩa hoặc A span.
- View kết quả mới giữ operation rank. First-seen chỉ là chỉ mục kho tổng;
  không cộng điểm giữa needs hoặc thêm reranker. Trạng thái assessment tính theo
  need–candidate, không lấy trạng thái tổng của case thay cho mọi need.
- Trang tối đa 5 cards và còn chịu token cap. Khi giảm số cards để vừa token,
  cursor tiến đúng số đã hiển thị. Duyệt hết không thiếu/lặp; previous/refresh
  không làm pool hay kết quả retrieval thay đổi.
- Cursor/handles bind run/query/source/config/revision/filter/focus phù hợp;
  reject foreign/stale/tampered refs. Cursor cũ không âm thầm trỏ sang dữ liệu mới.
- Model chọn hướng; host giữ focus qua một bước có ích và báo trạng thái/cảnh
  báo. Có lối thoát khi lỗi/no-hit/missing evidence; không ép round-robin cứng
  hoặc mắc kẹt chờ assessment bất khả thi. Request/action in-flight không bị ngắt.
- Manifest của từng view là immutable; response dùng binding của đúng view,
  không dịch bằng bảng mới nhất. Offered, response-delivered, raw-delivered và
  assessed là các trạng thái riêng. Unknown không ngầm thành đã xem/đã đọc.
- Raw caller cấp giữ đúng text/spans/hashes/refs; nếu không vừa thì unfit rõ
  ràng. Không thêm pin/park/reload lifecycle của CM2 hoặc làm yếu validator M4.
- Hard cap 8.500 input, output 512; tokenizer/chat template pin. Soft target
  7.900 là mục tiêu thử, không phải lý do cắt raw hoặc dừng nếu vẫn dưới hard cap.
  Token removal deltas không cộng được; exact total mới quyết định.

## Evidence cần trả

Lệnh chạy tests, `measure`, `replay`, `stress` nằm trong `README.md`. Dùng
namespace AG mới; các output Main đã có không được ghi đè. Bộ stress hiện chỉ
duyệt hết 3/50 án, first-page-only cho 500/10.000; review phải giữ giới hạn này.
Map đầy đủ/source tool dispatch và assessment execution chưa nối CM1; schema
ở đây chỉ cho context commands, không thay validator M4 hoặc gate tích hợp CM3.

1. Lệnh, stdout/stderr/exit code, số PASS/FAIL/skip trên source cuối; mọi skip có lý do.
2. CM0: số token của hai payload thực đã lưu, chi phí instructions/tools/view/raw,
   các nhận định về ngân sách và giới hạn phương pháp đo.
3. CM1: replay ledger thực, model view, canonical manifest, schema/bindings,
   dispatch intents giả lập và log focus/pages; exact token count từng view.
4. Stress pool 3/50/500/10.000, nhiều needs; view có giới hạn, đủ canonical pool,
   có kiểm traversal/cursor/refresh và raw-preserve-or-unfit.
5. Resume và tamper tests: revision/source/config/code drift, refs cũ, unknown
   receipts và không replay action trả phí. Không cần gửi request thật để kiểm.
6. Hash run nguồn trước/sau, source/code/profile bindings, latency local và
   counters controller/embedding/retrieval requests mới đều bằng 0.

AG không cần chạy lại phần đã có evidence phù hợp chỉ để tăng số test. Nếu có
lỗi chặn, giữ output namespace lỗi, báo command tái hiện và dừng; không chỉnh
seals/hashes hoặc bỏ guard để làm PASS. Các giới hạn của adapter offline phải
được báo riêng, không coi là đã nghiệm thu CM2/CM3, bias hành vi hay recall live.

## Điểm dừng

Điều kiện mở CM2: AG không còn finding chặn trong sửa v2, tests/replay phù hợp
bindings bản cuối, ba finding schema/previous/metrics đã kiểm lại, các giới hạn
offline/full traversal còn lại được ghi rõ; Main đối chiếu evidence rồi chốt.
CM2 dự kiến chỉ mở evidence lifecycle (pin/park/reload/continuation và raw hiện
tại cho A/B), không tự mở live/CM3 hoặc đổi model/fusion/selector. Chưa có lệnh
triển khai CM2 trong gói review này.

Trả evidence để Main đối chiếu và nghiệm thu CM0–CM1. Chỉ sau review checkpoint
này mới xem xét CM2. Việc chạy inference/deploy vẫn do người dùng/AG thực hiện
trong scope riêng; hướng dẫn này không giao chạy live.
