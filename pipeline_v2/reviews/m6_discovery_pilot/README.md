# Pilot M6 hybrid trên ba query discovery

Chạy `017984.txt`, `090579.txt` và `021095.txt` theo thứ tự đã khóa trong [manifest](manifest.json). Đây là ba query đầu của discovery, đã được dùng trong chẩn đoán M5. Mỗi query tìm trong toàn corpus M3. Gold chỉ vào bộ chấm sau khi đóng băng các run. Tập holdout dành cho M7.

Profile thử nghiệm cho mỗi query có tối đa 8 request controller, 384 output token mỗi request, 7.400 input token mỗi payload, 2 request embedding và 896 embedding input token. Tổng trần ba query là 24 request controller và 6 embedding. Retry bằng 0. Tắt targeted review cho pilot này để tập trung vào tìm và đọc nguồn. Giữ các cap trong manifest khi phân tích kết quả.

## AG chạy live

**Bước hiện tại là canary grammar, sau đó chạy riêng `runs_v12/017984.txt`.** Dùng [hướng dẫn canary](ISSUE_GRAMMAR_CANARY.md) trước khi mở lại batch. `runs_v11` là lượt lịch sử đã ghi được phản hồi một ký tự. [Kết quả v10–v11](PILOT_V10_FINDINGS.md)

Các lệnh dưới đây ghi lại quy trình chạy batch v11. Khi mở batch mới, chuẩn bị cả ba query vào namespace mới và dùng cùng đường dẫn xuyên suốt.

```powershell
$pilot = 'pipeline_v2/reviews/m6_discovery_pilot'
$runs = "$pilot/runs_v11"
# Chỉ khi cần chuẩn bị lại, chọn namespace mới.
# $runs = "$pilot/runs_v13"
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
