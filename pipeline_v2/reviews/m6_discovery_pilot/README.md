# Pilot M6 hybrid trên ba query discovery

Chạy `017984.txt`, `090579.txt` và `021095.txt` theo thứ tự đã khóa trong [manifest](manifest.json). Đây là ba query đầu của discovery, đã được dùng trong chẩn đoán M5. Mỗi query tìm trong toàn corpus M3. Gold chỉ vào bộ chấm sau khi đóng băng các run. Tập holdout dành cho M7.

Profile thử nghiệm cho mỗi query có tối đa 8 request controller, 384 output token mỗi request, 7.400 input token mỗi payload, 2 request embedding và 896 embedding input token. Tổng trần ba query là 24 request controller và 6 embedding. Retry bằng 0. Tắt targeted review cho pilot này để tập trung vào tìm và đọc nguồn. Giữ các cap trong manifest khi phân tích kết quả.

## AG chạy live

M6 hiện chờ cùng một Modal controller call qua các lượt kiểm tra 30 giây. Nhật ký stderr có call ID và trạng thái chờ. Embedding cũng ghi thông báo khi chờ lâu. Qdrant dense exact không có hạn đọc phản hồi phía client, với trần xử lý phía Qdrant là 86.400 giây và timeout thiết lập kết nối là 10 giây. Thông báo đang chờ chỉ xác nhận phía client chưa nhận kết quả. Deployment Modal hiện áp giới hạn khởi động/thực thi 900/120 giây cho controller và 1.800/600 giây cho embedding. Các giới hạn này khác thời gian xếp hàng chờ GPU.

