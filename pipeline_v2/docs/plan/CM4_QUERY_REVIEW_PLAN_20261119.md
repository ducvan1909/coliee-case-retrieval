# CM4: xử lý từng query, khảo sát kết quả và mở quyền điều hướng

Ngày: 19/11/2026. Trạng thái: **đã triển khai Q1–Q4 và đạt kiểm local (122 CM4 tests); chờ người dùng/AG chạy nghiệm thu live**. Xem [báo cáo](../../reviews/cm4_query_review_v24/REPORT.md) và [lệnh giao AG](../../reviews/cm4_query_review_v24/AG_CHECK.md).
Code đối chiếu: `7c230e5`, CM4 `cm4-anchor-flow-v23`.

Sau triển khai Q1–Q4, người dùng yêu cầu dọn tool/hướng dẫn cũ: engine hiện `cm4-query-review-v25`, gate v4 không giữ aliases. Xem [cleanup](../../reviews/cm4_query_review_v24/CLEANUP.md). Phần dưới là kế hoạch và tiêu chí gốc; hướng dẫn chạy hiện hành nằm ở AG_CHECK đã liên kết trên.

## 1. Mục tiêu và phạm vi

CM4 mở ngân sách cộng dồn rộng để quan sát khả năng tự tìm, đọc, đánh giá và điều hướng của model. Không dùng ngân sách nhỏ hoặc ngưỡng chống lặp cố định làm lý do kết thúc thí nghiệm. AG theo dõi log và chủ động dừng khi model mất kiểm soát.

Các quyết định đã được người dùng đồng ý về hướng:

1. Phải kết luận một query trước khi chuyển query khác.
2. Khảo sát toàn bộ tập kết quả trước khi chọn đọc sâu; ghi rõ độ phủ.
3. Xem lại source gate để không bỏ mất nhu cầu truy nguồn chỉ vì thiếu citation/tên án rõ.
4. Cho phép tìm trên span thuộc paragraph bị cắt; mở thêm ngữ cảnh khi cần.
5. Loop guard phát cảnh báo; AG quyết định dừng qua STOP.

**Thuật ngữ:** trong kế hoạch này `search_query` là một lần gửi text tìm kiếm và tập kết quả của lần đó, không phải toàn bộ án A. Một A có nhiều nhu cầu nguồn; một nhu cầu có thể cần nhiều query nối tiếp. Đây là contract dùng cho đợt triển khai đã được yêu cầu.

Giữ model, tokenizer, ba kênh retrieval, chunk/index và RRF hiện có. Giữ input cap 8.500, output cap 512 làm cấu hình ban đầu; thay đổi nếu có evidence output bị cắt, không tự tăng trong cùng phép so sánh. Không triển khai thêm heuristic citation hoặc phân tích ngữ nghĩa toàn corpus. Không sửa artifact đã seal/báo cáo lịch sử. Chưa thay thuật toán chọn án cuối ngoài việc tách rõ trạng thái dang dở.

## 2. Vấn đề trong bản hiện tại

| Vị trí | Hiện trạng quan sát được | Hệ quả |
|---|---|---|
| `engine.py`, review progress và source gate completion | Chặn finish khi còn cặp chưa review, nhưng deferred pairs được loại khỏi phần bắt buộc xử lý | Complete có thể còn phần chưa được đánh giá; phải công khai ý nghĩa |
| `engine.py`, context paging; `live.py`, instructions | Tối đa 5 cards/trang, ưu tiên đánh giá án đang mở | Dễ tập trung trang đầu trước khi biết toàn bộ tập |
| `live.py`, instructions | Đòi source signal của một judgment khác | Có thể chặn mệnh đề pháp lý cần nguồn nhưng không nêu nguồn rõ; đây là giả thuyết cần kiểm tra |
| `source_gate.py`, `evaluate` | Quyết định cuối cần `paragraph_coverage == full` | Span hữu ích trong paragraph quá dài có thể không được cấp quyền tìm |
| `live.py`, `LoopGuard` và `run_loop` | Tự stop khi no-progress 6 hoặc cycle 3 | Chưa đúng phân công AG kiểm soát; coverage tăng cũng chưa chứng minh tiến triển ngữ nghĩa |

