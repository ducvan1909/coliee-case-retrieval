# Tiếp tục tối ưu retrieval trên máy còn lại

## Checkpoint bàn giao đầy đủ — 23/11/2026, thay đổi kể từ lần pull gần nhất

### 1. Mốc so sánh và cách đọc tài liệu

- Checkout: `G:/Git/coliee-case-retrieval`, nhánh `main`. Reflog xác nhận lần pull gần nhất là `pull --ff-only` lúc **20/11/2026 20:00:43 +07:00**, từ `7c230e5` lên **`dce7163`**. Phạm vi checkpoint này là diff working tree và code/tests/plan mới so với `dce7163`, không lấy `7c230e5` làm base cho toàn đợt mới.
- Ngày 23/11 đã fetch `origin`; trước commit bàn giao, `HEAD...origin/main` là `0 / 0`. Những sửa được bàn giao là phần chưa commit trên máy này sau pull. Đây là phạm vi Git; không suy ra mọi artifact untracked đều được tạo sau pull.
- Mục này là checkpoint hiện hành. Các phần v28/v27/v26 bên dưới là lịch sử. Bản hiện có trong source là engine **`cm4-query-review-v31`**, live **`cm4-live-v3`**, source gate **`cm4-source-gate-v5`**, source-bound **`cm4-source-bound-v2`**, passage review **`cm4-passage-review-v4`**. Không dùng số v30/v2 hoặc output 512 trong hướng dẫn cũ làm cấu hình chạy mới.
- Tài liệu liên quan: [PROGRESS](PROGRESS.md), [source-bound/survey-first](plan/CM4_SOURCE_BOUND_SEARCH_IDENTITY.md), [phục hồi span](plan/CM4_SOURCE_SPAN_LOOP_RECOVERY.md), [dual-query/rerank và lịch sử thay đổi contract](plan/CM4_DUAL_QUERY_RRF_RERANK.md). Checkpoint này tổng hợp trạng thái code; PROGRESS giữ các mốc kiểm/pilot riêng.

### 2. Luồng mới so với bản vừa pull

| Khâu | Thay đổi và hành vi hiện có |
|---|---|
| Đọc A | Profile `--survey-first` khảo sát A trước khi cấp quyền tìm. Khi bước điều hướng xác định được, host cấp thẳng nguyên văn vùng A kế tiếp vừa context, thay vì buộc model gọi thêm một action mở vùng. Admission lưu lựa chọn để replay cùng vùng. |
| Quyết định nguồn | Model đánh giá span được cấp, dùng ref hoặc quote nguyên văn. `search_needed` và `no_search_needed` đều cần selector; không đóng cả paragraph chỉ vì một mệnh đề đã được xử lý. `need_more_context` giữ phần còn việc. |
| Gom nguồn | Nhận tối đa ba quyết định trong một batch. Host tự gom theo citation khóa khớp hoặc theo liên kết cùng quyết định được model xác nhận; không tự gộp mọi mệnh đề cùng chủ đề. Các khối trích độc lập giữ citation scoped. |
| Truy vấn | Có cả code hai nhánh issue/verbatim và profile khóa nguồn mới. **Source-bound hiện chạy một nhánh `source`**, dựng từ mệnh đề nguyên văn và citation/group member được phép, không nhân đôi RRF. |
| Rerank | Lấy passage lead từ pool án hybrid, kiểm raw/hash/span, chấm Qwen theo cặp A × passage B, giữ 10 passage rồi mới gom theo B. Top 10 không đảm bảo 10 án khác nhau. |
| Đọc B | Mở trực tiếp từ card, cấp phần mở đầu và passage trong ngân sách; model quyết định đọc thêm hoặc rời/mở lại. Có các đường đọc định danh, attribution, citation context và continuation. |
| Chọn B | Model yêu cầu kiểm định danh trước select. Lượt cuối chỉ trả nhãn định danh; host ánh xạ và commit một lần cho `(search_query_id, B)`, rồi tự hiện lại trang ứng viên. `not_select` khi chưa chốt vẫn là pending. |
| Kết thúc | Card đã giao, raw đã đọc, pending và kết luận được theo dõi riêng. Phải giao các trang card còn lại trước khi đóng search; B chưa mở/giải quyết vẫn có thể giữ pending và query báo partial. Chưa có prediction cuối không được báo F1. |

### 3. Thay đổi retrieval và dịch vụ reranker