V19 hoàn thành Qdrant dense exact sau 454,33 giây. Request 4 có đủ raw A/B và tool assessment, nhưng Modal trả `ValueError` trước khi có output. Schema assessment chứa `uniqueItems`, từ khóa mà vLLM 0.19.1 từ chối khi dùng XGrammar. Receipt v19 thiếu thông báo exception gốc, nên chưa xác nhận được đây là nguyên nhân duy nhất. Bản sửa bỏ từ khóa khỏi schema decoder và kiểm ref trùng tại host. [Report v19](runs_v19/017984.txt/report_1794560623836988300.json) · [Validator upstream](https://github.com/vllm-project/vllm/blob/v0.19.1/vllm/v1/structured_output/backend_xgrammar.py)

V20 có 8/8 phản hồi hợp lệ và một assessment chờ bằng chứng. Đọc lại `073752.txt` trả 0 đoạn mới rồi controller lặp ba lượt. Schema v6 thu hồi lựa chọn đọc của B khi cùng đầu mối đã trả 0 đoạn mới. B vẫn nằm trong pool, có thể mở tiếp qua cursor, và các B khác vẫn đọc được. Đầu mối tìm mới có thể mở lại đường đọc. [Report v20](runs_v20/017984.txt/report_1794562392545685900.json)

V21 đã chuyển từ `073752.txt` sang `049344.txt` sau khi lần đọc lại trả 0 đoạn mới. Payload sau khi mở `049344.txt` đã có cặp A/B và tool assessment, nhưng controller chọn đọc lại B. Lần đọc này trả 0 đoạn mới, rồi payload kế tiếp vượt trần. M6 hiện lược lựa chọn đọc lại B ngay trong lượt giao bằng chứng A/B mới. Khi cần co payload, M6 cũng rút gọn các danh sách điều hướng ngay cả ở lượt chưa có cặp A/B. [Report v21](runs_v21/017984.txt/report_1794564604995732800.json)

AG chạy riêng `017984.txt` trong `runs_v22`. Kiểm action ngay sau mỗi lần giao cặp A/B, số đoạn mới sau khi mở B và trạng thái dừng. Ghi raw refs, assessment, số request và token. Khi chờ lâu, giữ log tiến độ và kiểm call ID, trạng thái container hoặc log Qdrant trước khi can thiệp.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir "pipeline_v2/reviews/m6_discovery_pilot/runs_v22/017984.txt"
```

**Đối chứng Qdrant bằng vector cache.** V15 chạy dense exact thành công sau 149,11 giây. V17 dùng cùng cụm tìm và timeout 240 giây nhưng Qdrant trả HTTP 500 báo timeout tại `points/query`. Thời gian 323,17 giây là toàn bước hybrid. [Report v17](runs_v17/017984.txt/report_1794556328542838900.json)

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m3_completion_v1.diagnose_dense_timeout
```

Probe dùng vector passage cache, 0 request controller/embedding, và dùng timeout 120 giây cho đối chứng toàn corpus. Khi so máy hiện tại với Linux/OCI CPU, dùng cùng collection, vector, bộ lọc và timeout. Dùng namespace mới cho lượt live sau khi xác nhận retrieval ổn định.

Các lệnh dưới đây ghi lại quy trình chạy batch v11. Khi mở batch mới, chuẩn bị cả ba query vào namespace mới và dùng cùng đường dẫn xuyên suốt.

```powershell
$pilot = 'pipeline_v2/reviews/m6_discovery_pilot'
$runs = "$pilot/runs_v11"
# Chỉ khi cần chuẩn bị lại, chọn namespace mới.
# $runs = "$pilot/runs_v14"
# & .venv/Scripts/python.exe -m pipeline_v2.reviews.m6_discovery_pilot.prepare --runs-dir $runs
Get-Content "$runs/preflight_summary.json"

& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir "$runs/017984.txt"
# Dừng tại đây nếu tool reply bị reject. Đọc request_result.m6_reply trong ledger.
# Chỉ chạy hai query tiếp theo sau khi lượt đầu đã thực thi được lượt tìm.
& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir "$runs/090579.txt"
& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir "$runs/021095.txt"
```

Giữ `plan.json`, `first_payload.json`, `events.sqlite3`, `embedding_events.sqlite3`, mọi `report_*.json` và ledger embedding M3 được liên kết. Khi receipt chưa rõ, dừng batch để đối chiếu call ID và ledger. Giữ kết quả lỗi, budget stop, schema reject và usage chưa biết. Chỉ resume cùng run theo quy trình M6, tránh gửi lại request chưa rõ. Nếu lỗi hạ tầng chặn các query còn lại, báo pilot chưa đủ và giữ toàn bộ artifact hiện có.

Sau query đầu, có thể đọc chẩn đoán từ ledger mà chưa cần freeze cả batch:

```powershell
@'
import json
import sys
from pipeline_v2.agent_harness.ledger import Ledger

for event in Ledger(sys.argv[1]).read():
    if event["kind"] == "request_result":
        fields = ("seq", "request_id", "status", "error", "schema_validation",
                  "input_tokens", "output_tokens", "m6_reply")
        print(json.dumps({key: event.get(key) for key in fields}, ensure_ascii=True))
'@ | & .venv/Scripts/python.exe - "$runs/017984.txt"
```

## AG đối chiếu gold sau khi có ba run terminal

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m6_discovery_pilot.evaluate freeze --manifest "$pilot/manifest.json" --runs-dir $runs --out "$runs/freeze.json"
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m6_discovery_pilot.evaluate score --manifest "$pilot/manifest.json" --runs-dir $runs --freeze "$runs/freeze.json" --out "$runs/gold_diagnostic.json"
```

`freeze` khóa manifest, plan, preview, ledger và receipt. `score` kiểm lại hash rồi mới đọc train gold. Báo recall trên **toàn bộ gold của ba query** và giữ các run terminal lỗi trong mẫu. Selector hiện chưa có, vì vậy `final_metrics` là null.

Trong báo cáo của AG, ghi bảng từng query với số gold, vào pool, đã mở, đã giao, đã assess, trạng thái dừng và usage của controller/embedding. Dùng `pairs[case_id].first_gap` và `trace` để lần về request/action hoặc span cụ thể:

| Điểm dừng | Cần kiểm tiếp trong log |
|---|---|
| `retrieval` | Nếu `search_action_executed=false`, kiểm `reply_rejection_seqs` và trường `m6_reply` trong trace trước. Nếu đã tìm, kiểm issue và đoạn A trong `action.args._m6_need.a_paragraph` hoặc citation đã chọn. Kiểm cụm tìm có bám đoạn đó không, rồi kiểm số lượt tìm, coverage và giới hạn pool. Gold ngoài pool chưa cho biết án rơi ở kênh nào hoặc ở RRF nếu ledger thiếu rank ngoài top K. |
| `source_open` | B có mặt trong pool nhưng chưa mở raw. Kiểm candidate/focus và budget tại lúc chọn đọc. |
| `evidence_delivery` | Đã mở nguồn, nhưng chưa có lượt nhận raw hoặc chưa có cặp A/B hợp lệ trong payload assessment. Kiểm refs, clipping và cap. |
| `assessment_missing/rejected/pending` | Kiểm tool đã cấp, output lỗi và refs thiếu. Đối chiếu nhận định với raw để xác định lỗi ngữ nghĩa. |
| `selector_unavailable` | Đã có assessment, đang chờ selector. Nếu nhãn đáng ngờ, xem raw A/B, attribution và phản chứng trước khi kết luận. |

Mỗi query chọn vài ví dụ lỗi có request ID hoặc event sequence, ghi đoạn raw và byte span khi có. Train gold là nhãn ở cấp cặp án A→B. Nó không chỉ định passage hay speaker đúng, nên kết luận lỗi attribution hoặc đọc sai đoạn cần bằng chứng riêng.

## Kiểm tra trước khi giao AG

Replay [kết quả hybrid đã lưu](payload_replay_v5/report.json) với tokenizer đã pin và cap của pilot đạt qua bước mở B, nạp lại A/B và assessment. Controller trong replay dùng hành động giả lập. Các lượt thử trước phát hiện payload bị cắt đến mức không thể assess. M6 hiện giữ raw A/B trước phần mô tả hoặc lựa chọn điều hướng trùng lặp khi cần co payload. Các lựa chọn bị lược được đếm trong payload. Kết quả live và đối chiếu gold thực tế sẽ do AG ghi sau khi chạy.