Host chứng minh được raw đã cấp và assessment hợp lệ về cấu trúc; không chứng minh model đã hiểu hoặc quan hệ viện dẫn đúng. Mọi quyết định ngữ nghĩa của model phải tách khỏi gold.

## 3. Luồng và trạng thái đề xuất

```text
Đọc A / xác định nhu cầu nguồn
       ↓
Tạo search_query → đóng băng tập kết quả của query
       ↓
SURVEY: xem hết các trang kết quả, đánh dấu ưu tiên
       ↓
REVIEW: chọn án → raw A/B → assessment hoặc ghi thiếu evidence
       ↖ quay lại tập kết quả, đổi ưu tiên ↙
       ↓
CLOSE_QUERY: kết luận và kê khai phần chưa đọc/chưa giải quyết
       ↓
Mở quyền tạo query tiếp theo hoặc tiếp tục khảo sát A

AG STOP / lỗi / provider unknown → INTERRUPTED (không coi là kết luận)
```

Các trạng thái tên dưới đây là contract đề xuất, chưa phải API đang tồn tại:

- Query: `surveying`, `reviewing`, `concluded`, `interrupted`.
- Candidate trong query: các trục độc lập `survey_exposed`, `priority`, `raw_exposed`, `assessment_status`, `unresolved_reason`. Không dùng một boolean `reviewed` để thay tất cả.
- Query conclusion: `resolved`, `partially_resolved`, `no_supported_source_found`. Đây là kết luận trong tập đã truy hồi, không phải khẳng định toàn corpus không có nguồn.
- Án đã đọc nhưng thiếu evidence có thể giữ `unknown`; án chưa đọc raw phải giữ `not_read`, không chuyển thành `not_supported`.

## 4. Mốc Q1 — Khóa xử lý từng search query

### Thiết kế

- Host giữ `active_search_query_id`, liên kết operation, source need, nguyên text query, provenance A và ordered result IDs.
- Tập kết quả cố định theo receipt của operation. Query khác có cùng án vẫn là lượt đánh giá theo nhu cầu tương ứng; có thể tham chiếu evidence trước, không tự coi assessment cũ là đáp án nhu cầu mới.
- Khi active query chưa concluded, không cấp quyền thực hiện retrieval mới. Không chặn các thao tác đọc, navigation, assessment, mở header, bổ sung ngữ cảnh A/B và báo blocker.
- Stage một nhu cầu/query nháp nếu cần nhưng không cho thực thi trước khi đóng query hiện tại. Không cần tính năng stage mới để đạt mốc đầu.
- Thêm thao tác đề xuất `conclude_search_query`: model nêu kết luận, nhu cầu còn thiếu, lý do ngừng đọc sâu. Host tự dựng danh sách/counters còn tồn; model không tự khai hash, offsets hay tổng số.
- Chỉ cấp conclude sau survey đủ tập kết quả; không bắt mở raw đủ 50. Mọi candidate chưa có kết luận phải có disposition rõ: ưu tiên thấp sau survey, đã đọc nhưng thiếu evidence, hoặc chưa xử lý kèm lý do.
- Một lý do có thể áp dụng cho một nhóm refs để tránh output dài; model không được tự sửa trạng thái assessment bằng disposition.
- Cho phép query `partially_resolved` kết luận rồi tạo query mới nhắm vào phần còn thiếu. `defer_case_pair` đơn lẻ không tự đóng query.
- Query không có hits vẫn có conclusion rõ. Retrieval lỗi/unknown không được ghi như query zero-hit thành công.
- Tách `query concluded` khỏi `case review complete`. Case-level report phải thống kê query partial, nhu cầu chưa tìm, cặp unresolved; không dùng nhãn complete để che phần còn thiếu.

### Nghiệm thu local

1. Đọc 5/50 rồi gửi search mới bị từ chối, không phát backend/embedding request.
2. Hoãn một candidate không mở khóa query mới; conclude mới mở khóa.
3. Kết luận partial giữ đủ danh sách chưa đọc/unknown và giải thích; không biến thành prediction âm.
4. Resume khôi phục active query, tập kết quả và phase; không replay retrieval.
5. Các query trùng/hits trùng và zero-hit có state nhất quán; query receipt lỗi/unknown giữ riêng.

Đầu ra: code/tests, state contract và báo cáo local. Dừng nghiệm thu Q1 trước mở Q2.