- `dual_search.py` bổ sung hợp case bằng RRF trên hai góc nhìn issue/verbatim; khi text trùng, tái dùng nhánh issue và không cộng hai lần cùng danh sách. Nhánh source-bound kiểm `source_query_text` và SHA-256, so lại nguyên văn A và các support; chỉ gửi truy vấn đã khóa.
- Pool rerank mặc định tối đa 50 án. Lead của cùng passage được khử trùng bằng case/hash/span và giữ origins của kênh/nhánh. Án thiếu passage lead có fallback tìm lexical trong chính B, tối đa hai hit từ runtime; trường hợp vẫn thiếu lead được ghi riêng.
- Trước chấm kiểm hash và giới hạn byte của từng nguồn, không dựng passage giả. Score phải hữu hạn và đủ số cặp. Xếp theo score, phá hòa bằng hạng case RRF và ref ổn định; cắt 10 hit rồi mới gom. Không kéo thêm passage của cùng B từ ngoài 10 hit đó.
- `reranker_protocol.py` pin `Qwen/Qwen3-Reranker-0.6B`, revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`, `MAX_TOKENS=8192`, batch 8, app `coliee-cm4-qwen3-reranker-l4`. Worker mới ở `pipeline_v2/deployments/modal_cm4_reranker/app.py`, dùng L4 và trả scores/token receipt.
- `reranker_modal.py` pin function ID từ prepare; fingerprint gồm model/revision/instruction/giới hạn/function ID/query/documents. Ghi admission, submission/call ID, result hoặc failure theo batch. Có result hợp lệ thì tái dùng; admission thiếu usable receipt thì chặn gửi lại tự động.
- Client kiểm request ID/model/revision/GPU L4/số score/token. Usage báo admitted/completed/failed/unaccounted, known input/padded/output tokens và thời gian quan sát cả failure. Khoản thiếu receipt không được xem là usage bằng 0.
- Điểm, hạng và nhãn top-k ở diagnostics host; payload model giữ ref/nguyên văn/tiến độ, không dùng thứ hạng làm bằng chứng viện dẫn.

### 4. Khóa span A, phục hồi lỗi và độ phủ

- `source_gate.py` thêm variants schema theo ref hoặc quote; so quote với nguồn, giữ UTF-8 byte spans, source/text hashes và vai trò support. Permit chỉ cấp quyền chạy nguồn đã duyệt; model có thể bổ sung/sửa ngữ cảnh được phép trước search.
- `remaining_visible` biểu diễn đúng hợp các khoảng chưa xét. Với đoạn có các mục đầu dòng `(a)`, `(b)`, không cấp ref gộp khiến một quyết định vô tình đóng nhiều căn cứ; `[1]` của `021095.txt` vẫn có ref gộp khi phù hợp.
- Quote không khớp được đưa về lựa chọn ref nguyên văn để xác nhận, không ghi coverage dựa trên một phần JSON sai hoặc câu gần giống chưa được xác nhận. Thiếu selector là schema reject; host cấp một lần sửa cùng scope rồi dừng nếu lỗi lặp lại.
- LoopGuard dùng hợp byte đã có quyết định, không dùng đổi lời/đổi focus/lặp cùng byte làm tiến triển. Replay khôi phục tiến độ từ ledger. Raw mới được cấp cũng chưa tự thành screened.
- Sửa crash sau `search → conclude_search_query → prepare`: source need lấy đủ `a_paragraph` metadata từ permit để quay lại A.
- Sửa vòng lặp bản đồ: khi còn vùng con chứa byte chưa xét, lọc lối lên khỏi catalog và schema; khi không còn đường xuống phù hợp thì cấp lại lối lên.
- Batch survey nhận một tới ba span phân biệt, không chồng lấn. Chỉ khi có receipt Modal `finish_reason=length` đã xác thực và chưa có action được thực thi mới giảm batch **3 → 2 → 1**, giữ queue/coverage và hạch toán request lỗi. Đây không phải quyền suy diễn hành động từ JSON bị cắt.
- Auto navigation chọn vùng chưa xét theo cây nguồn và cap, lưu ở admission và dùng lại khi replay. Model vẫn quyết định ý nghĩa pháp lý và cách xử lý khi chưa đủ ngữ cảnh; host chỉ quyết định bước mở nguồn xác định được.

### 5. Passage review và định danh B

- Module mới `passage_review.py` gom hit theo án sau cutoff, hợp các vùng chồng lấn cùng nguồn, giữ thứ tự byte và continuation. Có `return_to_candidates`, mở lại, tìm lexical trong B và `revisit_case_passage` cho đoạn cũ có chủ đích.
- Tìm trong B phân biệt `new_content`, `already_read`, `no_hits` bằng span/hash/receipt; phần mới sau prefix đã đọc được mở từ gap mới đầu tiên. Đổi focus không tự tăng coverage.
- `read_passage_attribution` mở khoảng trước/sau ±1.200 byte để model đọc câu dẫn; nhãn này không có nghĩa host đã nhận diện người nói hoặc biên quotation đúng ngữ nghĩa.
- Mở B cấp tối đa 900 byte đầu làm ngữ cảnh định danh, kèm dấu hiệu metadata nếu có. Đã bổ sung trường hợp phần mở đầu nêu Prothonotary. Tự định danh B phải tách khỏi đoạn thân B đang trích án X.
- Trước select, `request_identity_check` dùng ref A, ref tự định danh B và ref quy tắc B đã được cấp. Lượt cuối chỉ kết luận danh tính. Host xác minh quyền dùng ref/provenance và commit đúng một lần; không lấy việc byte/hash đúng làm chứng nhận A viện dẫn B.
- Sửa lỗi cùng span B `[0,900)` có nhãn provenance khác nhau bị xem là evidence trùng không hợp lệ khi commit. Regression đã mở rộng đến việc ghi kết luận thực, không dừng ở bước tạo schema.
- Kết luận select/not_select bất biến trong từng search, kể cả resume. Vẫn được đọc tiếp hoặc mở lại sau chốt; không được đổi/thu hồi. Âm ở search khác không xóa dương đã khóa. Pending không tạo assessment phủ định giả.
- Bỏ `uniqueItems` khỏi mảng ref gửi backend xgrammar vì backend pilot từ chối keyword; kiểm trùng và quyền ref vẫn ở host. Không đánh đồng schema được host chấp nhận với biên dịch trực tiếp bằng xgrammar.
- `citation_lookup.py` bổ sung đường chốt trực tiếp rất hẹp khi citation A khóa khớp tự định danh của đúng một B và provenance kiểm lại được. Quét corpus 7.708 file được ghi trong PROGRESS chưa thấy header đạt quy tắc hẹp. Fixture xác nhận wiring; chưa có bằng chứng đường này hữu ích trên corpus hiện tại.

### 6. Transport, cap, projection và timing

- Controller function pin trong source đổi từ `fu-TfWPSIRNQIkZWM1W5O7HEv` sang **`fu-EebPFmRFbonO5T97FTMSH4`**. Đây là pin code đã kiểm; phiên này không gọi Modal để xác minh trạng thái deployment hiện tại.
- Output cap tăng **512 → 1.024** trong worker và `CONTROLLER_OUTPUT_TOKEN_CAP`; replay CLI bỏ hardcode 512. Input cap 8.500, context worker 12.288; 1.536 mới là tùy chọn thí nghiệm trong tài liệu, chưa được áp dụng.
- `_wait_for_result` nhận nhãn component để dùng chung controller/reranker. Giữ poll cùng call, không đặt host deadline cố định cho pending GPU, không tự gửi request mới vì chờ lâu.
- `model_view.py` giữ `proposition_quote` là literal, giữ span byte của source gate và source label của excerpt khi compact payload. Ref alias dùng trên wire; nguồn/hash/offset canonical vẫn giữ ở host.
- `runtime_timing.py` mới cung cấp đo thời gian phân cấp theo context, inclusive/exclusive, phần chưa đo, số calls/samples, total, p50/p95/max và request chậm nhất. Tắt timing là mặc định.
- Instrument `ledger.py`, `m6_hybrid.py`, engine/live và dual retrieval: đọc/replay/append ledger, khóa writer, mở tokenizer/source/index, đếm token, dựng payload, serialize, chờ transport, kiểm receipt, execute, embedding, lexical/dense/fusion, diagnostic, rerank, inspection và ghi result. Không suy nguyên nhân latency live chỉ từ preflight ít mẫu.
- Live CLI thêm `--reranker-function-id`, `--survey-first`, `--profile-timing` khi **prepare**. Survey-first yêu cầu reranker. Các cờ lưu trong plan/binding; lúc run chỉ dùng namespace đã prepare, CLI từ chối truyền lại các cờ cấu hình này.

### 7. Bằng chứng lịch sử sau pull và giới hạn

Các số sau được đối chiếu với PROGRESS/tài liệu đã có; phiên push này không chạy lại inference và không chuyển các namespace cache:

| Mốc/artifact local | Kết quả đã ghi và cách hiểu |
|---|---|
| `cm4-dual-query-20261121-082213228` | Dừng T41 trong vòng lặp priority; không chứng minh contract passage review mới đạt. |
| `cm4-final-once-20261121-160727278` | Dừng T030 do xgrammar không nhận `uniqueItems`; đã sửa schema và kiểm host local, không sửa receipts cũ. |
| `cm4-source-span-recovery-ready-20261122-094355232` | 27 reply hợp lệ; sau chốt search crash dựng T028 vì thiếu paragraph metadata. `070847.txt` vào shortlist nhưng chưa mở. Bản sửa có replay local. |
| `cm4-source-span-page-check-20261122-111459932` | 59 request/58 action; quay về A hai lần. Model vẫn phân loại căn cứ [2](a)/(b) thành facts; `070847.txt` được mở nhưng không chọn. Chưa có prediction cuối. |
| `cm4-identity-first-ag-20261122-165805297` | T033 yêu cầu identity check, T034 model trả select nhưng host chưa commit do ref trùng provenance; STOP sau 38 request. |
| `cm4-identity-commit-fix-ag-20261122-181709912` | T035 ghi `070847.txt = select`; sau đó dừng vì lặp bản đồ A. Một select là kết luận model, không phải gold acceptance hay F1. |
| `cm4-survey-first-local-20261123-115942490` | Preflight 3.270 input token, 0 controller/embedding/reranker requests. Ba mẫu mỗi chế độ: trung vị 4,42 giây tắt timing, 4,56 giây bật timing; chỉ là preflight. |
| `cm4-auto-survey-nav-local-20261123-151440587` | Preflight mở A `[0,929)`, 6.546 input token, 0 inference. Replay quyết định [1] rồi nhận `[929,2551)`; vừa nhận vùng mới chưa tăng screened coverage. |

Đợt cuối trước push chạy lại kiểm local; kết quả và lệnh chính xác bổ sung ở mục 10 bên dưới. Các con số test cũ 152/158/163/171/194 trong PROGRESS thuộc từng revision, không tự thay cho kiểm hiện tại. Chưa có final prediction/gold evaluator mới; chưa kết luận micro P/R/F1, recall tốt hơn hoặc tiết kiệm token live. Chi phí pilot lỗi/retry giữ nguyên trong receipts nguồn; không gộp preflight 0 request thành chi phí của cả đợt.

### 8. Danh mục file chuyển sang máy tiếp theo

Đường dẫn dưới đây tính từ root repo. Ngoài hai file bàn giao, giữ toàn bộ code/tests/docs hiện có trong diff và các module mới cần import:

| Nhóm | File |
|---|---|
| Bàn giao/trạng thái | `CODEX_HANDOFF.md`; `pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md`; `pipeline_v2/docs/PROGRESS.md`; `pipeline_v2/experiments/context_manager_v2/CM4.md` |
| Kế hoạch mới | `pipeline_v2/docs/plan/CM4_DUAL_QUERY_RRF_RERANK.md`; `CM4_SOURCE_BOUND_SEARCH_IDENTITY.md`; `CM4_SOURCE_SPAN_LOOP_RECOVERY.md` trong cùng thư mục |
| Shared runtime/worker | `pipeline_v2/runtime_timing.py`; `pipeline_v2/agent_harness/ledger.py`; `pipeline_v2/agent_harness/modal_qwen.py`; `pipeline_v2/m6_hybrid.py`; `pipeline_v2/deployments/modal_qwen36_27b/app.py`; `pipeline_v2/deployments/modal_cm4_reranker/app.py` |
| CM4 sửa | `cli.py`, `engine.py`, `evidence.py`, `live.py`, `model_view.py`, `query_options.py`, `query_review.py`, `source_gate.py`, `tool_repair.py` trong `pipeline_v2/experiments/context_manager_v2/` |
| CM4 mới | `citation_lookup.py`, `dual_search.py`, `passage_review.py`, `reranker_modal.py`, `reranker_protocol.py` trong cùng module |
| Tests CM4 | Sửa `test_live.py`, `test_map_first.py`; thêm `test_citation_lookup.py`, `test_dual_search.py`, `test_passage_review.py`, `test_source_span_loop_recovery.py`, `test_survey_auto_navigation.py`, `test_survey_first.py` trong `pipeline_v2/experiments/context_manager_v2/tests/` |
| Tests shared | `pipeline_v2/tests/test_m4_modal_qwen.py`; `pipeline_v2/tests/test_runtime_timing.py` |

Không stage đại trà toàn bộ untracked. Giữ local các `knowledge_base/**/outputs`, `pipeline_v2/reviews/` run receipts/log/fixtures sinh ra, `cache`, `MagicMock/`, `tmp-test-not-created/`, `pools.json`, `retrieval_fixtures.json` và `__pycache__`. Chúng không bị xóa và không được mô tả như artifact đã chuyển qua Git. Tài liệu vẫn giữ tên namespace để máy có dữ liệu cũ tìm lại; máy mới không có các thư mục đó phải báo rõ thiếu evidence lịch sử. Không đưa `.env`/credential lên commit.

### 9. Tiếp quản và thao tác được phép

1. Đọc checkpoint này rồi PROGRESS và ba plan mới. Xác nhận commit đã pull, working tree và code binding trước thao tác; giữ thay đổi độc lập của máy đích.
2. Chạy lại suite phù hợp bằng `.venv/Scripts/python.exe`. Dùng raw corpus/index/tokenizer đã có hoặc khôi phục đúng binding; không embed lại corpus chỉ vì đổi máy.
3. Prepare **namespace mới** cho engine/live v31/v3, đặc biệt khi thay source/settings/root/prompt/function pin. Không resume plan v30/v2 hoặc namespace STOP bằng binding mới.
4. Cấu hình thử survey-first bằng `--reranker-function-id <function-id đã được AG xác minh> --survey-first`; thêm `--profile-timing` tại prepare nếu cần đo. Dùng `python -m pipeline_v2.experiments.context_manager_v2.live --help` để lấy CLI hiện có. Lệnh run dùng đúng `--run-dir`, không lặp các cờ prepare.
5. Codex chỉ chuẩn bị code/lệnh và kiểm local. Người dùng/AG thực hiện inference/deploy. Phiên bàn giao này không cấp authorization mới cho Codex gọi Modal.
6. Khi AG chạy, kiểm model tự khảo sát đủ A, không mất căn cứ riêng trong paragraph, gom đúng nguồn, quay về A sau search, giữ pending và commit identity đúng một lần. Đo request/token/latency cả lỗi/retry; so recall và identity với baseline và gold tách ở evaluator trước tuyên bố chất lượng.
7. Pending GPU phải theo dõi cùng call, không tự kill/redeploy/probe/retry vì chờ lâu. Admission unknown phải kiểm receipts/call gốc trước. Run terminal hoặc operator STOP không được ghi là complete prediction.

### 10. Kiểm tại thời điểm đóng gói 23/11/2026

- `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests`: **197/197 PASS**, 146,358 giây.
- `.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_runtime_timing pipeline_v2.tests.test_m4_modal_qwen pipeline_v2.tests.test_m6_hybrid`: **23/23 PASS**, 0,859 giây.
- Tổng hai nhóm: **220 test PASS** trên code đóng gói. Chạy suite local, không inference/deploy Modal. Không chạy full repository/M6 end-to-end hoặc evaluator gold trong phiên push này.
- Whitespace diff PASS với `git -c safe.directory=G:/Git/coliee-case-retrieval -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`. Cấu hình `cr-at-eol` nhận diện CRLF Windows; lệnh mặc định báo CR cuối dòng là whitespace, không phải lỗi logic.
- Sau fetch, remote khớp base. Commit bàn giao sẽ bao gồm code/tests/plans trong mục 8 và hai file bàn giao; kiểm SHA remote sau push. Hash commit cuối xem `git log -1` (không chèn hash tự tham chiếu vào chính commit).
- Giới hạn kiểm: test fixture/replay xác minh contract, nguồn và trạng thái; không xác nhận model live tự khảo sát/gom nguồn đúng, danh tính mọi B, recall, chi phí toàn run hoặc F1.


## Checkpoint hiện hành — 20/11/2026

CM4 hiện `cm4-query-review-v28` / `cm4-live-v2`, gate v4. Xem [bảng thay đổi pipeline](PROGRESS.md) và [pilot v27 / kiểm v28](../reviews/cm4_survey_focus_fix_v1/PILOT_20261120.md). Prepare namespace v28 mới theo [AG_CHECK](../reviews/cm4_query_review_v24/AG_CHECK.md); chưa có nghiệm thu live/semantic v28. Controller pin hiện `fu-TfWPSIRNQIkZWM1W5O7HEv`. Giữ request gốc khi chờ GPU theo chỉ đạo mới; Codex không tự inference/deploy. Các chỉ dẫn v27 trở về trước dưới đây là checkpoint lịch sử.

## Checkpoint bàn giao mới — 19/11/2026

**V27 hiện tại:** [REPORT focus/survey và lệnh AG](../reviews/cm4_survey_focus_fix_v1/REPORT.md). Active query không cấp gate mutations nhưng vẫn đọc được A; next-unseen/progress tách cards đã giao và preview, priority không đổi không được cấp. Bảo toàn coverage nhiều nhu cầu/paragraph. Fresh namespace v27, không resume v26 STOP. Các checkpoint v26 trở về trước dưới đây là lịch sử.

**Phiên bản hiện tại v26:** sau pilot v25, sửa blocker map sau search; xem [REPORT và lệnh AG](../reviews/cm4_map_projection_fix_v1/REPORT.md). Không dựng bản đồ A ở results mode; đếm cap map theo projection CM4, không tăng ngân sách. Run cũ 4 lượt thành công, chưa tới survey/B/assessment, giữ nguyên receipts. Prepare namespace v26 mới theo hướng dẫn, không resume v25.

**Hướng dẫn dùng hiện tại:** cleanup engine `cm4-query-review-v25`, gate v4; các nhãn gate và tool anchor/citation cũ không còn trong API CM4. Đọc [CM4](../experiments/context_manager_v2/CM4.md), [luồng tools](../experiments/context_manager_v2/MODEL_CONTEXT_FLOW.md), [cleanup](../reviews/cm4_query_review_v24/CLEANUP.md) và [AG_CHECK](../reviews/cm4_query_review_v24/AG_CHECK.md). Các đoạn v24/v23 và lệnh run lịch sử dưới đây không dùng để resume với code v25. Luôn prepare namespace mới.

### Q1–Q4 sau review — CM4 query review v24

Người dùng đã yêu cầu triển khai đủ [kế hoạch Q1–Q4](plan/CM4_QUERY_REVIEW_PLAN_20261119.md). Bản mới khóa một **search query** đến explicit conclusion, survey toàn bộ hits trước đọc sâu B, giữ counters/unread/unresolved, nới source gate cho mệnh đề không citation và partial span, loop guard mặc định warn để AG giám sát. Xem [REPORT](../reviews/cm4_query_review_v24/REPORT.md) cho nghiệm thu local và [AG_CHECK](../reviews/cm4_query_review_v24/AG_CHECK.md) cho lệnh chạy thật. Không diễn giải plan hoặc test protocol thành live/semantic PASS.

Engine `cm4-query-review-v24`, live CLI `cm4-live-v2`; code/settings/root binding đổi nên phải prepare namespace mới. Không cần run/evidence cũ để chạy mới. Người dùng/AG chạy Modal, Codex chỉ code/local. Báo kết quả dừng partial cả STOP và các non-complete terminal stops; không chỉ lỗi. Các mục a398de0/7c230e5/v23 bên dưới giữ làm lịch sử.

**Đọc mục này trước các mục ngày 14/11 phía dưới.** Đây là checkpoint chuyển tiếp công việc đang làm, chưa phải nghiệm thu selector, CM4 live hoặc chất lượng COLIEE. Base trước commit bàn giao: `19283dc`, nhánh `main`. Ngày 19/11 đã fetch và xác nhận base local/remote khớp. Không ghi đè các sửa độc lập trên máy đích.

### Bổ sung sau commit a398de0 — 19/11/2026

CM4 thêm `report_review_blocker(kind, reason)` để ghi vướng mắc theo scope cặp/vùng và trả hướng recovery/navigation đang thực sự được cấp. Khi review chưa xong, schema không cấp `finish_case_review`; khi đã đủ điều kiện, chỉ cho `complete_policy`. Báo blocker giữ review mở và không được báo lại cùng kind trong cùng scope. Nếu host dừng lỗi, `inspect()` trả `partial_supported_cases` riêng; đây không phải final prediction. Prompt live đã đổi theo hợp đồng này; test mới ở `experiments/context_manager_v2/tests/test_review_blocker.py`. Code binding thay đổi: prepare namespace mới, không resume plan của a398de0. Kiểm local bản bổ sung: suite context_manager_v2 đạt 112 tests PASS trong 67,334 giây; chưa chạy inference/deploy mới.

### Code đi cùng lần push này

- `agent_harness/selection.py`, `ledger.py`, `harness.py`, `m6.py`, `m6_live.py`: nối selector vào M6 live; tổng hợp assessment theo candidate; kiểm assessment còn active, không pending, evidence đã giao và khớp catalog/hash/source trước khi chốt prediction, kể cả khi raw đã rời payload. Selector mặc định yêu cầu citation A khớp identifier quan sát được trong header B. Đây là heuristic bảo thủ, không phải gold hoặc bộ nhận diện mọi loại citation.
- `adaptive_policy.py`, `m6.py`: tùy chọn `explicit_leads`, tool `open_retrieved_passage` mở đúng lead đang hiển thị và đúng source need. `read_case_passages` dùng focus cho tìm nội bộ khi bật chế độ này. Lead thường giữ handle đầu tiên thay vì âm thầm ghi đè bằng hit sau.
- `m6_hybrid.py`: M6 cho phép output đến 50 cases, tái tính cùng case-rank RRF từ channels hiện có khi yêu cầu hơn 20; không thêm lượt backend/embedding để mở rộng output. Default M6 config và mặc định CM4 khác nhau: CM4 không truyền settings riêng thì dùng search limit 50; settings truyền rõ vẫn được giữ.
- `assessment.py`: từ chối evidence A/B chỉ có whitespace; bổ sung mode `model_attribution` dùng trong thử nghiệm. `evidence.py`: chuẩn hóa tuple khi sort spans hỗn hợp list/tuple.
- `modal_qwen.py`: function pin local đang là `fu-JifUyUWll3lk5ctQEedpCW`. Pin này được chuyển nguyên trạng, **chưa xác minh deployment hiện tại trong đợt bàn giao**. Máy đích kiểm metadata trước inference, giữ function-ID guard.
- Chuyển toàn bộ source, tests, settings và tài liệu trong `experiments/uncapped_probe/`, `experiments/context_manager_v1/`, `experiments/context_manager_v2/`. Không chuyển bytecode hoặc run/cache. CM4 hiện là `cm4-anchor-flow-v23`; đọc `experiments/context_manager_v2/CM4.md`, `MODEL_CONTEXT_FLOW.md` và code hiện tại. Các tài liệu v1–v22 là checkpoint lịch sử, không phải chỉ dẫn resume run cũ với code v23.

### Trạng thái CM4 và khác biệt với M6 thường

CM4 nối source gate, đọc toàn query nếu vừa payload (không vừa thì điều hướng vùng), model view dùng mã ngắn, đọc lead/continuation theo cặp need–candidate, phản hồi pending và tool repair, search reuse, draft `issue/source_proposition/anchor_quote` có đường sửa hoặc xác nhận nguyên văn. Anchor khớp duy nhất được ánh xạ về raw offsets; trường hợp nhiều vị trí hoặc gần giống trả các đoạn nguyên văn để xác nhận trước retrieval. Chỉ `issue` đi vào retrieval; `source_proposition` là model annotation.

CM4 bật `model_attribution=True` và `model_support=True`: attribution/identity support dựa đánh giá model trên evidence; host vẫn kiểm refs, raw và phía A/B. Vì vậy không được mô tả CM4 là đã qua cùng heuristic citation/header của selector M6 mặc định. `supported`/`accepted` trong ledger không chứng minh nhãn COLIEE đúng.

Theo các tài liệu thử nghiệm, người dùng trước đó đã cho phép nhánh uncapped/RT4/RT5 và nối CM4; điều đó không nghiệm thu các gate RT3/context còn ghi ở dưới. Lần bàn giao này chỉ kiểm local và chuyển code, không inference/deploy. CM4 giữ cap mỗi lượt input 8.500/output 512; cumulative caps mặc định rất lớn (`2**60`), có loop guard, STOP và tùy chọn max-turns. Không xem profile này là pilot ngân sách nhỏ. `live.py` CM4 không nhận profile RT5 bounded.

### Kiểm lại ngày 19/11 và lỗi còn lại

Các lệnh đều dùng `.venv/Scripts/python.exe`; các lượt kiểm là local/offline, không chủ động chạy inference/deploy hoặc embedding mới.

- `-m unittest pipeline_v2.tests.test_source_selection pipeline_v2.tests.test_m6_hybrid -q`: **14 tests PASS**.
- `-m unittest discover -s pipeline_v2/experiments/context_manager_v1/tests -p 'test_*.py' -q`: **19 tests PASS**.
- `-m unittest discover -s pipeline_v2/experiments/uncapped_probe/tests -p 'test_*.py' -q`: **25 tests PASS**, có replay dựa dữ liệu/tokenizer/run local.
- `-m unittest discover -s pipeline_v2/tests -p 'test_m6*.py' -q`: **82 tests, FAILED (errors=6)**. Tất cả lỗi báo `AttributeError: 'AdaptiveHarness' object has no attribute 'explicit_leads'` trong `test_m6_v15_regression.py` (có hai subtest). Fixture tạo harness bằng `__new__` và không khởi tạo thuộc tính mới. Chưa sửa trong công việc bàn giao. Máy đích cần sửa fixture hoặc thiết kế default tương thích sau khi review; chạy lại đúng suite. Không báo M6 regression xanh từ kết quả 14 tests chọn lọc.
- `-m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q`: **109 tests PASS**, 69,210 giây. Đây là kiểm offline; chưa kiểm inference/deployment hoặc chất lượng ngữ nghĩa mới.

### Việc tiếp theo trên máy đích

1. Pull `main` sau khi cất/commit sửa local nếu có; đọc `AGENTS.md`, mục này và CM4.md. Review diff selector/evidence với công việc độc lập ở máy đích trước khi merge. Không reset hoặc chép đè cả module.
2. Sửa lỗi fixture M6 nói trên, chạy lại tests liên quan. Review sâu progress từng pair, draft cũ sau đổi focus/need và ambiguity của normalized anchor; tests PASS chỉ bao phủ tình huống đã kiểm, chưa đủ kết luận các invariants này đúng mọi đường.
3. Dùng raw/artifacts/tokenizer/vector cache/Qdrant máy đích đã có. Các `cache/...` và `pipeline_v2/reviews/...` chưa tracked ở máy nguồn không nằm trong push. Replay CLI, offline_acceptance và một số tests có dependency vào run local lịch sử; thiếu fixture thì ghi rõ thiếu/skip, không tạo receipt thay thế. Các báo cáo local cũ trong thư mục experiments giữ như tài liệu lịch sử và có thể trỏ tới evidence không chuyển.
4. Khi cần preflight CM4 mới, dùng namespace mới. Plan bind root/code/config/source nên không resume plan từ máy cũ hay version khác. `prepare` kiểm local, chưa gọi inference:

```powershell
$cmRun = 'cache/cm4-handoff-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $cmRun
```

5. Chỉ người dùng/AG chạy `live run --run-dir $cmRun` sau khi review preflight và deployment metadata. Codex không tự inference/deploy. STOP đặt tại `$cmRun/STOP`, chỉ có hiệu lực safe boundary; đang chờ call thì poll cùng call, không gửi trùng. Run/admission unknown phải giữ nguyên accounting, không reset để retry. Không dùng lệnh run namespace lịch sử trong tài liệu v1–v22 như lệnh chạy tiếp trên máy mới.
6. Chỉ mở rộng đánh giá sau gate tương ứng; giữ gold ngoài solver, không tự đổi model/chunk/reranker hoặc tune holdout. Báo retrieval → mở nguồn → assessment → selection riêng, cùng request/token/latency và errors/unknown.

### Prompt tiếp tục hiện hành

> Đọc AGENTS.md, CODEX_HANDOFF.md và checkpoint 19/11 trong pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md trước phần lịch sử. Pull/merge cẩn thận với sửa local. Tiếp tục selector M6 và thử nghiệm CM4 cm4-anchor-flow-v23; chưa coi đây là nghiệm thu live/semantic. Trước tiên xử lý 6 errors của fixture test_m6_v15_regression do thiếu explicit_leads, kiểm lại tests và review pair progress/draft/anchor ambiguity. Dùng code, settings và fixtures có thật; không yêu cầu hoặc dựng lại run cũ không chuyển. Giữ nguồn/hash/offset/provenance và unknown accounting. Codex chỉ code, local checks và chuẩn bị lệnh; người dùng/AG chạy inference/deploy. Không tự mở pilot hoặc mốc tiếp theo.

---

Cập nhật ngày 14/11/2026. Theo yêu cầu người dùng: chỉ chuyển code, tests và hướng dẫn cần thiết qua Git; **không cần chuyển các run/evidence thử nghiệm cũ**. Người dùng tiếp quản bước chạy và nghiệm thu tiếp theo.

## 1. Bắt đầu trên máy đích

1. Pull commit bàn giao, đọc `AGENTS.md`, `CODEX_HANDOFF.md`, file này và `pipeline_v2/docs/plan/M6_RETRIEVAL_OPTIMIZATION.md`.
2. Giữ các thay đổi selector/evidence đang làm trên máy kia. Merge/review theo diff, không copy đè cả module hoặc reset working tree.
3. Dùng `.venv/Scripts/python.exe`, dependencies đã pin. Dùng raw data, artifacts M0–M3 và vector cache máy đích đã có. Không embed lại hoặc sửa seals/hashes để vượt guard.
4. Chuẩn bị tokenizer local nếu thiếu:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m4_live prepare-tokenizer --tokenizer-dir cache/tokenizers/qwen36_27b_fp8
```

