# Harness M4

Thiết kế gốc nằm trong [kế hoạch agent và đánh giá](plan/AGENT_AND_EVALUATION.md). Harness nhận profile và ngân sách từ caller. Caller cung cấp transport và hàm đếm token của payload thực tế. Replay local có thể thay cả hai bằng fixture.

## Nối công cụ M3

`pipeline_v2.m4.M3Tools` nhận một `SourceToolsSession` và một `SparseSession` do caller sở hữu. Có thể dùng cùng snapshot khi mở `SourceToolsSession(root, snapshot=lexical)`. Tái sử dụng hai session cho các action trong run.

- `query_start()` trả bản đồ query có phân trang và một excerpt toàn văn. Harness thử giao toàn văn trong ngân sách payload. Bản đồ giữ các handle, heading, role, dấu hiệu quan sát và preview có offsets/hash. Trang đầu có thể kèm vùng đọc quanh handle có anchor quan sát được hoặc paragraph đầu tiên có trên trang.
- `actions()` nối BM25 cấp án/passage, tìm trong án, phrase/identity, và các công cụ đọc nguồn. `open_source` nhận `open_ref` từ hit. `expand_source` nhận `continuation` từ trang trước, hoặc `target_handle` và `case_id`/`source_hash` để mở vùng đích. Các refs, byte spans và cursor thuộc cùng snapshot.
- `recorded_search` có thể nhận kết quả hybrid M3 đã xác minh để replay đúng query và index. Adapter kiểm fingerprint index và hash nội dung query. Chế độ `recorded_replay` giữ request ID gốc, còn lượt replay hiện tại chỉ đọc local.
- Truyền `verify_source=tools.verify_source` cho harness để kiểm lại hash nguồn khi giao excerpt và đánh giá liên kết. `byte_budget` giới hạn trang đọc của M3, còn token cap của payload thuộc harness.

## Chạy và tiếp tục run

Tạo `AgentHarness` với `RunIdentity`, `Budget`, danh sách baseline đã freeze (dùng `[]` cho fixture chưa có baseline), mapping action từ `tools.actions()`, `count_tokens`, `transport` và kết quả `query_start()` qua `initial_observation`/`query_excerpt`. Dùng `tools.fingerprint` cho `RunIdentity.tools_fingerprint`. Các fingerprint của corpus/index/profile, model, tokenizer và prompt cần phản ánh đúng inputs đã dùng. `count_tokens` phải tính theo request đã render cho model, kể cả prompt và tool schema mà transport thêm. Gọi `run()` để xử lý. `inspect()` trả trạng thái dựng lại từ ledger và `events()` trả lịch sử theo thứ tự ghi.

`events.sqlite3` lưu các sự kiện append-only. Mỗi request được ghi admission trước khi gửi. Đoạn đã mở nằm trong hàng chờ cho đến khi payload thực sự được dùng ở một lượt model. Assessment chỉ được viện dẫn excerpt có trong payload của lượt trả action. `reload_source` đưa lại excerpt đã mở vào payload kế tiếp và phần đọc lại được tính vào ngân sách.

Khi tiếp tục run, dùng lại `run_dir` với cùng cấu hình. Harness khôi phục cap và trạng thái từ lịch sử. Request chưa có kết quả được giữ với trạng thái chưa rõ để tránh gửi trùng. Nhánh fallback dùng baseline do caller cấp. M5 sẽ tạo baseline và policy chọn án dựa trên evidence.

## Schema và xử lý kết quả