## 5. Mốc Q2 — Khảo sát rộng rồi chọn đọc sâu

### Survey cards và pagination

- Mỗi card có ref, rank, tên/định danh nếu đã quan sát được, passage preview hiện có, kênh hỗ trợ và trạng thái xử lý. Không bịa tên án; không thêm summary suy luận cho cả corpus.
- Card/preview có source provenance; preview luôn là lead. Không dùng preview thay evidence raw cho assessment.
- Giữ pagination theo token budget; 5 là kích thước ban đầu, không mặc định phải cố nhồi 50 cards vào một payload.
- Mỗi payload có tổng kết quả, số cards đã cấp, vị trí trang, số trang/candidates chưa cấp và lối sang phần chưa thấy. Nếu token fitting giảm số cards, tính theo cards thực sự được giao.
- Theo dõi union các IDs được cấp trong payload, không tính merely fetched/rendered-before-fit. Compile preview với `admit=False` không làm tăng delivery coverage.
- Khi survey chưa đủ, chỉ mở tool khảo sát/đánh dấu ưu tiên/đọc thêm A/báo blocker; chưa mở luồng đọc sâu B. Điều này làm rõ chi phí và tác dụng của survey-first.
- Model đánh dấu `read_next`, `maybe`, `low_priority`, kèm lý do ngắn hoặc lý do chung cho nhóm refs. Không ép một tỷ lệ chọn hoặc K đọc sâu cố định.
- Sau survey, giữ danh sách ưu tiên qua các lượt; được đổi thứ tự/chọn thêm khi raw cho thấy giả thuyết ban đầu sai.

### Counters và luồng review

Tách hai loại counters: unique cases và `(search_query, candidate)` để tránh đếm trùng án thành nhiều án khác nhau.

| Counter host dựng | Ý nghĩa |
|---|---|
| retrieved | Tập kết quả đã receipt thành công |
| survey_exposed / not_exposed | Cards đã/chưa thực sự cấp cho model |
| selected_for_read | Model chọn đọc sâu, có thể đổi |
| raw_exposed | Có raw B thực sự đã cấp, không chỉ preview |
| assessed | Có assessment hợp lệ, phân tách supported/unknown/similarity/... |
| unresolved / not_read | Phần chưa giải quyết, không gộp vào assessed |

Luôn hiện tóm tắt ngắn các counters và số việc còn tồn. Host không gán tên `understood`/`verified_semantic` từ delivery.

Trong review, model có thể chuyển candidate để so sánh sau khi lưu trạng thái hiện tại; bỏ yêu cầu cứng đánh giá xong candidate đang mở mới được chuyển. Khóa theo query, không khóa theo candidate.

### Nghiệm thu

- Fixture 50 hits/10 trang: không conclude hoặc đọc sâu trước survey đủ; next/back và resume không làm tăng đếm sai.
- Card bị loại bởi token fitting không được tính exposed; controls vẫn đến được các cards còn lại.
- Survey priority không tạo assessment; án low priority chưa đọc không bị ghi not_supported.
- Chuyển candidate rồi quay lại giữ evidence, priority, unresolved state.
- Survey đủ không tự kích hoạt conclusion. Không ép đọc sâu tất cả 50.

## 6. Mốc Q3 — Source gate theo nhu cầu nguồn và span partial

### Hai câu hỏi độc lập

1. Có mệnh đề cần tìm án làm nguồn không?
2. Có nguồn cụ thể đã được nêu trong raw không?

Câu 2 không phải điều kiện bắt buộc cho câu 1. Model quyết định `search_needed`, `no_search_needed`, `need_more_context`; giữ attribution và lý do. Không thêm regex/heuristic làm bộ lọc semantic cứng.

- `search_needed`: chọn span mệnh đề và giải thích vì sao cần nguồn. Citation/tên nguồn là evidence tùy chọn; cho phép mệnh đề không có đầu mối tên/citation rõ.
- `no_search_needed`: chỉ áp dụng cho phạm vi đã đọc; không suy từ vài dòng sang toàn paragraph/án.
- `need_more_context`: ghi cụ thể thiếu chủ thể, đầu/cuối mệnh đề, quotation hay quan hệ với đoạn khác; mở theo nhu cầu.
- Giữ original `issue` là text gửi retrieval. `source_proposition` là model annotation/debug, không tự ghép vào query.
- Không mặc định mọi câu có thuật ngữ pháp lý đều cần tìm. Gate là model judgment cần đánh giá độc lập.