Code/profile/scripts cần thiết đi cùng commit; `.env`, tokenizers, vector cache, runtime artifacts và các run thử trước không đưa lên Git. Không cần các `local_verification.json`, acceptance receipts hoặc inventory cũ để khởi động công việc mới. Những đường dẫn run/receipt lịch sử trong PROGRESS/kế hoạch có thể chỉ tồn tại ở máy nguồn, không phải dependency cho run mới. Không tạo receipt thành công thay thế cho evidence không chuyển.

## 2. Trạng thái và quyết định hiện hành

| Phần | Trạng thái |
|---|---|
| RT1: lưu raw kết quả từng kênh ngoài prompt, link/hash và verifier | Đã nghiệm thu engineering cached corpus trên máy nguồn |
| RT2: tìm theo issue từ phần paragraph A bị cắt, giữ đúng visible span/hash | Đã nghiệm thu engineering scripted corpus trên máy nguồn |
| RT3: bản đồ A phân cấp, đọc/mở rộng mọi cấp, coverage qua receipts | Code/local PASS; còn cần review độc lập cuối |
| Context input 8.500 | Profile/source đã chuẩn bị; AG báo deploy v2 thành công nhưng canary unknown, chưa nghiệm thu live |
| RT4: mệnh đề debug và hướng dẫn query | Chưa triển khai |
| RT5: 5 embedding và pilot discovery | Chưa triển khai |

