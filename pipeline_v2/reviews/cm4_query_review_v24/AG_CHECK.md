# AG kiểm CM4: từng search query, survey và giám sát

**Đợt kiểm tiếp theo dùng CM4 v30.** Đọc [kết quả pilot v28 và kiểm lỗi dựng context](../cm4_survey_focus_fix_v1/PILOT_20261120.md). Nếu có nhiều nhu cầu nguồn chưa xử lý, kiểm tổng số, danh sách của trang hiện tại và khả năng chuyển trang. Khi `query_context_fallback` xuất hiện, kiểm model dùng `read_query_passages` để mở bản đồ vùng nhỏ hơn và đọc tiếp. Chỉ tính raw đã giao theo receipt. Tiếp tục đối chiếu query với mệnh đề A và kiểm chiều A viện dẫn B.

Ngày 19/11/2026. Hướng dẫn chạy sau khi Main xác nhận local PASS ở `REPORT.md` cùng thư mục. Không phải receipt live PASS.

Source gate hiện dùng v4 sau đợt cleanup. Thư mục này giữ tên v24 để liên kết báo cáo Q1–Q4. Dùng engine v30 và namespace mới theo mục dưới. Xem `CLEANUP.md` cho kết quả lịch sử của v25.

Pilot giới hạn ở một án A `021095.txt`. Khi được giao v30, AG kiểm đầu vào, tạo namespace mới, chạy và review ngữ nghĩa. Giữ nguyên STOP và receipts của các run trước. Xem [REPORT v27](../cm4_survey_focus_fix_v1/REPORT.md) và [REPORT v26](../cm4_map_projection_fix_v1/REPORT.md) cho các thay đổi trước pilot mới nhất.

**Blocker sau đổi tài khoản, 20/11:** đọc [bàn giao Modal mới](../cm4_survey_focus_fix_v1/MODAL_ACCOUNT_20261120.md) trước lần chạy tiếp. Attempt embedding gốc vẫn `started`; kill client/probe cancellation chưa chứng minh call gốc được hủy. Làm rõ trạng thái/cancel call gốc trước fresh retry, giữ usage unknown. Controller đã có canary PASS và pin mới; không deploy lại chỉ vì request embedding đang chờ.

## Phân công và mục tiêu

Codex triển khai Q1–Q4 và kiểm local. Chỉ người dùng hoặc AG chạy inference/deploy. Đợt này quan sát model khi mở ngân sách cộng dồn rộng: không tự áp max-turns hoặc thu nhỏ ngân sách để đạt exit sớm. Giữ model, tokenizer, chunk/index, RRF, input 8.500/output 512 và top 50 theo settings. Một search query là một text tìm và tập hits của nó, không phải toàn án A.

Đọc `CODEX_HANDOFF.md`, `pipeline_v2/docs/plan/CM4_QUERY_REVIEW_PLAN_20261119.md` và báo cáo local mới nhất trước khi chạy. Dùng assets local đã seal; không cần mang cache/run lịch sử sang máy khác. Không đọc gold vào solver. Chưa tự mở đánh giá holdout.

## 1. Kiểm checkout và local

Tại root checkout:

```powershell
git rev-parse --show-toplevel
git status --short
git rev-parse HEAD
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_source_selection pipeline_v2.tests.test_m6_hybrid -q
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live --help
```

Ghi số tests và skips. Replay V15/V20/V21 có thể thiếu ledger cũ; không cần dựng lại receipt cũ, không gọi skip là đã xác minh regression lịch sử.

## 2. Kiểm deployment metadata và nguồn retrieval

- Xác nhận deployment/function pin trong `agent_harness/modal_qwen.py` khớp metadata app hiện tại; không tự sửa pin để bỏ guard. Đọc metadata không thay cho canary thành công.
- Qdrant local và collection đúng bundle, sparse/raw/tokenizer assets hiện diện. Không embed lại corpus.
- Nếu cần deploy mới, yêu cầu Main cung cấp lệnh đúng cho source revision sau review. Việc sửa luồng host Q1–Q4 không tự động đòi deploy engine mới.
- Không retry admission/call ID cũ đang unknown. Namespace mới không phải lý do được gửi trùng một call chưa xác định kết quả.