### Span partial

- Bỏ `paragraph_coverage == full` như điều kiện cứng cấp quyền tìm.
- Tách metadata khách quan `paragraph_complete`/delivered spans khỏi model judgment `sufficient_for_search` và `missing_context`.
- Mệnh đề phải nằm trong raw đã giao, có source hash, UTF-8 byte span, text hash; host tiếp tục kiểm binding.
- Span đủ ý được tìm dù paragraph dài chưa đọc hết. Nếu mệnh đề trải qua nhiều trang, đọc tiếp và hỗ trợ binding nhiều span hoặc ghép vùng liên tục từ nguồn đã giao với provenance đầy đủ; không buộc nguyên paragraph vào một payload.
- Cần thiết kế cụ thể cơ chế issued refs trên các trang trước: không chấp nhận ref chưa giao; không bỏ quyền chọn chỉ vì raw đã ra khỏi payload. Có thể reload excerpt gọn trước phê duyệt.
- Mở trước/sau theo source order, không dựa paragraph number ±1. Không sửa nguồn để ghép câu.
- Lưu coverage vùng đã quyết định `no_search_needed`; phần chưa đọc vẫn chưa được screening. Nhiều nhu cầu nguồn trong một paragraph không bị lần đầu screening che mất.
- Thay completion toàn A từ một boolean/paragraph sang coverage span + nhu cầu nguồn còn mở. Nếu policy vẫn yêu cầu screening toàn A, phải ghi rõ đây là quyết định riêng, không phải hệ quả bắt buộc của provenance.

### Nghiệm thu

1. Mệnh đề đủ ý trên trang giữa của paragraph quá dài được cấp quyền tìm, binding đúng.
2. Đầu/cuối câu thiếu hoặc attribution chưa rõ có đường đọc thêm, không deadlock.
3. `no_search_needed` trên span partial không đóng phần còn lại.
4. Ref sai hash/offset/không từng được giao bị từ chối; không bỏ validator để mở quyền semantic.
5. Một paragraph chứa nhiều nhu cầu vẫn tạo được các query nối tiếp theo khóa Q1.
6. Bộ tình huống: quy tắc không citation, dữ kiện thuần, quotation, ý kiến đương sự, song ngữ, tên nguồn rõ. Protocol PASS không tính là semantic PASS.

### Kiểm gate quá hẹp

Sau khi Q3 local PASS, review độc lập mẫu các span model bỏ qua và cho tìm thử cùng các span đó trong run riêng. Tách `missed_source_need` khỏi `query_failure`, `retrieval_failure` và `candidate_review_failure`. Ghi tiêu chí reviewer và unknown; không gọi model-generated labels là gold. Nhãn chuẩn, nếu dùng, chỉ evaluator sau run, không vào prompt/tool solver. Không mở holdout cho đợt thăm dò này.

## 7. Mốc Q4 — AG giám sát, loop guard chỉ cảnh báo

- Thêm cấu hình đề xuất `--loop-guard-mode warn|stop`, profile CM4 mặc định `warn`. Flag này **chưa tồn tại** ở code đối chiếu.
- Ngưỡng no-progress/cycle giữ làm detector cảnh báo, không gọi `engine.stop` trong warn mode, kể cả khi resume/replay guard.
- Log cảnh báo có active query, phase, candidate, tool/args đã lọc, byte coverage mới, assessment delta, pending counters, request/token/latency cộng dồn và chuỗi hành động liên quan.
- Không mặc định raw mới = tiến triển ngữ nghĩa. Log đủ để AG xem việc đọc thêm có giải quyết nhu cầu không.
- Không gửi cùng cảnh báo dài vào mọi payload. Ghi log và thông báo gọn khi cần; không dùng cảnh báo tạo vòng lặp mới.
- Giữ STOP ở safe boundaries và trong transport polling theo contract hiện có. STOP không bảo đảm provider call đang chạy đã bị hủy; ghi call ID/trạng thái và usage unknown khi chưa biết.
- Audit các điểm dừng khác, nhất là repeated tool-input rejection. Chuyển những giới hạn mang tính policy về thử lại sang cảnh báo/AG điều khiển nếu còn đường sửa. Vẫn không execute action sai schema hoặc provenance.
- Provider error/unknown, source corruption, schema không thể biên dịch là lỗi kỹ thuật riêng; giữ receipt thật, không giả thành model đã kết luận hoặc tự resend unknown admission.
- Không dùng giá trị ngưỡng cực lớn để giả lập warn mode; phải có branch rõ và test.