Hiện tại dùng profile **`pipeline_v2/reviews/m6_retrieval_rt3_ctx8500_v1/settings.json`**: input cap 8.500, context engine source 12.288, output 384, 8 request/actions, input tổng 68.000, total 71.072. Output contract tối đa 512; việc áp output 512 thuộc RT4, khi đó total 72.096 nếu vẫn 8 lượt. Embedding budget tách riêng.

Map allocation 2.400 trong tổng cap input, fanout tối đa 6, leaf target 1.024 byte, snippet target 96 ký tự. Chỉ heading/snippets literal có nguồn; không tóm tắt ngữ nghĩa trước. Không thêm ba nhóm đầu mối chọn đoạn vào prompt (đang để sau). Không thêm nhánh literal/identity mới đã bỏ khỏi kế hoạch; giữ tool citation cũ.

## 3. Canary chưa rõ: thông tin tối thiểu để tiếp quản

AG đã báo deploy app `coliee-qwen36-27b-fp8-l40s` version v2 exit 0 (5,515 giây). Deploy thành công chưa chứng minh engine GPU nhận context mới hoặc inference thành công.

Một canary được gửi với input đã đếm 8.500, output cap 64, retry 0, embedding 0:

- Call ID: `fc-01M7CBMZWGZDPFSPB4BBT9WB94`.
- Request ID: `527d2d3aa978649b7fb270847c11c96608e4942a4c887f65745e5b94be8adfc6`.
- Client hết chờ sau khoảng 18 phút 23 giây, `TimeoutError` → `modal_result_uncertain`, `cancel_requested=true`, trạng thái `unknown`.
- Actual model execution count/input tokens/output tokens/provider latency và cancel completion đều chưa biết; không ghi 0 chỉ vì không có output.