## 3. Fresh prepare, không gọi inference

```powershell
$cmRun = 'cache/cm4-query-review-v30-ag-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $cmRun --loop-guard-mode warn
if ($LASTEXITCODE -ne 0) { throw 'Prepare failed; do not submit live requests.' }
Write-Output $cmRun
Get-Content (Join-Path $cmRun 'plan.json')
```

Kiểm plan: đúng A discovery được giao, code/root/config binding, search_limit 50, input 8500/output 512, uncapped cumulative, loop guard warn, không max-turn cap. Default A hiện là `021095.txt`; muốn đổi phải chuẩn bị settings riêng và namespace mới, ghi rõ cấu hình. Không sửa plan sau prepare.

`--loop-guard-mode` là CLI mới của Q4; nếu help không có thì checkout chưa đúng phiên bản. Không dùng ngưỡng cực lớn để thay warn mode.

## 4. Chạy live và giám sát

### Quy định chờ GPU — người dùng chốt ngày 20/11/2026

Nếu request đang chờ Modal cấp GPU/worker (`PENDING`, chưa có container/task), **AG phải chờ vô hạn, không tự dừng vì chờ lâu**. Không đặt deadline local, không kill process, tạo STOP, cancel call, redeploy hay chuyển run mới chỉ vì đã chờ nhiều phút/giờ. Không coi chờ scheduler là model lặp/không tiến triển.

- Giữ process/client và request gốc; theo dõi định kỳ bằng log/metadata read-only, tiếp tục cùng call khi có ID. Được chia các lượt giám sát ngắn và ghi checkpoint để tiếp quản, nhưng không kết thúc việc theo dõi chỉ vì hết một timer.
- Không gửi thêm inference/probe, retry hay request embedding mới để thử hàng đợi; tránh tạo thêm công việc trong khi request gốc đang pending. Giữ thời điểm admission, elapsed, call/request IDs và usage unknown cho tới khi có receipt.
- Khi GPU được cấp và request trả kết quả, tự tiếp tục run và review như đã giao, không hỏi lại chỉ vì đã chờ lâu.
- Chỉ dừng theo yêu cầu rõ ràng mới của người dùng hoặc khi có lỗi terminal thực sự từ provider/process; ghi đúng lỗi và trạng thái remote, không giả timeout/hủy thành công. Quy định STOP do model lặp vẫn áp dụng lúc model đang thực hiện lượt, **không áp dụng cho thời gian chờ cấp GPU**.
- Run cũ đã bị kill phải xác định trạng thái call gốc; nếu call vẫn pending thì tiếp tục theo dõi call đó, không tự cancel để mở namespace mới. Chờ vô hạn không cho phép resend một admission chưa xác định kết quả.