### Nghiệm thu

- Vượt ngưỡng cycle/no-progress trong warn mode vẫn chạy; stop mode còn hoạt động khi chủ động chọn.
- Resume từ log đã có cảnh báo không tự dừng warn mode; không phát lại request đã hoàn tất.
- STOP trước admission, trong chờ reply và trước action giữ trạng thái/receipt nhất quán.
- Invalid tool không được thực thi; có repair hoặc báo lỗi rõ. Không đánh đồng việc bỏ guard với bỏ validation.
- AG có thể xác định query/candidate đang kẹt, bước cuối và tổng usage từ log mà không đọc toàn bộ database thủ công.

## 8. Điều phối triển khai và điểm dừng nghiệm thu

Mỗi mốc Q1 → Q2 → Q3 → Q4: Main chốt contract, giao implementer phạm vi; tester/tester_advanced kiểm độc lập trên code cuối. Hai agent không sửa cùng file. Vì các mốc cùng chạm engine/live, triển khai tuần tự; tester có thể chuẩn bị tình huống trước.

| Scope | File dự kiến |
|---|---|
| State, tools, delivery, completion | `experiments/context_manager_v2/engine.py`, `model_view.py`, các options liên quan |
| Gate và span semantics | `experiments/context_manager_v2/source_gate.py`, evidence/anchor helpers khi cần |
| Runner, guard, log, instructions | `experiments/context_manager_v2/live.py`, helper log dùng chung nếu thực sự cần |
| Tests | `experiments/context_manager_v2/tests/`, M6 tests bị ảnh hưởng |
| Hướng dẫn | `CM4.md`, `MODEL_CONTEXT_FLOW.md`, latest handoff; không sửa báo cáo lịch sử |

Mỗi mốc cung cấp diff, test command/result, state/schema thay đổi, hạn chế và hướng dẫn AG. Theo yêu cầu mới “làm toàn bộ các mốc”, Main nghiệm thu local và tiếp tục tuần tự Q1–Q4 trong cùng đợt; không cần chờ xác nhận riêng từng mốc. Inference/deploy vẫn do người dùng hoặc AG chạy. Trước live tích hợp, xử lý hoặc cô lập rõ fixture regression M6 đã biết; không dùng skip do thiếu cache để tuyên bố lỗi đã hết.

## 9. Lệnh kiểm local và lệnh giao AG

### 9.1 Local, không inference/deploy

Các CLI hiện có, chạy tại root repo. Có thể dùng ngay để lấy baseline; không chứng minh tính năng đề xuất đã tồn tại.

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_source_selection pipeline_v2.tests.test_m6_hybrid -q
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live --help
```

Sau mỗi mốc chạy tests phù hợp mới bổ sung; trước pilot chạy cả CM4 suite và các regression bị ảnh hưởng. Ghi cả số skip và nguyên nhân, không chỉ exit code.

### 9.2 Fresh prepare — chỉ sau khi triển khai và local PASS

Command dưới dùng CLI hiện có. Sau Q4 phải kiểm plan xác nhận `loop_guard_mode=warn`; nếu chưa có trường này, không dùng run đó để nghiệm thu Q4.

```powershell
$cmRun = 'cache/cm4-query-review-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $cmRun
if ($LASTEXITCODE -ne 0) { throw 'Prepare failed; do not run inference.' }
Get-Content (Join-Path $cmRun 'plan.json')
```

Kiểm source/code/config binding, target query, search_limit 50, input 8500, output 512, cumulative uncapped, warn mode, không max-turn cap vô tình. Prepare phải 0 controller/embedding requests. Khi đổi code/settings/máy phải namespace mới; không cần mang run cũ để tạo run mới.

### 9.3 Live — người dùng hoặc AG chạy, Codex không tự gọi

Sau khi Main nghiệm thu Q1–Q4 và người dùng cho chạy pilot, giao AG một A discovery cố định đã được duyệt, settings và commit cụ thể. Default hiện là `021095.txt`; nếu đổi A, tạo settings riêng, ghi đầy đủ cấu hình, không sửa plan đã prepare.

AG kiểm metadata deployment/function pin đúng phiên bản dự kiến trước run; nếu cần deploy, Main cung cấp riêng lệnh đúng cho commit đó. Không tự đổi app/function pin để vượt mismatch.

Trong cùng PowerShell session đã prepare thành công:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir $cmRun
```