Người dùng không yêu cầu chuyển run cũ. Dùng call ID để đọc metadata/log hoặc thu kết quả của **call hiện có**, không spawn lại call đó. Nếu không còn truy được kết quả thì giữ unknown lịch sử và ghi rõ giới hạn; không dựng lại run cũ hoặc xóa dấu vết admission để gửi trùng. Người dùng tiếp quản quyết định thử canary mới theo ngân sách riêng.

Canary script dùng transport mặc định `wait_seconds=1080`, hết chờ thì yêu cầu cancel; M6 live dùng `wait_seconds=None` để poll cùng call. Cần review khác biệt này cùng startup/GPU/container logs trước khi quy lỗi cho context/OOM. Không có container sau timeout không đủ xác định nguyên nhân. Function ID guard không được bỏ; thay pin phải có metadata đối chiếu.

## 4. Kiểm mới có thể chạy trên máy đích

### RT3: không cần Qdrant/inference

Dùng `pipeline_v2/reviews/m6_retrieval_rt3_v1/AG_CHECK.md`. Các script code được chuyển, không phụ thuộc run lịch sử:

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -p 'test_m6*.py' -q
```

Bản local trước bàn giao đạt 73 tests (1 skip thiếu ledger lịch sử), 159 map pages trên ba nguồn và navigation giả lập 8 bước cộng đọc root trực tiếp. Đây là engineering, không phải recall/semantic model quality.

Review cuối đặc biệt: continuation vẫn tồn tại khi trim context; reload refs không bị xử lý như context dict; paired A/B giữ read routes; map giữ literal text từng vùng; chưa giao payload thì chưa tính đã đọc. Status node cần merge với `status_defaults` cấp trang. Root/internal/leaf phải đọc raw được, không bắt buộc xuống leaf. Stateless refs và resume giữ source/config binding.

### Profile 8.500 và context live

Dùng `pipeline_v2/reviews/m6_retrieval_rt3_ctx8500_v1/AG_CHECK.md`. Hướng dẫn có checkpoint canary unknown; không coi các lệnh ban đầu là yêu cầu tự retry. `prepare` local không gọi model, `context_canary run` là một request thật và phải do người dùng/AG thực hiện. Phối hợp app dùng chung với máy kia, không deploy ngắt call chưa rõ.

Không lặp kiểm hoặc deploy không cần thiết nếu đã có evidence phù hợp. Mỗi lượt mới dùng namespace mới và ghi tokens/request/latency/lỗi/unknown, không chỉnh reports cũ. Không push credential hoặc output chứa credential.

## 5. Sau khi gate RT3/context đạt

Chỉ sau khi người tiếp quản kiểm và nghiệm thu mới mở RT4, rồi dừng để xem kết quả trước RT5:

- **RT4:** thêm `source_proposition` do model diễn đạt, bắt buộc trong JSON action issue search, chỉ để debug; query vẫn từ `issue`, không ghép mệnh đề vào retrieval. Sinh cùng lượt, không thêm lượt model. Output 512; input 8.500/8 lượt thì total 72.096. Thêm hướng dẫn query giữ thuật ngữ phân biệt, tránh quá chung hoặc gộp nhu cầu; giữ tình tiết hữu ích. Kiểm schema/ledger/query/token và AG canary live.
- **RT5:** profile embedding tối đa 5 request, tổng 2.240 input token embedding; kiểm feasibility navigation/read/search trong controller cap. Freeze discovery pilot, chấm từng kênh/RRF/pool qua diagnostic RT1, giữ đủ denominator/lỗi/chi phí. Không đưa gold vào solver hoặc tune holdout.

Đừng đổi model/chunk/reranker/fusion/K/selector đồng thời rồi quy gain cho query/navigation. Giữ provenance raw/hash/UTF-8 spans, trạng thái unread/partial/unknown. Model annotations không phải passage gold. Protocol PASS không chứng minh đúng quan hệ pháp lý hoặc COLIEE recall.

## 6. Prompt tiếp tục

> Đọc AGENTS.md, CODEX_HANDOFF.md và pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md. Người dùng tiếp quản bước tiếp theo, không yêu cầu các run/evidence cũ. Code retrieval RT1/RT2 đã nghiệm thu engineering; RT3 chờ final review, context input 8.500 có deploy báo thành công nhưng call canary fc-01M7CBMZWGZDPFSPB4BBT9WB94 vẫn unknown. Giữ thông tin này, không tự resend. Dùng profile ctx8500, context source 12.288, output hiện 384. Merge với selector/evidence máy này cẩn thận, không ghi đè cả module. Tạo evidence mới khi cần và ghi rõ không tái kiểm được receipt lịch sử không chuyển. Sau nghiệm thu RT3/context mới triển khai RT4 rồi dừng gate, sau đó RT5. Codex chuẩn bị code/lệnh, người dùng/AG chạy deploy/inference; không tự thay model/chunk/holdout policy.
