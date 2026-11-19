# Khảo sát một query có AG giám sát

## Sửa payload sau lượt tìm đầu tiên

Policy thử nghiệm v4 rút ngắn **key lựa chọn tool** bằng digest ổn định của key
canonical và bỏ lặp các source need giống hệt nhau: `m6.source_needs` giữ đầy đủ
need, mỗi candidate giữ các key trỏ vào bảng đó. Cả bảng vẫn hiện trong payload.
Host kiểm digest/ref và hydrate một bản sao khi tạo catalog hoặc dịch action;
binding được dispatch vẫn giữ nguyên nguồn, hash, span, lead và toàn bộ need.
Không đổi K=3, fusion, raw text, per-request input 8.500/output 512, hoặc bỏ route
map/đọc để làm vừa payload. Alias không dùng số thứ tự có thể trỏ sang binding khác
ở lượt sau; collision bị từ chối.

Ngoài ra, bản mô tả `available_tools` trong **text prompt** trỏ enum lựa chọn đến
table `m6` hoặc `current_payload_source_refs` đã có thay vì lặp nguyên danh sách
ref trong nhiều trường. Đây là bản sao riêng của tool metadata; JSON Schema đầy
đủ gửi decoder và dùng ở host vẫn giữ enum, required, types, limits và fingerprint.
Không rút gọn mô tả pháp lý, ví dụ, raw evidence hoặc quyền truy cập nguồn.

Đây là thay đổi code/schema binding: **prepare run mới** sau khi kiểm local. Không
resume hay sửa run lịch sử đã dừng `payload_token_cap`.

Tái dựng request kế tiếp từ ledger, không gọi model/embedding/retrieval và không
ghi vào run nguồn; tùy chọn cuối đọc một passage lead hiện có bằng source reader
local, rồi dựng tiếp payload A/B bằng hành động model giả lập:

```powershell
$replay = 'cache/m6-payload-replay-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.replay_payload --source-run cache/m6-uncapped-021095-20261114-200422096 --output-dir $replay --dry-open-first-candidate
Get-Content "$replay/report.json"
```

Report phân biệt baseline chưa compact với payload mới, count bằng tokenizer/chat
template pin, và SHA-256 mọi file run lịch sử trước/sau. `token_removal_deltas` là
chênh lệch khi bỏ từng trường, **không cộng được** vì các trường/nested fields chồng
nhau và tokenizer phụ thuộc ngữ cảnh. File event `scripted_candidate_read_events`
chỉ là probe offline, không phải provider receipt hoặc usage thật.

Toàn bộ code/profile của thử nghiệm nằm trong thư mục này. Production không import
thư mục này; xóa nó không đổi đường chạy chính. Không sửa model, chunk, indices,
fusion, K=3, selector hoặc snapshot đã seal. Không dùng pool 10 án/gold để cấp ứng
viên. Query đầu tiên khóa ở **021095.txt**, thuộc discovery đã exposed. Chưa mở
sang query khác hoặc holdout.

Authorization mới: người dùng yêu cầu thử bỏ giới hạn embedding/action và để AG
quan sát/dừng; sau đó yêu cầu làm luôn RT4 và RT5. Đây là nhánh thử nghiệm đi trước
gate RT3/context theo yêu cầu mới, không phải tuyên bố đã nghiệm thu các gate đó.
Codex chỉ chuẩn bị code/lệnh và kiểm local; **người dùng/AG chạy inference/deploy**.
Không deploy từ bộ thử này. Theo receipt
`cache/modal_pending_calls_cancellation_20261114.json`, AG đã dừng app cũ, hai call
cũ đều `TERMINATED`, backlog bằng 0; giữ nguyên lịch sử admission và usage, không
gửi lại call cũ. Sau deploy module mode và cập nhật function-ID binding,
`cache/modal_canary_20261114_v3.json` ghi canary **30 input token PASS**. Đó là kiểm
startup/structured output, chưa phải canary gần 8.500 token. Giữ function-ID guard;
source context 12.288 không thay đổi trong bản sửa payload này.

## Hai chế độ độc lập