Ở terminal giám sát khác, đặt biến đúng đường dẫn run đã in ở trên:

```powershell
# Thay bằng thư mục run thực tế; không tạo một timestamp mới ở terminal này.
$cmRun = 'cache/cm4-query-review-REPLACE_WITH_ACTUAL_TIMESTAMP'
Get-Content (Join-Path $cmRun 'trace.jsonl') -Tail 30 -Wait
```

Khi AG quyết định cần dừng, ghi lý do/step quan sát được rồi tạo STOP:

```powershell
New-Item -ItemType File -Path (Join-Path $cmRun 'STOP') -Force
```

Nếu process mất kết nối: kiểm ledger/receipt/call ID trước resume. Không tạo run mới gửi lại khi admission cũ còn unknown; không tự xóa STOP rồi resume run đã terminal. Không đòi chạy lại các thí nghiệm lịch sử.

### 9.4 AG cần trả về gì

- Commit, settings, plan/binding, run path và lệnh/exit code.
- Theo từng query: text gửi thật, 50 hay ít hơn hits thực tế, survey/raw/assessment counters, lý do conclude và phần còn tồn.
- Chứng cứ không phát query mới trước conclusion; không dừng sau trang đầu khi chưa survey đủ.
- Các quyết định gate, span partial, missing context và mọi validation rejection.
- Cảnh báo loop, AG có can thiệp không, lý do/step dừng nếu có.
- Controller/embedding requests, input/output tokens, latency cả lỗi/retry; giữ riêng unknown. Đọc log/provider receipts, không suy usage từ budget.
- Không nhận định recall/F1 khi chưa chạy evaluator có gold và denominator đầy đủ.

## 10. Pilot và tiêu chí quyết định tiếp

Pilot đầu là kiểm hành vi, không phải tối ưu điểm số. Chọn A discovery có đủ nhiều kết quả, sau đó mới thêm trường hợp paragraph dài và không có citation rõ. Chốt danh sách trước run; không chọn lại chỉ vì kết quả đẹp.

Thành công engineering: thực thi đúng Q1–Q4, không mất provenance/state/resume, log giải thích được việc dừng. Thành công hành vi: survey đủ, model chọn và đổi ưu tiên có căn cứ, giữ unknown thay vì kết luận vượt evidence. Chất lượng tìm nguồn phải đánh giá riêng; đọc nhiều hơn không tự động tốt hơn.

Các rủi ro cần quan sát: survey-first gây quên trang đầu; disposition quá dễ trở thành cách bỏ hàng loạt án; source gate mở rộng gây nhiều query không hữu ích; warn-only để model đọc mãi. Không chữa bằng cap ngầm: giữ evidence, để AG can thiệp và điều chỉnh sau review.

## 11. Các điểm cần người dùng review

1. Khóa theo một search query như định nghĩa mục 1; không phải bắt giải quyết xong toàn nhu cầu pháp lý mới được reformulate query.
2. Bắt khảo sát hết tập kết quả trước đọc sâu B; không bắt raw đủ 50.
3. Cho conclude partial nếu kê khai phần còn tồn, rồi query tiếp nhắm vào chỗ thiếu. Không tính defer tự động là kết luận.
4. Mở gate cho mệnh đề cần nguồn không có citation rõ; cho partial span, vẫn giữ validation provenance.
5. Warn-only cho loop policy; AG STOP. Lỗi kỹ thuật/unknown receipt vẫn xử lý theo trạng thái thật.

Người dùng đã yêu cầu triển khai toàn bộ các mốc sau review. Tài liệu này không phải receipt PASS và không cấp quyền Codex tự chạy Modal.