Chỉ chạy sau local PASS, prepare ready và người dùng giao pilot:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir $cmRun
```

Ở terminal khác, dùng đúng đường dẫn thực tế vừa prepare:

```powershell
$cmRun = 'cache/REPLACE_WITH_ACTUAL_RUN_DIRECTORY'
Get-Content (Join-Path $cmRun 'trace.jsonl') -Tail 30 -Wait
```

AG theo dõi:

1. Không có search mới trước conclusion query trước.
2. Survey hết cards/trang trước deep raw B; last-page preview/admission chưa có response không tự tính đã giao.
3. Model chọn ưu tiên, đọc raw/đánh giá hoặc giải thích dừng đọc. Không mặc định phải mở raw cả 50 án.
4. Kết luận partial giữ `not_read`/unresolved, không chuyển chúng thành not_supported. Hoãn một án không tự đóng query.
5. Gate có đường tìm mệnh đề không citation và paragraph partial; phần chưa đọc không bị gán screening âm.
   Khi mệnh đề qua hai cửa sổ A đã giao, `read_query_span` cấp lựa chọn ghép liên tục vừa budget. Không nhận offsets tùy ý; vùng dài hơn context không được coi là đã ghép/đọc hết.
6. Warnings không tự kết thúc run ở mode warn. Đọc raw mới liên tục chưa chắc có tiến triển ý nghĩa; AG phải xem mục tiêu đang được giải quyết.
7. V27 khi active query còn mở không được cấp tool thay đổi source gate; `query_gate_paused` phải hiện rõ. `next_unseen`/return results trỏ phần chưa giao, không tự tính cards đang preview là đã nhận. Không cấp lại priority classification không đổi; đổi priority vẫn được nhưng AG phải xem có tiến triển thật không.

Khi thấy lặp không hữu ích, đọc lan không giải quyết nhu cầu hoặc lỗi tool lặp mà model không tự sửa được: ghi lý do và bước quan sát được, rồi STOP. Không dùng một số lượt cố định như chứng cứ duy nhất model mất kiểm soát.

```powershell
New-Item -ItemType File -Path (Join-Path $cmRun 'STOP') -Force
```

STOP được xử lý ở boundary/polling hiện có; không đồng nghĩa provider call đã hủy. Ghi call ID, cancellation/result/usage biết được và unknown riêng. Không xóa STOP hoặc tự resend để làm run trông hoàn tất. Process bị ngắt cần kiểm ledger/admission/receipt trước mọi quyết định resume.

## 5. Evidence trả về

- Commit, settings/plan, run path, lệnh và exit codes.
- Mỗi query: text thật, số hits, phase, survey/raw/assessment counts, priority changes, conclusion và phần còn tồn.
- Log warnings, tool rejections, gate partial/missing context, AG interventions.
- Requests/tokens/latency controller và embedding, cả lỗi/retry; unknown giữ riêng. Không suy usage từ caps.
- Các file thực tế được tạo: plan/preview, trace, result nếu có, session ledger/manifests và embedding/retrieval receipts nếu đã gọi.
- Nhận xét hành vi tách khỏi metric chất lượng; không báo recall/F1 hoặc gold PASS khi chưa có evaluator độc lập.
- Báo cáo review ngữ nghĩa đầy đủ theo mục 6, kèm bảng từng lượt và kết luận mức độ hiểu án; thiếu review này thì chưa hoàn tất nhiệm vụ AG.

Đợt đầu dừng sau một A đã được giao để Main review. Các mốc code Q1–Q4 có thể hoàn tất local, nhưng không thay thế nghiệm thu live và ngữ nghĩa.

## 6. Bắt buộc review ngữ nghĩa toàn bộ các bước model đã dùng

Sau run, kể cả run bị STOP/lỗi, AG phải tái dựng và review **tất cả lượt controller cùng actions/results**, theo thứ tự; không chỉ đọc final prediction, vài bước tiêu biểu hoặc đếm tool calls. Bao gồm navigation, screening âm, query trùng, tool bị từ chối, deferred, sửa đánh giá và conclusion. Mỗi lượt phải có một hàng trong bảng review; nếu gom các lượt giống nhau để giải thích thì vẫn liệt kê đủ IDs và verdict từng lượt.

### 6.1 Căn cứ và cách review

1. AG tự đọc raw A và xác định khung vụ án: ai yêu cầu gì, sự kiện/thủ tục chính, vấn đề pháp lý, lập luận các bên, nhận định và kết quả của tòa. Với án dài, đọc qua nhiều trang; nếu không review đủ toàn A phải kê khai chính xác vùng chưa đọc, không tuyên bố hiểu/độ phủ toàn án.
2. Với từng lượt, mở **exact payload/manifest model được cấp**, raw model reply, action/result và raw liên quan. Phân biệt dữ liệu model thực sự đã thấy với phần chỉ fetched hoặc phần AG đọc thêm sau run. Không dùng kiến thức ở lượt sau để quy cho model tại lượt trước.
3. Đối chiếu hành động/lý do/kết luận model với nguyên văn. Khi nghi thiếu quotation, attribution, ngoại lệ hoặc đầu/cuối mệnh đề, AG đọc thêm ngữ cảnh nguồn để kiểm và ghi rõ đó là ngữ cảnh bổ sung của reviewer.
4. Dùng hành vi và lý do model đã ghi để đánh giá; không suy đoán suy nghĩ ẩn hoặc yêu cầu dựng lại chain-of-thought. Nếu không có đủ dấu vết để biết model hiểu vì sao, ghi `không đủ bằng chứng`, không tự điền lời giải thích hộ model.
5. Review là đánh giá độc lập của AG, không phải gold COLIEE. Không đưa kết luận reviewer, nguồn AG tìm thêm hay gold vào solver trong run đang đánh giá; nếu can thiệp thì phải ghi thời điểm/nội dung và tách phần run sau can thiệp.

Phân biệt chính xác record với coverage: thêm một negative phủ paragraph có thể che nhu cầu chưa xét dù positive/search record cũ vẫn còn; chỉ gọi “ghi đè/xóa” khi ledger chứng minh điều đó. `signal_ref == proposition_ref` không tự là lỗi: cùng một câu có thể vừa chứa mệnh đề vừa nêu nguồn; phải kiểm nội dung. Vùng chưa xét tại STOP không mặc định là bỏ sót vĩnh viễn. Lặp tool và mất mục tiêu là evidence về điều hướng/tuân thủ, chưa tự chứng minh model hiểu sai quy tắc pháp lý; tách đóng góp của catalog/guidance host khỏi hành vi model.

### 6.2 Những câu hỏi phải trả lời theo từng loại bước

| Bước | AG phải kiểm về ngữ nghĩa |
|---|---|
| Bản đồ/đọc A | Model chọn vùng có liên quan tới nhu cầu đang xét không? Có bỏ qua vùng hoặc mất ngữ cảnh khiến hiểu sai không? Đọc thêm có giải quyết khoảng thiếu cụ thể không? |
| `assess_source_need` | Model nhận đúng mệnh đề cần nguồn, hay chỉ thấy từ khóa? Có bỏ sót nhu cầu vì thiếu citation? `no_search_needed` có căn cứ trong phạm vi đã đọc? Một paragraph có nhiều nhu cầu bị bỏ phần nào? |
| Chủ thể/quotation | Phân biệt lời tòa, đương sự, tòa dưới và án được trích; có nhầm câu trích thành nhận định được tòa hiện tại chấp nhận, mất phủ định/điều kiện/ngoại lệ hoặc hiểu sai nội dung song ngữ không? |
| Tạo query | `issue` thực sự gửi tìm có bám mệnh đề A, đủ cụ thể và giữ thuật ngữ phân biệt không? Có lệch sang sự kiện/chủ đề rộng, gộp nhu cầu hoặc thêm nội dung không có căn cứ? Đối chiếu cả source_proposition, không coi field debug là query đã gửi. |
| Survey/priority | Model ưu tiên theo nội dung liên quan đến mệnh đề hay chỉ rank/tên án? Lý do chọn/bỏ có phù hợp preview? Có bỏ qua lead đáng đọc trong các trang sau? Không dùng preview để chứng nhận quan hệ A→B. |
| Đọc B/header/context | Vùng đọc có giúp xác minh nguồn/identity/quan hệ đang tìm? Model có nhận ra đang đọc lời B trích án C, hoặc A và B cùng nhắc C? Đọc thêm có ích hay lặp không làm rõ gì? |
| Assessment | Bằng chứng có chứng minh A viện dẫn/dựa vào đúng B, hay chỉ tương đồng quy tắc/sự kiện? Identity, attribution, vị trí và lý do có khớp raw? Unknown có được giữ khi thiếu chứng cứ? |
| Chuyển focus/reload/repair/defer | Model có giữ đúng nhu cầu và đúng cặp A–B, sửa được lỗi trước không? Việc đổi hướng có mục đích? Hoãn có lý do thật hay dùng để né phần khó? |
| Kết luận query/án A | Kết luận có tương xứng với evidence đã đọc? Phần chưa đọc/unknown có được công khai? Có dừng đọc quá sớm dù còn leads tốt, hoặc khẳng định vượt phạm vi retrieval/corpus không? |

AG cần kiểm cả **những cơ hội model bỏ qua**: vùng A bị screening âm, cards bị hạ ưu tiên và án chưa mở raw. Liệt kê đầy đủ IDs/disposition; nếu đánh giá một lead có thể quan trọng thì đọc raw liên quan để xác minh nhận xét đó. Không bắt AG đọc toàn văn cả 50 B khi không cần, nhưng phải khai phạm vi raw B reviewer đã kiểm. Nếu chỉ đủ kiểm preview, ghi rõ chưa thể kết luận quan hệ nguồn của B đó.

### 6.3 Bảng review bắt buộc

Lưu `semantic_steps.md` và `semantic_review.md` trong run directory, bổ sung mới, không sửa ledger/manifests/receipts. Không dùng lại báo cáo của run khác.

Mỗi hàng `semantic_steps.md` có:

| Trường | Nội dung |
|---|---|
| Turn / request / action / event IDs | Ref để đối chiếu chính xác thứ tự và evidence |
| Query/need/candidate và tool | Nhu cầu đang xử lý, bước model thực hiện |
| Evidence model được cấp | Source refs, byte spans và đoạn nguyên văn ngắn đủ kiểm tra; dẫn manifest/raw, không chỉ screenshot/log tóm tắt |
| Ý hiểu hoặc quyết định quan sát được | Dẫn action/reason thực tế của model; phần không quan sát được giữ unknown |
| Verdict | `có căn cứ`, `có phần đúng nhưng thiếu`, `sai ngữ nghĩa`, `không đủ bằng chứng`, hoặc `thao tác kỹ thuật` |
| Giải thích của AG | Vì sao verdict đó đúng theo raw; nếu lỗi thì mệnh đề/chủ thể/quan hệ nào bị hiểu sai |
| Tác động và ngữ cảnh bổ sung | Có làm mất nhu cầu, query lệch, bỏ lead, assessment sai hoặc kết luận sớm không? AG đã đọc thêm phần nào ngoài payload? |

Verdict `thao tác kỹ thuật` vẫn cần kiểm tool có phục vụ mục tiêu hiện tại không; không dùng nó để bỏ qua navigation/reload. Báo tổng số lượt trong ledger, số lượt đã review và danh sách thiếu; không ghi “review toàn bộ” khi denominator chưa đủ. Provider unknown/không có reply phải ghi đúng thiếu dữ liệu, không chấm khả năng hiểu cho nội dung chưa có.

### 6.4 Kết luận mức độ hiểu án

Trong `semantic_review.md`, tổng hợp riêng:

- Hiểu cấu trúc vụ án và phân biệt vấn đề pháp lý với sự kiện/thủ tục.
- Nhận diện nhu cầu nguồn và tạo query bám mệnh đề.
- Theo dõi chủ thể phát biểu, quotation, ngoại lệ/điều kiện và song ngữ khi có.
- Hiểu identity và quan hệ A→B, phân biệt tương đồng với việc viện dẫn/dựa vào.
- Duy trì mục tiêu qua nhiều lượt, chọn vùng đọc hữu ích, tự sửa sai và giữ uncertainty.

Với mỗi mặt, chọn `có bằng chứng hiểu đúng`, `hiểu một phần`, `có bằng chứng hiểu sai` hoặc `chưa đủ bằng chứng`; dẫn turn IDs minh họa cả điểm đúng lẫn sai. Không suy “hiểu án tốt” từ số lượt đọc, schema PASS hoặc một candidate tìm đúng tình cờ. Kết luận chỉ áp dụng án A và run đã review, không khái quát thành năng lực toàn bộ COLIEE.

Cuối báo cáo phải nêu lỗi sớm nhất làm lệch luồng, model có tự phục hồi không, phần hiểu sai còn ở kết luận cuối, và ưu tiên sửa. Tách các nguồn lỗi: hiểu A/gate, diễn đạt query, retrieval backend, điều hướng/context, hiểu B/assessment, conclusion, hoặc chưa xác định. Nếu nhãn chuẩn/evaluator chưa được giao, không suy recall/F1 hay bịa gold để hoàn thành báo cáo.