| Profile | Controller | Embedding | Dừng no-progress tự động |
|---|---|---|---|
| `settings.json` (`uncapped`) | Requests/actions/input tổng dùng sentinel `2**60`; không có total-token cap | Requests/input tổng dùng cùng sentinel | Tắt; AG quyết định qua log/STOP |
| `rt5_settings.json` (`rt5`) | 8 requests/actions; input tổng 68.000, total 72.096 | Tối đa 5 requests / 2.240 input tokens | Giữ policy 4 action không tiến bộ |

Sentinel là **1.152.921.504.606.846.976**, giới hạn hữu hạn rất lớn để tái dùng
contract production; không phải vô hạn toán học. Cả hai chế độ giữ input mỗi lượt
8.500, output **512** (RT4), retry 0, giới hạn input từng embedding và các guard
nguồn/schema/context/duplicate-action/recovery. Model vẫn có thể tự chọn kết thúc.
Không tăng cap engine hoặc bỏ context check. Năm embedding là trần, không bảo đảm
8 action đủ navigation/đọc/tìm năm lần. Không nhầm chi phí controller với embedding.

RT4 chạy qua policy riêng chỉ được nạp bởi runner thử nghiệm. Action issue search
bắt buộc thêm `source_proposition` ngắn để debug, sinh cùng lượt với `issue`.
Chỉ `issue` được gửi tới retrieval; mệnh đề không ghép vào query/fusion/selector.
Prompt hướng dẫn giữ cụm phân biệt và tình tiết hữu ích, tránh query chủ đề quá rộng
hoặc gộp nhiều nhu cầu nguồn. Không thêm nhóm đầu mối mới hay tool identity/literal.
Annotation của model không phải gold; log không tiết lộ suy nghĩ nội bộ của model.

## Chuẩn bị local, không inference

Chạy ở repo root với raw/artifacts/sparse và tokenizer pin đã có. `prepare` không
khởi tạo hybrid remote session, không gọi controller/embedding/Qdrant retrieval.
Nó có thể mất thời gian để kiểm nguồn/index. Mỗi lượt cần namespace mới.

```powershell
$probe = 'cache/m6-uncapped-021095-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.runner prepare --run-dir $probe
if ($LASTEXITCODE -ne 0) { throw 'Prepare loi; giu run/log, khong chay inference' }
Get-Content "$probe/plan.json"
```

Kiểm `preflight_status=ready`, `model_requests=0`, payload không quá 8.500, mode và
caps đúng. Plan/first payload write-once; code/source/profile/tokenizer bindings
phải còn khớp khi run. Đừng sửa settings, hash hoặc plan để resume qua drift.

Để chuẩn bị **RT5 có giới hạn** thay vì uncapped, dùng thư mục run khác:

```powershell
$rt5 = 'cache/m6-rt5-021095-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.runner prepare --settings pipeline_v2/experiments/uncapped_probe/rt5_settings.json --run-dir $rt5
```

Không chạy cả hai profile đồng thời. Khảo sát uncapped trước rồi đọc kết quả và
quyết định chạy RT5; profile thứ hai không tự được runner gọi nối tiếp.

## AG chạy và đánh giá tiến trình

Sau khi kiểm runtime/function binding/context hiện hành và Qdrant local sẵn sàng,
AG chạy **một** run đã prepare ở trên; đây là inference thật:

```powershell
& .venv/Scripts/python.exe -u -m pipeline_v2.experiments.uncapped_probe.runner run --run-dir $probe 2>&1 | Tee-Object -FilePath "$probe/console.log" -Append
```

`trace.jsonl` được append và flush mỗi sự kiện. Console cũng phát JSONL và có thể
có heartbeat nguyên gốc của adapter. Theo dõi bằng terminal thứ hai:

```powershell
Get-Content "$probe/trace.jsonl" -Tail 30 -Wait
# Snapshot riêng, read-only, không gọi remote hoặc tạo writer:
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.runner status --run-dir $probe
```

Log gồm: mở index/nguồn; chuẩn bị lượt model; raw A refs/spans và map đang offer;
request/response controller với action thực sự; action pipeline và kết quả;
query thực gửi; stage embedding; dense exact; candidate IDs, raw coverage,
assessment counts; usage và latency. Heartbeat mỗi 10 giây chỉ cho biết client
đang chờ ở stage nào, **không khẳng định GPU/model đang tiến bộ**. Call ID controller
được đưa vào heartbeat khi có. Payload/action/results canonical nằm trong
`events.sqlite3`, embedding reservations/receipts trong `embedding_events.sqlite3`,
RT1 raw channel results trong `retrieval_diagnostics/`. Không in credential/env.