Run mới dùng contract assessment ở [mục 2.1 của kế hoạch](plan/AGENT_AND_EVALUATION.md#21-ràng-buộc-đầu-ra-và-kiểm-bằng-chứng-cho-m4m5). `response_schema(tool_actions=...)` cung cấp JSON Schema theo tập công cụ của run. Transport hỗ trợ structured decoding qua `send_structured(payload, request_id, schema)` và có thể đặt text JSON gốc vào `ModelReply.action` để host parse. Adapter replay có thể trả `ModelReply` từ fixture. Phiên bản và fingerprint của contract được ghi cùng cấu hình run.

`validate_model_response()` dùng chính schema đó để parse và kiểm đầu ra. Kiểm refs trùng, provenance và trạng thái nguồn thuộc host. Ledger cũ giữ contract gốc khi đọc hoặc resume.

- `speaker.role=unknown` bỏ `type`. Các vai trò xác định nhận `type` theo từng nhánh. `case_relation` và `passage_location` là hai trục độc lập, nên `unknown` có thể đi cùng `pinpoint`.
- Host kiểm lại JSON và xác nhận refs thuộc raw text trong payload hiện tại, đúng vai trò A/B và đúng provenance. Host dựng ID assessment, phiên bản, raw quote và byte offsets từ refs. Dấu hiệu cấu trúc quan sát từ M3 hỗ trợ kiểm tra provenance. Độ đúng của kết luận về người nói và quan hệ A→B cần đánh giá trên dữ liệu có nhãn.
- Ứng viên chỉ có retrieval giữ quan hệ `unknown`. Hồ sơ thiếu bằng chứng giữ trạng thái `pending_evidence` cùng thông tin còn thiếu. Output sai schema hoặc refs bị từ chối và ghi lý do cùng usage vào ledger. Host áp dụng fallback theo chính sách run, với 0 request sửa output tự động. Retry lỗi transport vẫn theo budget đã khóa.

## Kiểm local

```powershell
& .venv/Scripts/python.exe -m pip install -r pipeline_v2/requirements-m4-local.txt
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m4_harness pipeline_v2.tests.test_m4_tools -v
```

Profile live cần model, tokenizer, prompt, giới hạn thực tế và kiểm thử riêng theo thiết kế. Kết quả replay chỉ xác nhận đường chạy local và tính đúng đắn của các quy tắc về nguồn và trạng thái.

## Nghiệm thu live trên Modal

Runner `pipeline_v2.m4_live` dùng app riêng `coliee-qwen36-27b-fp8-l40s` với Qwen3.6-27B-FP8 và vLLM/XGrammar. Adapter tra cứu app theo tên và kiểm ID function `fu-H0trMyuxzOOOWOyVIHfKp5` của deployment đã xác minh trước khi gửi inference. Workspace hiện tại từ chối tra cứu pin bằng `version=1`. Adapter gửi schema M4 theo từng request, đếm token local bằng tokenizer và chat template của checkpoint, giữ cap 8.192 token gồm prompt và phần sinh, tối đa 512 token đầu ra, và đối chiếu số đếm với usage từ engine. Các lệnh dưới đây chạy từ root repo với profile Modal có quyền gọi app.

```powershell
& .venv/Scripts/python.exe -m pip install -r pipeline_v2/requirements-m4-local.txt
$tokenizer = 'cache/tokenizers/qwen36_27b_fp8'
& .venv/Scripts/python.exe -m pipeline_v2.m4_live prepare-tokenizer --tokenizer-dir $tokenizer
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m4_corpus_action_policy pipeline_v2.tests.test_m4_modal_qwen pipeline_v2.tests.test_m4_harness pipeline_v2.tests.test_m4_tools -q
```

Sau khi kiểm local đạt, chạy probe một request. Payload chỉ chứa dữ liệu tổng hợp. Prompt cố yêu cầu `speaker.role=unknown` cùng `type`. PASS cần engine trả đúng nhánh ở lần đầu, harness ghi ref A hợp lệ, trạng thái `pending_evidence` do thiếu đoạn B, usage đầy đủ và 0 retry.

```powershell
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$probe = "pipeline_v2/reviews/m4_live_$stamp/probe"
& .venv/Scripts/python.exe -m pipeline_v2.m4_live probe --tokenizer-dir $tokenizer --run-dir $probe
```

Chỉ khi probe PASS, chạy một query kỹ thuật đã dùng trong kiểm local, `017984.txt`. Có thể dùng lại [probe đã đạt](../reviews/m4_live_20261112T081741491Z/probe/report.json) khi model, adapter và schema probe giữ nguyên. Runner dùng BM25 local và giới hạn tối đa sáu request model, 0 retry. Host giới hạn schema theo trạng thái của lượt. Lượt đầu tìm một hit, lượt sau mở hit nếu có `open_ref`, rồi nạp lại raw refs khi cần. Nhánh assessment chỉ mở khi A/B cùng có raw excerpts trong payload. Nhánh dừng xử lý khi đã có assessment hoặc không còn bước hợp lệ. Host kiểm lại schema của lượt trước khi thực thi action. PASS cần mọi response hợp lệ ngay lần đầu, ít nhất một assessment có raw refs cả A và B được validator chấp nhận, usage đầy đủ và kết thúc theo contract hoặc ngân sách.

Model nhận `available_tool` gồm tên, mô tả, lúc dùng, tham số và kết quả của tool được phép. `search_cases_by_issue` nhận `issue`. `read_case_passages`, `reload_delivered_passages` và `finish_case_review` nhận args rỗng khi host đã xác định tham số. Khi payload có đúng một đoạn gốc mỗi phía, `assess_case_link` chỉ nhận `case_relation`, `passage_location` và `reason` tối đa 120 ký tự. Host điền ID và raw refs từ payload, giữ speaker `unknown` trong lượt corpus một cặp. Probe schema vẫn kiểm nhánh speaker. Host kiểm schema ngoài rồi chuyển về action nội bộ của harness. Token count trước admission tính cả định nghĩa tool trong prompt. Report lưu tên tool model thấy, action nội bộ và fingerprint schema theo lượt.

```powershell
$corpus = "pipeline_v2/reviews/m4_live_$stamp/corpus"
& .venv/Scripts/python.exe -m pipeline_v2.m4_live corpus --tokenizer-dir $tokenizer --run-dir $corpus --query-id '017984.txt'
```

Mỗi lệnh live cần thư mục mới. Giữ `report.json` và `events.sqlite3` cho cả PASS lẫn FAIL. Báo cáo corpus lưu phiên bản policy, action được phép và fingerprint schema theo từng request. Khi lỗi hoặc receipt chưa rõ, dừng và gửi đường dẫn cùng exit code, số request/token/latency, trạng thái schema và assessment. Dùng kết quả này để nghiệm thu kỹ thuật M4. Độ đúng của kết luận pháp lý cần kiểm riêng trên dữ liệu có nhãn.