AG đọc log và quyết định dừng khi có evidence như:

- Lặp các vùng/map hoặc query tương đương, không thêm raw/candidate/evidence hữu ích.
- Action duplicate liên tiếp hoặc chuyển đi/chuyển lại giữa cùng vài vùng mà không
  giảm nhu cầu thiếu evidence.
- Stage remote chờ kéo dài và không có bằng chứng tiến bộ từ call/container logs;
  ghi đây là nghi kẹt, không tự suy ra OOM hay zero usage từ heartbeat.
- Model tự dừng hoặc có lỗi/unknown: giữ đầy đủ run và chi phí, không resend.

Ghi lý do, đoạn log và thời gian khi dừng. Đây là quan sát của AG, không phải một
threshold tự động đã được hiệu chỉnh. Không đánh giá legal correctness chỉ qua
schema/provenance PASS; không đưa gold vào prompt hoặc dùng gold để dẫn đường chạy.

## Dừng an toàn

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.runner stop --run-dir $probe
```

Lệnh tạo `STOP`; runner kiểm trước **mỗi request mới và mỗi action đang chờ thực
thi**. Nếu một request/tool đang chạy, nó được phép trả về rồi runner dừng trước
bước tiếp. Heartbeat báo `stop_requested=true`. Nếu model đã trả action mà chưa
thi hành, action đó được giữ trong ledger dưới terminal `operator_stop_file`.
Đây là dừng ở ranh giới an toàn, không phải lệnh hủy GPU tức thì.

Nếu stage đang kẹt và cần ngắt client ngay, dùng **Ctrl+C** ở terminal chạy. Runner
cố lưu report với receipt/call ID, giữ in-flight/active-action chưa rõ. Không khẳng
định remote đã hủy; kiểm metadata call hiện có. Không xóa ledger, reset admission,
resend hoặc tự mở run khác để thay một request unknown. Recovery production giữ
unknown và không replay. STOP file được giữ nguyên; muốn khảo sát mới tạo run mới.

## Đóng băng và chấm sau khi chạy

Sau terminal hoặc ngắt client, lưu reports/trace/ledgers. Freeze phải thành công
trước khi score được đọc gold; không sửa run giữa hai bước. Đặt output ngoài run:

```powershell
$freeze = "$probe-freeze.json"
$score = "$probe-score.json"
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.evaluator freeze --run-dir $probe --out $freeze
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.evaluator score --run-dir $probe --freeze $freeze --out $score
Get-Content $score
```

Nếu evaluator từ chối vì admission/active action còn unresolved, giữ nguyên trạng
thái và đối chiếu call cũ trước; không sửa ledger để chấm. Chấm candidate recall
từng kênh/union/RRF/pool với denominator gold đầy đủ của một query, giữ lỗi/unknown;
không coi output `prediction=null` là kết quả chọn án đã nghiệm thu. So uncapped
với RT5 phải ghi rõ khác ngân sách và stop policy; không quy gain riêng cho prompt.

## Kiểm offline

```powershell
& .venv/Scripts/python.exe -m compileall -q pipeline_v2/experiments/uncapped_probe
& .venv/Scripts/python.exe -m pipeline_v2.experiments.uncapped_probe.runner --help
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/uncapped_probe/tests -p 'test_*.py' -v
```

Kết quả local/fixture chỉ chứng minh cơ chế trong phạm vi đã kiểm. Canary/context,
query quality, retrieval recall và vận hành uncapped thật cần evidence AG riêng.

Kiểm offline đã thực hiện ngày 14/11/2026: 16/16 tests đạt, gồm caps của hai
chế độ, giữ context, query restriction, live trace, STOP trước request/vào action,
recovery unknown không resend, status read-only, 12 lượt controller/action scripted,
7 embedding reservations, cap request/token embedding, RT4 schema/debug/query và
freeze/evaluator. Các embedding reservations chỉ ghi ledger fixture, không gọi model.
Không có request inference trong các test này. Kết quả prepare/corpus/live mới cần
đối chiếu riêng với report tương ứng; không sửa checkpoint lịch sử để ghi thành đạt.
