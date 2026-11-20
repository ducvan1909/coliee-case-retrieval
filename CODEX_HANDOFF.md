# Bàn giao Pipeline V2 cho Codex trên máy khác

## Điểm bàn giao hiện hành — Pilot CM4 v30 và hướng tiếp theo cho COLIEE Task 1

Mục tiêu là trả về tập án trong corpus mà án A tham chiếu. Dùng micro precision, recall và F1 để so kết quả, kèm số lượt, token và thời gian chạy. Bắt đầu bằng hai việc offline: xác minh danh tính B trước khi chọn và dùng lại phần khảo sát khi truy hồi trả cùng tập kết quả. Các mục bên dưới là lịch sử của những phiên bản trước. [Đề bài Task 1](https://coliee.org/COLIEE2026/tasks/task1) · [Cách tính điểm](https://coliee.org/COLIEE2026/evaluation)

### Code và bằng chứng cần đối chiếu

- Run nguồn `cache/cm4-query-review-v30-ag-20261120-105534942`, án A `021095.txt`, engine `cm4-query-review-v30`, commit nền `7c230e5`. Đối chiếu source đang dùng với `plan.json` và `plan.code_binding` nếu có run. Commit nền chỉ xác định điểm xuất phát vì run bind cả code trong working tree.
- Code chính ở `pipeline_v2/experiments/context_manager_v2/`. Xem `engine.py` và `query_review.py` cho trạng thái từng query, `tool_repair.py` cho lỗi refs, và `pipeline_v2/agent_harness/{selection,ledger}.py` cho điều kiện chọn án. Đọc [AGENTS.md](AGENTS.md) trước khi sửa.
- Nếu có run nguồn, đọc `semantic_review.md`, `semantic_steps.md`, `result.json`, `session/events.sqlite3`, manifests và retrieval diagnostics trong namespace đó. Đọc ledger lịch sử ở chế độ chỉ đọc. Nếu máy kia chỉ có repo, dùng các fixture và suite hiện có để tái hiện các lỗi mô tả bên dưới, rồi bổ sung regression đúng ca sửa. Ghi rõ phần nào kiểm bằng fixture và phần nào kiểm được với run thật. Chuyển cache và receipts cũ là tùy chọn.

### Những phần đã sửa và phạm vi kiểm

| Mốc | Thay đổi đã có | Bằng chứng và giới hạn |
|---|---|---|
| RT1 · Chẩn đoán retrieval | Ghi kết quả từng kênh case BM25, passage BM25 và dense passage ngoài payload. Liên kết query, need, operation, refs A và thứ hạng RRF/hits đã giao. Giữ riêng lỗi, unknown và trường hợp dense scan chạm cap. | Cached hybrid trên Qdrant và verifier provenance đã đạt, 0 inference mới. Dùng để tìm gold rơi ở kênh, fusion hay cutoff khi có evaluator. |
| RT2 · Đoạn A bị cắt | Cho phép tìm từ span raw đủ ý dù paragraph bị chia trang. Host giữ source hash, UTF-8 byte span và text hash. | 41 unit test và 9 kiểm tra từ corpus thật đạt. Đây là kiểm contract và nguồn. |
| RT3 · Điều hướng A và tokenizer | Bản đồ nhiều cấp có ref mở vùng con, byte span và preview literal. Vùng vừa ngân sách có thể mở nguyên văn. Vùng lớn dùng bản đồ và subdivision. Tokenizer và chat template được pin để đếm payload thật. | Xem các checkpoint RT3 và replay CM4. Profile RT3 lịch sử có output 384, khác launcher CM4 v30. |
| RT4/RT5 và nhánh thử nghiệm | CM4 nhận `issue` và `source_proposition`. Chỉ `issue` gửi retrieval, còn mệnh đề do model diễn đạt để truy vết. Output mỗi lượt lên 512. Repo có profile RT5 bounded với tối đa 5 embedding request. Pilot CM4 dùng nhánh `uncapped` bên dưới. | Phân biệt profile và scope nghiệm thu. Launcher CM4 live yêu cầu `experiment_mode=uncapped`. |
| M6 selector và đọc B | Host tổng hợp assessment theo ứng viên. Explicit passage lead mở đúng đoạn retrieval và đúng need. Hybrid hỗ trợ tới 50 án theo RRF trên các danh sách kênh đã có. | M6 selector bảo thủ có kiểm định danh header. CM4 live hiện bật `model_attribution` / `model_support`, vì vậy cần mốc xác minh B ở phần làm tiếp. |
| CM4 v24–v25 · Một query đang mở | Khóa query tới khi có conclusion. Survey đủ tập kết quả rồi mới mở raw B. Có priority, receipt-based coverage, kết luận partial và trạng thái dang dở tách riêng. Source gate cho mệnh đề chưa có citation và span partial đủ ý. Có `read_query_span` để ghép cửa sổ liên tục đã được giao. V25 bỏ alias gate và công cụ anchor/citation cũ khỏi catalog live. | V25 đạt 126 test local. Pilot thật dừng trước T5 vì map thừa ở results mode. |
| V26 · Map chỉ ở query mode | Bỏ dựng map A ngoài query mode. Đếm cap map trên payload đã compact, giữ mã định danh đầy đủ ở host. Map thực sự không vừa có lỗi terminal được ghi. | 129 test CM4 và 11 test navigation đạt. Replay trước T5 đạt. Pilot vượt T5 rồi AG STOP khi mới survey 10/50 và chưa mở raw B. |
| V27 · Focus và survey | Khi query còn mở, chặn thay đổi source gate ở schema và host. Giữ đường đọc A. Hiện `query_gate_paused`, trang đang xem và `next_unseen`. Loại lượt gán lại cùng priority. | 132 test đạt. Replay T08/T12/T44 đạt. Pilot đủ năm tập 50 thẻ, mở raw 3 án rồi AG STOP do lặp mệnh đề đã tìm. |
| V28 · Preview, đọc B và mệnh đề đã tìm | Thẻ survey có preview literal tối đa 320 ký tự, gắn span/hash. `read_next` dẫn về ứng viên ưu tiên chưa đọc. Trước khi kết luận phải đọc hoặc hạ ưu tiên có lý do. Query có hits và chưa có raw B chỉ được kết luận partial. Mệnh đề đã tìm bị loại khỏi lựa chọn tìm mới và có thể mở lại qua `revisit_source_need`. Prompt bổ sung giữ điều kiện pháp lý, phân biệt người nói, chiều A tham chiếu B và kiểm ngày khi đã xác minh. STOP sau admission và trước gửi được ghi là operator stop với `submission_attempted=false`. | 135 test đạt. Pilot 250 lượt mở raw 59 án B và dừng khi dựng payload lượt 251. |
| V29 · Vùng A không còn vừa | Khi full region vượt cap do feedback/catalog thay đổi, cấp payload điều hướng tới bản đồ cha hoặc subdivision. Lượt này chưa giao raw và chưa tăng coverage. | 136 test đạt. Dựng lại đúng boundary T250 cho payload 1.940 token với tokenizer thật, 0 request Modal mới. |
| V30 · Phân trang nhu cầu nguồn | `unresolved_source_needs` và enum `defer_source_need` chỉ xuất tối đa năm mục. `show_source_need_page` chuyển trang theo ref được cấp và giữ nguyên focus. Host giữ toàn bộ trạng thái và ẩn các thao tác gate khi query còn mở. | 137 test đạt. Với 96 mục giả lập, map giảm từ 9.550 xuống 5.198 token và fallback từ 9.419 xuống 2.065 token. Pilot v30 chưa đi qua nhánh phân trang này. |

Chi tiết implementation và evidence nằm ở [bàn giao retrieval RT1–RT5](pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md), [luồng CM4](pipeline_v2/experiments/context_manager_v2/CM4.md) và [báo cáo v28–v30](pipeline_v2/reviews/cm4_survey_focus_fix_v1/PILOT_20261120.md). Lịch sử đã test local, pilot live và điểm Task 1 cần được báo riêng khi tiếp quản.

### Uncapped đã chạy như thế nào?

- **Ngân sách cộng dồn:** profile `uncapped` dùng `2**60` cho số request/action và input token cộng dồn của controller, cùng số request và input token cộng dồn của embedding. `max_total_tokens=null`, `max_retries=0`. Pilot không phát `--max-turns`, nên `max_turns=null`. Các giá trị cực lớn phục vụ thí nghiệm quan sát khả năng model đi được tới đâu.
- **Giới hạn từng lượt:** CM4 có 8.500 input và 512 output. Map có cap 2.400. Source deployment controller khai context 12.288. Launcher mặc định nâng `search_limit` lên 50 khi dùng settings mặc định. Nếu truyền `--settings` riêng thì đọc giá trị thật trong plan. Cần phân biệt giá trị `search_limit=3` trong JSON profile gốc với 50 của pilot CM4.
- **Điều kiện dừng:** pilot dùng loop guard `warn`, tiếp tục ghi cảnh báo cycle/no-progress và cho AG giám sát. File `STOP` được xử lý ở ranh giới an toàn. Lỗi context, nguồn hoặc provider vẫn có thể kết thúc run. Lượt đã admission nhưng chưa gửi, lượt đã gửi chưa rõ kết quả và lượt đã có receipt được ghi và đối chiếu riêng.
- **Chờ GPU:** controller dùng `wait_seconds=null` để poll cùng call. Khi Modal đang chờ GPU, chỉ đạo hiện hành là AG tiếp tục chờ và giám sát request gốc, tránh gửi trùng hoặc cắt chỉ vì chờ lâu. Phân biệt thời gian xếp lịch với thời gian model chạy và lý do người dùng dừng cả pilot. Xem [hướng dẫn AG](pipeline_v2/reviews/cm4_query_review_v24/AG_CHECK.md).
- **Môi trường pilot:** profile Modal `g38180254`, controller Qwen 27B pin `fu-TfWPSIRNQIkZWM1W5O7HEv`, Qwen3-Embedding-4B trên L4 và Qdrant local collection `coliee_m3_full_ef2f4d6950a5b9fd`. Dùng tokenizer, sparse index và vectors đã pin. Tạo namespace mới khi đổi code, máy hoặc settings và đối chiếu binding trước khi chạy. [Bàn giao endpoint và accounting](pipeline_v2/reviews/cm4_survey_focus_fix_v1/MODAL_ACCOUNT_20261120.md)

Uncapped là cấu hình đã dùng để thu bằng chứng ở pilot v30. Việc đề xuất ngân sách hữu hạn cho thử nghiệm tối ưu Task 1 ở phần làm tiếp cần được chốt dựa trên dữ liệu discovery. Đây chưa phải thay đổi đã triển khai.

### Kết quả pilot v30

AG dừng theo yêu cầu của người dùng vì thời gian và chi phí. Run kéo dài **26.072,776 giây, khoảng 7 giờ 15 phút**, với **501 lượt controller**, **476 action**, **2.525.932 input token**, **43.792 output token** và không có usage unknown trong run này. T501 đã nhận phản hồi, STOP chặn action tại `after_reply_before_action`. Kết quả ghi `operator_stop_file`, `pending_selection` và `prediction=null`. Retrieval có năm query và ba request embedding, tổng 121 token. Q4 và Q5 dùng lại kết quả Q3.

Cả năm query khảo sát đủ 50 thẻ. Ledger giữ 250 cặp query–ứng viên, 119 án duy nhất trong pool và 79 án duy nhất được cấp raw. Bốn query đã kết luận và Q5 còn đang review. Model được cấp raw A ở `[0, 16061)` trong tổng 48.635 byte, khoảng 33%, và mới sàng lọc tới đoạn đánh số [18]. Phần nhận định từ [89] nằm ngoài vùng đã cấp. V30 vượt mốc từng gặp lỗi context ở v28. Đường dự phòng context và phân trang nhu cầu nguồn chưa phát sinh trong pilot v30.

Mỗi hàng dưới đây tính từ lượt phát lệnh tìm tới lượt kết luận. Q5 tính tới T501. Khoảng giữa các hàng có các lượt đọc A và xác định nhu cầu.

| Query | Lượt | Span A, byte | Text gửi retrieval | Controller / input token | Thẻ / raw B | Kết luận |
|---|---|---|---|---:|---:|---|
| Q1 | T015–T107 | `[5805, 6186)` | `leave to file reply affidavit judicial review` | 93 / 443.277 | 50 / 25 | `no_supported_source_found` |
| Q2 | T117–T255 | `[7580, 7829)` | `standard of review prothonotary discretion` | 139 / 679.049 | 50 / 36 | `partially_resolved` |
| Q3 | T257–T357 | `[7829, 7999)` | `standard of review interlocutory prothonotary` | 101 / 500.632 | 50 / 28 | `partially_resolved` |
| Q4 | T359–T462 | `[7999, 8574)` | `standard of review interlocutory prothonotary` | 104 / 534.569 | 50 / 28 | `partially_resolved` |
| Q5 | T464–T501 | `[8574, 8660)` | `standard of review interlocutory prothonotary` | 38 / 193.560 | 50 / 6 | Dừng giữa review |

### Các lỗi có bằng chứng và tiêu chí nghiệm thu

1. **Nhầm B trích án X thành B là X.** AG đối chiếu 12 án tạm `supported` và xác định chúng đều sai danh tính đối với nguồn F.C.A. được nêu ở [18]. Raw A còn `315 N.R. 175 (F.C.A.)`. Các B là quyết định Federal Court trích lại nguồn đó hoặc nguồn liên quan. Bảy B ra đời sau A theo ngày AG kiểm được. CM4 live hiện dùng `model_support=True`, nên đoạn trích trong B có thể được model gán `supported` mà thiếu bằng chứng nhận dạng của chính B. Tái hiện bằng A, đoạn B trích án thứ ba và header B. Regression phải giữ B ở `unknown` hoặc loại khỏi nguồn cho mệnh đề đó khi thiếu hoặc mâu thuẫn định danh. Ca positive cần giữ được khi A khớp định danh của chính B. Mười hai nhận định của AG chỉ áp dụng cho nguồn đang xét ở [18]. Chưa đối chiếu gold của cả án.
2. **Q4–Q5 duyệt lại cùng tập kết quả Q3.** Ba query dùng span A khác nhau nhưng gửi cùng text. Q4–Q5 nhận cùng 50 án, cùng thứ tự, có receipt `search_reuse` trỏ về Q3. Hai vòng dùng lại vẫn tốn **142 lượt controller và 728.129 input token**, khảo sát thêm 100 thẻ. Q4 mở raw 28 B, trong đó 23 B đã mở trong Q3. Cả 6 B Q5 mở đều đã mở trong Q3 hoặc Q4. Như vậy 34 lần cấp raw tính theo hai query chỉ thêm 5 B duy nhất trong nhóm Q3–Q5. Tổng run dành **165 action chuyển trang và 53 action đổi ưu tiên**, khoảng 46% action đã thực thi. Regression cần giữ lịch sử query riêng nhưng dùng lại thẻ đã khảo sát, danh tính đã xác minh và raw đã cấp khi nguồn khớp. Mệnh đề hoặc evidence mới vẫn có đường đánh giá riêng. Đo số lượt tránh được trên replay và phân biệt với chi phí live thực tế.
3. **Tool ref trùng làm tốn thêm lượt.** Có 24 reply bị từ chối vì `duplicate_evidence_refs` ở `container_refs`, tốn 118.378 input và 5.710 output token. Q2 có 15 lượt lỗi. T180–T184 lặp lại ref giống hệt trong cùng trường. Thử khử trùng giữ thứ tự ở trường mà ref mang nghĩa tập hợp, sau đó áp dụng lại validation về quyền dùng ref, vai trò và provenance. Regression phải bao gồm cả ref trùng hợp lệ và ref sai hoặc ngoài payload. Giữ reply gốc và accounting.
4. **Độ phủ A và mệnh đề còn thiếu.** T003 đóng cả [2] là thủ tục, che hai căn cứ về tài liệu có thể có sẵn sớm hơn và việc tách vụ án. Ở Q1, text tìm làm mất điều kiện về thời điểm tài liệu có thể được cung cấp. Đoạn [18] lại chiếm bốn query, tổng 383 lượt controller và 1.907.810 input token. Phần nhận định [89] trở đi chưa được cấp. Xem raw của `021095.txt` và review theo lượt. Sàng lọc theo span phải để các mệnh đề khác trong cùng paragraph còn đường xét.

### Thứ tự làm tiếp

1. **Mốc đầu · Xác minh danh tính B.** Rà `witnessed_identity` hiện có và đường `model_support` của CM4. Phân biệt định danh trong header B với citation nằm trong thân B. Dùng ngày và cấp tòa khi chứng cứ xác minh được. Đối với citation bị che, thử đường kiểm nhận dạng dựa trên các bằng chứng còn thấy và giữ `unknown` khi thiếu căn cứ. So ca positive và ca B chỉ trích lại X trước khi đổi selector rộng hơn.
2. **Mốc đầu · Giảm công việc lặp.** Tách cache pool, lịch sử khảo sát và evidence theo B khỏi kết luận theo mệnh đề. Khi receipt cho thấy kết quả giống hệt, giữ đường đến các ứng viên hoặc evidence chưa kiểm. Xác minh danh tính B một lần theo hash nguồn. Khử trùng refs hợp lệ và kiểm lại guard. Hai mốc đầu yêu cầu regression local và review độc lập. Nếu có ledger v30, dựng lại các điểm Q4–Q5 và chuỗi T180–T184 mà giữ nguyên run nguồn. Khi thiếu ledger, chạy fixture và báo giới hạn tái hiện.
3. **Đề xuất sau hai mốc đầu · Thử giảm survey và đọc A có ưu tiên.** So khảo sát 50/50 với shortlist đọc sâu dựa trên dấu hiệu định danh và điểm retrieval. Giữ danh sách top 50 ngoài prompt để đo candidate recall. Tận dụng các dấu hiệu còn thấy trong corpus, cấu trúc A và vùng nhận định để chọn mệnh đề. So query theo định danh còn thấy với query theo mệnh đề trên discovery. Giảm lặp trên cùng cụm nguồn, giữ quyền xét span khác khi nó đặt câu hỏi độc lập.
4. **Đề xuất đánh giá · Chốt ngân sách qua so sánh trên discovery.** Đo gold vào pool, qua shortlist và vào prediction cuối. So với BM25/hybrid hiện có trên cùng cohort, báo micro precision, recall, F1, số lượt, input/output token, latency và thống kê án dừng sớm. Khi tới ngân sách, thử đường chốt tập án đã qua xác minh và ghi rõ trạng thái dừng. Chọn ngưỡng chi phí từ kết quả đo. Tách gold ở evaluator và giữ test queries ngoài quá trình chỉnh hệ thống. Xem [kế hoạch đánh giá](pipeline_v2/docs/plan/AGENT_AND_EVALUATION.md).

Máy kia tiếp quản kiểm và triển khai local trước. Báo riêng lỗi retrieval khi gold chưa vào pool và lỗi chọn án khi gold đã vào pool. Pilot v30 chưa có prediction cuối hoặc evaluator gold nên chưa kết luận thay đổi F1. Nếu cần pilot live sau kiểm local, người dùng hoặc AG chạy theo [hướng dẫn AG](pipeline_v2/reviews/cm4_query_review_v24/AG_CHECK.md) với namespace mới. Quy định chờ request đang pending GPU vẫn áp dụng cho lượt đã gửi.

## CM4 v30

V30 phân trang các nhu cầu nguồn đủ điều kiện hoãn. Host giữ toàn bộ trạng thái và chỉ cấp tối đa năm lựa chọn mỗi lượt cùng đường chuyển trang. Dùng namespace mới theo [hướng dẫn AG](pipeline_v2/reviews/cm4_query_review_v24/AG_CHECK.md). Số token đối chiếu nằm trong [báo cáo kiểm](pipeline_v2/reviews/cm4_survey_focus_fix_v1/PILOT_20261120.md).

## CM4 v29 sau pilot v28

Pilot `021095.txt` hoàn tất 250 lượt rồi dừng `context_unfit` khi dựng lượt kế tiếp. V29 cấp đường chia nhỏ hoặc quay về bản đồ cha nếu vùng A đang mở vượt ngân sách. Dùng fresh namespace theo [hướng dẫn AG](pipeline_v2/reviews/cm4_query_review_v24/AG_CHECK.md) và xem [evidence pilot](pipeline_v2/reviews/cm4_survey_focus_fix_v1/PILOT_20261120.md). Giữ nguyên receipts run v28.

## CM4 v28 sau pilot v27

Bảng thay đổi pipeline từ base `7c230e5`, phạm vi file, evidence và giới hạn nghiệm thu được ghi tại [PROGRESS.md — cập nhật 20/11/2026](pipeline_v2/docs/PROGRESS.md).

Pilot v27 đã khảo sát đủ 5 tập kết quả nhưng chỉ mở raw 3 án B, sau đó AG dừng vì lặp screening ở `p000020`. V28 thêm preview có provenance, đường quay lại `read_next`, điều kiện kết luận và loại mệnh đề đã xử lý khỏi lựa chọn tìm mới. Xem [báo cáo pilot và yêu cầu kiểm v28](pipeline_v2/reviews/cm4_survey_focus_fix_v1/PILOT_20261120.md) và [lệnh AG](pipeline_v2/reviews/cm4_query_review_v24/AG_CHECK.md). Dùng namespace mới và giữ chỉ đạo chờ GPU vô hạn bên dưới.

## Modal mới — 20/11/2026

**Quy định chờ GPU mới:** người dùng yêu cầu AG chờ vô hạn khi Modal pending cấp worker, không tự kill/STOP/cancel/redeploy hoặc gửi probe/request mới vì chờ lâu. Giữ request gốc và theo dõi read-only đến kết quả; tiếp tục run khi có GPU. Chỉ dừng theo chỉ đạo người dùng hoặc lỗi terminal thật. Không áp loop/no-progress của model lên thời gian scheduler chờ. Chi tiết ở mục 4 [AG_CHECK](pipeline_v2/reviews/cm4_query_review_v24/AG_CHECK.md).

AG chuyển profile và deploy hai dịch vụ; code controller pin hiện `fu-TfWPSIRNQIkZWM1W5O7HEv`. V27 pilot mới có 4 controller replies nhưng dừng giữa query embedding, attempt vẫn started/remote usage unknown, chưa tới survey. Đọc [bàn giao account và điều kiện chạy lại](pipeline_v2/reviews/cm4_survey_focus_fix_v1/MODAL_ACCOUNT_20261120.md). Không retry chỉ vì client đã kill; xác định call gốc trước. Chưa đổi GPU/cap/model, chưa có semantic/live acceptance v27. Không tự inference/deploy.

## Checkpoint mới nhất — 19/11/2026

**V27 hiện tại:** sau run AG v26 STOP ở 10/50 survey và 0 raw B, khóa gate mutations khi active query, thêm next-unseen/progress và bỏ priority assignment không đổi. Giữ đọc A, coverage thật, warn/STOP và cap 8500/512. Đọc [REPORT v27 và lệnh AG](pipeline_v2/reviews/cm4_survey_focus_fix_v1/REPORT.md); không resume v26 STOP bằng code mới. Kết quả local không phải semantic/live PASS.

**Checkpoint sửa map v26:** không dựng map ngoài query mode; cap map đếm theo CM4 projection thật. Run AG v25 đã xong 4 lượt rồi crash trước lượt 5, chưa có survey/B assessment. [Báo cáo v26](pipeline_v2/reviews/cm4_map_projection_fix_v1/REPORT.md) giữ lịch sử; dùng lệnh v27 ở trên cho pilot tiếp. Codex vẫn không tự inference/deploy.

**Cleanup trước bản sửa map:** v25 chuyển gate sang v4 chỉ còn `search_needed` / `no_search_needed` / `need_more_context`; v26 giữ contract này. Không cấp tool citation/nháp anchor của luồng cũ; recovery hints chỉ trỏ tool đang được cấp. [CM4.md](pipeline_v2/experiments/context_manager_v2/CM4.md) và [MODEL_CONTEXT_FLOW.md](pipeline_v2/experiments/context_manager_v2/MODEL_CONTEXT_FLOW.md) đã tách lịch sử khỏi hướng dẫn hiện hành. Xem [kiểm cleanup](pipeline_v2/reviews/cm4_query_review_v24/CLEANUP.md). Phải prepare namespace mới, không chạy plan revision cũ.

**Đợt Q1–Q4 sau review:** người dùng đã yêu cầu làm toàn bộ [kế hoạch CM4 query review](pipeline_v2/docs/plan/CM4_QUERY_REVIEW_PLAN_20261119.md). Engine mới `cm4-query-review-v24` / live `cm4-live-v2`: khóa từng search query, survey trước deep read, gate nhu cầu nguồn/partial span và loop warn mặc định. Đọc [báo cáo local](pipeline_v2/reviews/cm4_query_review_v24/REPORT.md) và [lệnh giao AG](pipeline_v2/reviews/cm4_query_review_v24/AG_CHECK.md) để biết kết quả nghiệm thu thực tế. Chưa có live/semantic PASS mới; Codex không tự inference/deploy. Chuẩn bị namespace mới, không resume plan v23 bằng code v24. Các checkpoint v23 phía dưới là lịch sử trước đợt này.

Đọc **mục Checkpoint bàn giao mới — 19/11/2026** trong [RETRIEVAL_HANDOFF_20261114.md](pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md) trước các phần lịch sử dưới đây. Lần push này chuyển selector/M6, explicit passage leads, M6 hybrid output đến 50 và ba bộ thử nghiệm context (CM4 hiện `cm4-anchor-flow-v23`), cùng tests/settings/tài liệu. Không chuyển run/cache/evidence local cũ. Có lỗi fixture regression M6 đã tái hiện và hướng dẫn xử lý trong checkpoint; chưa nghiệm thu live/semantic. Tạo namespace mới khi đổi máy/code, giữ unknown admissions, không tự resend. Codex chỉ chuẩn bị code/lệnh và kiểm local; người dùng/AG chạy inference/deploy.


## Bàn giao retrieval mới ngày 14/11/2026

Nếu tiếp tục đợt tối ưu retrieval RT1–RT5, đọc thêm `pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md` trước khi thao tác. Tại checkpoint này RT1/RT2 đã nghiệm thu engineering, RT3 chờ AG review cuối; profile mới input 8.500/context source 12.288 chưa nghiệm thu live. Pull commit bàn giao chứa cả code/tests/hướng dẫn mới, không chỉ base `c0ab182`. File bàn giao ghi phạm vi selector máy kia, trạng thái AG và gate trước RT4. Các nội dung phía dưới giữ làm lịch sử nền/khôi phục assets.

Cập nhật kết quả AG: deploy v2 báo exit 0 nhưng canary 8.500 của call `fc-01M7CBMZWGZDPFSPB4BBT9WB94` timeout/unknown, đã yêu cầu cancel; actual provider usage chưa biết. Không resend run đã admission hoặc coi context live PASS. Theo yêu cầu bàn giao mới nhất, chỉ push code/tests/hướng dẫn cần thiết, không yêu cầu chuyển run/evidence/inventory cũ; người dùng tiếp quản phần tiếp theo theo file bàn giao mới.

Cập nhật ngày 10/11/2026. Đọc file này trước, rồi `AGENTS.md`, `pipeline_v2/docs/PROGRESS.md` và ba tài liệu trong `pipeline_v2/docs/plan/`. Các đoạn trạng thái cũ trong tài liệu kỹ thuật là checkpoint lịch sử. Tiến độ dưới đây phản ánh kết quả hiện hành.

## Cập nhật checkout đã có dữ liệu Pipeline V2

Sau khi pull, dùng lại raw corpus, các bundle đã seal, cache embedding và sparse index tại đường dẫn cũ. Kiểm collection Qdrant nếu dùng hybrid. Phần tiến độ M4–M6 mới nhất nằm trong [PROGRESS.md](pipeline_v2/docs/PROGRESS.md).

Để kiểm đường chạy M6 trên máy đích, cài dependencies và chuẩn bị tokenizer controller đã pin nếu máy chưa có. Lệnh `prepare` kiểm nguồn, index, tokenizer và payload ban đầu với 0 request inference.

```powershell
& .venv/Scripts/python.exe -m pip install -r pipeline_v2/requirements-m4-local.txt
& .venv/Scripts/python.exe -m pipeline_v2.m4_live prepare-tokenizer --tokenizer-dir cache/tokenizers/qwen36_27b_fp8
$run = "cache/m6-preflight-$(Get-Date -Format yyyyMMdd-HHmmss)"
& .venv/Scripts/python.exe -m pipeline_v2.m6_live prepare --settings pipeline_v2/reviews/m6_local_v1/live_preflight_settings.json --run-dir $run
```

Settings trên dùng BM25. Với hybrid, chạy thêm `diagnostic-hybrid` bên dưới hoặc dùng [settings kiểm tích hợp hybrid](pipeline_v2/reviews/m6_hybrid_local_v1/live_settings.json) cho một thư mục preflight mới. Các log và ledger lịch sử được giữ trên máy đã chạy. Chuẩn bị thư mục run mới cho các lượt thử trên máy đích.

## Mục tiêu và các quyết định đã chốt

COLIEE Task 1 nhận query case A và trả tập candidate cases được A thực sự viện dẫn hoặc sử dụng theo nhãn chuẩn. Agent truy tìm nguồn và evidence A→B, phân biệt source identity, vị trí đoạn và cách sử dụng. Tương đồng nội dung là tín hiệu truy hồi. Lập luận của đương sự, lời tòa và trích dẫn lồng giữ attribution riêng.

Trước query xây kho raw nguồn, cấu trúc, metadata quan sát được, passages, chỉ mục và công cụ đọc. Chưa xây doctrine/AU hoặc citation graph bằng suy luận toàn corpus. Nhãn chỉ dùng ở nghiên cứu/evaluator tách khỏi solver. Discovery/holdout và exposure ledger đã khóa ở M0. Kế hoạch hiện tại dùng micro-P/R/F1 trên unique `(query,candidate)`, đủ denominator. Kiểm lại protocol chính thức trước M7, giữ riêng mọi metric bổ sung.

- Marker `[số]` đầu dòng là boundary độc lập, role `current_case`, `quoted` hoặc `unknown` dựa evidence. Thứ tự số không điều khiển reset/gộp đoạn.
- Chunk bắt đầu từ paragraph theo cấu trúc. Parent dài tách theo tokenizer. BM25/dense dùng cùng core body và IDs, analyzer/tokenizer riêng được khai báo.
- Hit child `12b` mở full parent 12 và hàng xóm theo source order, giữ spans, hashes và pending continuation. Không dùng marker ±1 để tìm hàng xóm.
- Query vừa budget agent đọc toàn văn. Query dài dùng map, preview có provenance, context ưu tiên và mở thêm theo nhu cầu. Tokenizer/model/budget agent M4 còn cần chốt.
- Giữ nguyên tiếng Pháp, hiện chưa phân tích ngữ nghĩa hoặc tune riêng. Không dùng language metadata làm bộ lọc bỏ nguồn.
- Codex viết/sửa production. AG review, viết test độc lập và chạy các lệnh được giao. Codex chỉ đưa lệnh Modal để người dùng/AG chạy theo yêu cầu hiện hành.

## Tiến độ và nghiệm thu

| Mốc | Trạng thái |
|---|---|
| M0 | Khóa nguồn train, cohort 10 discovery + 10 holdout và exposure ledger. Embedding đã chốt sau checkpoint M0. |
| M1 | Nghiệm thu raw registry, UTF-8 offsets và cấu trúc marker/quotation/unknown theo contract. |
| M2 | Nghiệm thu toàn train, 7.708 án, 382.343 parents, 415.693 passages, tối đa 448 full-input tokens, mapping parent/context. |
| M3 | Full embedding/cache/Qdrant integrity đã nghiệm thu. BM25 sparse hai kênh và hybrid local dùng vector cache đã qua AG review. Còn các công cụ case/phrase/identity/context và query embedding thật. |
| M4 | Chưa có harness agent hoàn chỉnh. Cần tool delivery ledger, budgets, resume/fallback và invalidation assessments. |
| M5 | Chưa có baseline lịch tìm/đọc cố định end-to-end cho V2. |
| M6 | Chưa có controller thích ứng và targeted review. |
| M7 | Chưa chạy đánh giá khóa/F1. |

Full ingestion có 6.496 batch thành công, 55.346.360 input tokens và 55.360.576 padded tokens. Ledger còn 1 attempt `started` bị ngắt, tokens/elapsed `null`. Giữ nguyên khoản usage unknown này. Full DB có 415.693 points. Không cần embed lại corpus.

Sparse review đạt 37/37 unit/regression và 6/6 nhóm kiểm thử độc lập, 0 lỗi production chặn nghiệm thu. 16 phép đối chiếu corpus khớp IDs và điểm tuyệt đối. Ba truy vấn hybrid Qdrant local khớp từng kênh và top 20 RRF với bản SQLite. Tổng BM25 còn 0,41–0,61 giây. Mở session khoảng 35–39 giây, nên dùng một session xuyên nhiều truy vấn. Peak working set Python khoảng 523 MiB. Dense exact search và kiểm vector hiện chiếm phần lớn latency. Xem `pipeline_v2/reviews/m3_sparse_ag_review_v1/`.

## Tài sản và fingerprint hiện hành

| Tài sản | Đường dẫn hoặc giá trị |
|---|---|
| Raw train | `data/task1_train_files_2026/cases/` |
| Nhãn evaluator | `data/task1_train_files_2026/clean_task1_train_labels_2026.json` |
| M0 / M1 | `pipeline_v2/artifacts/m0_20261105_v2/`, `m1_20261105_v2/` |
| Navigation | `pipeline_v2/artifacts/m2_navigation_20261106_v3/` |
| Passages | `pipeline_v2/artifacts/m2_passages_20261106_v1/` |
| Full run | `pipeline_v2/artifacts/m3_full_train_20261108_v1/` |
| Sparse | `pipeline_v2/artifacts/m3_sparse_20261110_v1/`, 403.896.521 sealed bytes |
| Compatibility chain | `m3_pilot_20261106_l4_v1/`, `m3_opt_v2_index_20261108_v1/`, `m3_opt_v2_compat_20261108_v1/` dưới `pipeline_v2/artifacts/` |
| Full verify receipt | `pipeline_v2/reviews/m3_full_ag_review_v1/step5_verify_stdout.json` |
| Full collection | `coliee_m3_full_ef2f4d6950a5b9fd` |
| Qdrant | Docker local `qdrant/qdrant:v1.20.0`, REST `http://127.0.0.1:6333` |
| Modal app / class | `coliee-pipeline-v2-embed-m3-opt-v2` / `Embedder`, GPU L4 |
| Embedding | `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`, 2560-dim normalized FP32 output, BF16 weights |
| Tokenizer assets | `pipeline_v2/vendor/qwen3_embedding_4b_tokenizer/5cf2132abc99cad020ac570b19d031efec650f2b/` |

Các hash dùng đối chiếu, không sửa để vượt guard.

```text
accepted M2 seal
0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6
full implementation aggregate
e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503
sparse implementation aggregate
dd4eeb17401cbda28f9a14d7f9300fffde3765397e94e9bfe775385c7f2e5c7e
full manifest SHA-256
7bdf2bb5dda4b324147f5332f4c4a0ed95b15a953b2d3c40fe9f184ca74d45b0
full lexical.sqlite3 SHA-256
6ad1f818618bd6d4d66e0b89c3b06a5bc033da4ac19c86030859fdf9b8bc03fa
full verify receipt SHA-256
b841927b07e001435779a3575e3abccfd0f564e81680e63b801f39049b0ccd08
```

Full cache gồm 6.496 cặp `.npz`/`.json` trong `vectors/`, tổng 4.466.141.805 bytes. `lexical.sqlite3` là 4.357.505.024 bytes. Giữ ledger, invocations, receipts, manifests và seals cùng run. Code full phụ thuộc cả optimization/pilot readers và source/navigation/passages. Giữ nguyên modules/config đã bind hash khi thêm module mới. Sửa byte của code đã khóa có thể làm chain từ chối mở.

## Đợt dọn repo và Git

Nhánh bàn giao là `codex/pipeline-v2-handoff`, sau đó cập nhật `main` tới cùng commit. Dọn phần triển khai/thử nghiệm cũ ở `knowledge_base`, `research_bundle`, `kos_sample`, root `tests`, các `author_batch_*.py`, hướng dẫn bàn giao cũ và IDE files. Giữ 11 exposure manifests tại đường dẫn gốc trong `knowledge_base/pipeline_v1/` vì M0 vẫn bind chúng. Ba tài liệu nghiên cứu liên quan được đưa sang `pipeline_v2/docs/research/`. Giữ toàn bộ code/config/artifact/review thuộc V2 và `.codex` điều phối.

Các artifact V2 khoảng 14,3 GB giữ local và Git ignore, cùng `data/`, môi trường và secrets. Code, tài liệu, review và tokenizer vendor được đưa vào Git. `.gitattributes` giữ nguyên bytes dưới `pipeline_v2/` để bảo toàn hashes. Sau cleanup, Main đã chạy `unittest discover` đạt 204/204 tests trong 19,926 giây. Đối chiếu commit/receipt cuối của nhánh để biết kết quả kiểm bổ sung.

## Chuẩn bị máy mới

Clone nhánh bàn giao hoặc `main` đã cập nhật. Dùng checkout ngắn trên Windows và chạy từ repo root.

```powershell
git clone -c core.longpaths=true https://github.com/ducvan1909/coliee-case-retrieval.git
Set-Location coliee-case-retrieval
git rev-parse --show-toplevel
git status --short
py -3.12 -m venv .venv
& .venv/Scripts/python.exe -m pip install -r pipeline_v2/requirements-m3-local.txt
```

Requirements local pin NumPy 2.4.4, Modal 1.5.3, requests 2.33.1 và tokenizers 0.22.2. Torch/Transformers chạy trong image Modal đã khóa. Tạo lại `.venv` trên máy mới.

Git không chứa toàn bộ runtime lớn và secrets. Chuyển riêng các thư mục sau từ máy cũ, bảo toàn đường dẫn tương đối và raw bytes.

1. `data/` chuẩn, đặc biệt raw train và nhãn evaluator.
2. Toàn bộ `pipeline_v2/artifacts/` để giữ chain M0→M3, pilot compatibility, cache và accounting. Không chỉ copy sparse index.
3. Kiểm đủ tokenizer assets trong `pipeline_v2/vendor/` theo lock sau clone.
4. Kiểm đủ evidence/review được code dẫn chiếu, đặc biệt full verify receipt.
5. Dữ liệu Qdrant Docker chuyển riêng bằng snapshot/backup nhất quán. Named volumes là `coliee_pipeline_v2_qdrant_storage_v1` và `coliee_pipeline_v2_qdrant_snapshots_v1`. Dừng writer trước backup, kiểm restore trên máy mới.

Compose mới tạo server/volume trống. Có thể nạp lại collection bằng quy trình cache-only bên dưới. Đây là script vận hành dùng các adapter hiện có, chưa có CLI restore riêng. Trước hybrid thật phải khôi phục collection rồi verify so cache. Không chạy `m3_full run` để thử khi chưa kiểm đầy đủ cache, vì đường đó có thể gọi model cho batch thiếu cache. Helper restore pilot có giới hạn RAM khi áp cho full corpus, xem M3_FULL.md.

Nếu cần auth Modal, copy `pipeline_v2/.env.example` thành `pipeline_v2/.env` rồi nhập credential local, hoặc dùng SDK profile đã đăng nhập. Không commit `.env` hay in token. Tên app hiện hành lấy từ `configs/m3_full.json` và `m3_opt_v2.json`; tài liệu pilot lịch sử có app khác.

Runtime chính dùng repo root tương đối. Đường dẫn `E:/...` trong receipts/script review là lịch sử máy đo. Không chỉnh receipts, seals hoặc raw để đổi ổ đĩa. Nếu script review hardcode đường dẫn, tạo script review mới dùng root mới và ghi rõ. Guard báo drift sau copy thì kiểm thiếu file, line endings và SHA-256 trước khi tiếp tục.

## Kiểm tra sau chuyển máy

Fixture tests chạy trước, không cần Docker/Modal.

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m3_sparse_index pipeline_v2.tests.test_m3_lexical_reader pipeline_v2.tests.test_m3_hybrid_dense pipeline_v2.tests.test_m3_hybrid_fusion -v
& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse --help
```

Sau khi copy đủ raw/artifacts/vendor, thử lexical local. Mở session kiểm snapshot nên có thể mất hàng chục giây.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse search --channel passage --query "standard of review" --query-case 095448.txt --limit 100 --unique-cases
```

Sau khi Docker Engine chạy và collection đã restore, kiểm schema/count rồi diagnostic dùng vector cache. Các lệnh này không cần Modal.

```powershell
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml up -d
Invoke-RestMethod -Uri http://127.0.0.1:6333/collections/coliee_m3_full_ef2f4d6950a5b9fd
& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse diagnostic-hybrid --query "standard of review" --query-case 095448.txt --passage-id 095448:88b488d43fde1389756a8dd7
```

Full DB verification kiểm đủ 415.693 vectors/payload/IDs, mất khoảng 25 phút trên máy cũ. Chạy một lần sau restore, lưu stdout và exit code vào review mới.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_full verify --run-dir pipeline_v2/artifacts/m3_full_train_20261108_v1
```

## Khôi phục chi tiết từ artifacts local và cache đặt ở root

Quy ước trên máy mới là đặt vector cache tại `cache/vectors/` ở root repo. Nếu người dùng đặt tên khác, Codex hỏi tên hoặc kiểm inventory rồi sửa đường dẫn nguồn trong lệnh copy. Runtime vẫn đọc tại `pipeline_v2/artifacts/m3_full_train_20261108_v1/vectors/`. Chuyển cache về vị trí runtime bằng copy bảo toàn bytes, giữ bản nguồn ở root cho đến khi nghiệm thu xong. `cache/` và `restore_input/` đã được Git ignore.

### Chuẩn bị gói từ máy cũ

Dừng các writer trước khi copy, gồm full ingestion, benchmark có ghi ledger và mọi tiến trình đang sửa artifact. Nếu có SQLite WAL, để ứng dụng đóng kết nối bình thường trước khi copy toàn thư mục. Giữ cả file phụ còn tồn tại, tránh lấy riêng DB đang được ghi.

```text
<repo-moi>/
  cache/
    vectors/                       # 6.496 .npz + 6.496 .json, nguyên tên file
  restore_input/
    artifacts/                     # copy cây pipeline_v2/artifacts từ máy cũ
      m0_20261105_v2/
      m1_20261105_v2/
      m2_navigation_20261106_v3/
      m2_passages_20261106_v1/
      m3_pilot_20261106_l4_v1/
      m3_opt_v2_index_20261108_v1/
      m3_opt_v2_compat_20261108_v1/
      m3_full_train_20261108_v1/     # giữ manifest, seal, lexical, ledger, execution state...
      m3_sparse_20261110_v1/
      ...                          # giữ các checkpoint khác nếu chuyển toàn bộ
  data/                            # dữ liệu chuẩn copy riêng
```

Nếu đã tách `vectors/` sang `cache/vectors/`, có thể bỏ bản vector trùng trong gói `restore_input/artifacts/` để giảm dung lượng vận chuyển. Giữ mọi file khác của full run, đặc biệt `manifest.json`, `seal.json`, `lexical.sqlite3`, `execution_state.json`, `ledger.sqlite3` và lịch sử invocations/receipts. Giữ chain pilot compatibility trong bảng phía trên. Clone Git đã chứa vendor tokenizer, review receipt và 11 exposure manifests.

Kiểm trên máy cũ ngày 10/11/2026 xác nhận cache còn 6.496 `.npz` tổng 4.422.922.572 bytes và 6.496 `.json` tổng 43.219.233 bytes. Tổng 4.466.141.805 bytes, khoảng 4,16 GiB. Ledger có 6.496 committed batches, 6.496 success attempts và 1 started attempt lịch sử. Số lượng là kiểm inventory, bước kiểm SHA-256 theo schedule ở dưới mới xác nhận nội dung.

Chỉ vector cache không đủ tái tạo nguyên checkpoint hiện tại. Các manifest, metadata/schedule, upstream source bundles và compatibility receipts cần được chuyển cùng. Nếu thiếu, Codex liệt kê phần thiếu và dựng revision mới có nghiệm thu khi được giao. Không tự tạo receipt thành công, sửa seal hoặc chỉnh hash để nối snapshot mới vào lịch sử cũ.

### Copy về vị trí runtime

Chạy PowerShell từ root repo sau khi clone và cài môi trường. Ví dụ này yêu cầu đích artifacts mới, tránh trộn với một run đã có.

```powershell
$artifactSource = Join-Path (Get-Location) 'restore_input/artifacts'
$artifactTarget = Join-Path (Get-Location) 'pipeline_v2/artifacts'
if (!(Test-Path -LiteralPath $artifactSource -PathType Container)) { throw 'Thieu goi artifacts nguon' }
if (Test-Path -LiteralPath $artifactTarget) { throw 'Dich da ton tai. Kiem inventory/hash truoc khi merge, khong ghi de tu dong.' }
robocopy $artifactSource $artifactTarget /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
if ($LASTEXITCODE -ge 8) { throw 'Copy artifacts that bai' }

$vectorSource = Join-Path (Get-Location) 'cache/vectors'
$vectorTarget = Join-Path $artifactTarget 'm3_full_train_20261108_v1/vectors'
if (!(Test-Path -LiteralPath $vectorSource -PathType Container)) { throw 'Thieu cache/vectors' }
if (!(Test-Path -LiteralPath $vectorTarget)) {
    robocopy $vectorSource $vectorTarget /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
    if ($LASTEXITCODE -ge 8) { throw 'Copy vectors that bai' }
} else {
    Write-Output 'Dich vectors da co tu goi artifacts. Kiem cache theo schedule o buoc tiep theo.'
}
```

Nếu artifacts đã có local trên máy mới, bỏ bước copy artifacts. Chỉ thêm `vectors/` khi đích chưa có. Khi đích chứa cache dở, giữ evidence và đối chiếu hash từng file trước khi bổ sung từ nguồn. Không dùng `/MIR`, không xóa run hoặc ledger để xử lý lỗi copy.

### Kiểm đầy đủ cache trước khi ghi Qdrant

Đoạn sau chỉ đọc snapshot và cache. Nó kiểm toàn bộ schedule, SHA-256 của từng `.npz`, metadata, IDs, input hashes, fingerprint, shape và vector norms qua adapter đã có. Thiếu/hỏng bất kỳ batch nào sẽ dừng bằng lỗi. Chạy từ root repo, chờ hoàn tất, giữ stdout và exit code nếu cần báo cáo chuyển máy.

```powershell
@'
from pathlib import Path
from pipeline_v2.full_corpus.runner import load_plan, batches
from pipeline_v2.full_corpus.storage import ReadonlyCache

root, run, manifest, lexical = load_plan(
    Path.cwd(), 'pipeline_v2/artifacts/m3_full_train_20261108_v1')
try:
    cache = ReadonlyCache(run, manifest['embedding_fingerprint'],
                          manifest['profile']['embedding']['dimensions'])
    batch_count = point_count = 0
    for number, docs in batches(lexical):
        values = cache.get_batch([p['passage_id'] for p in docs],
                                 [p['exact_input_sha256'] for p in docs])
        if values is None:
            raise RuntimeError(f'Missing cache batch {number}')
        batch_count += 1
        point_count += len(docs)
    if (batch_count, point_count) != (6496, 415693):
        raise RuntimeError('Unexpected full cache coverage')
    print({'status': 'PASS', 'batches': batch_count,
           'points': point_count, 'model_requests': 0})
finally:
    lexical.close()
'@ | & .venv/Scripts/python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Cache audit that bai. Dung khoi phuc DB.' }
```

`load_plan` cũng kiểm source hashes, full seal và compatibility chain. Vì vậy lỗi thiếu M0/M1/M2/pilot assets phải được giải quyết trước khi dùng full cache. Giữ nguyên đường dẫn tương đối khi đổi ổ hoặc tên thư mục checkout.

### Khởi động Qdrant và nạp lại từ cache

Mở Docker Desktop Linux Engine. Cấu hình Compose đã có image Qdrant 1.20.0, cổng loopback 6333/6334 và hai named volumes. Chạy `docker compose ... up -d` như mục trên, sau đó kiểm API. Nếu dùng DB backup đã restore và full verify PASS thì bỏ bước nạp lại này.

Script bên dưới chỉ dùng `ReadonlyCache`, `FullQdrant` và các hàm kiểm snapshot. Nó kiểm hết cache trước khi tạo/sửa collection, rồi upsert theo batch 64. Nó không khởi tạo embedder hoặc gọi hàm inference. `run_lock` tránh writer cùng run của repo. Dừng mọi writer DB khác trong thời gian restore. Script tạo lock DB nếu chưa có, dữ liệu vector và lịch sử usage được đọc nguyên trạng. Log tiến độ ở console, nếu bị ngắt có thể chạy lại để bỏ qua các batch đã khớp DB.

```powershell
@'
from pathlib import Path
from pipeline_v2.full_corpus.runner import (
    load_plan, batches, make_store, guard, verify_batches)
from pipeline_v2.full_corpus.storage import ReadonlyCache
from pipeline_v2.retrieval.cache import run_lock

root, run, manifest, lexical = load_plan(
    Path.cwd(), 'pipeline_v2/artifacts/m3_full_train_20261108_v1')
try:
    cache = ReadonlyCache(run, manifest['embedding_fingerprint'],
                          manifest['profile']['embedding']['dimensions'])
    with run_lock(run):
        count = 0
        for number, docs in batches(lexical):
            values = cache.get_batch([p['passage_id'] for p in docs],
                                     [p['exact_input_sha256'] for p in docs])
            if values is None:
                raise RuntimeError(f'Missing cache batch {number}')
            count += len(docs)
        if count != manifest['passages']:
            raise RuntimeError('Cache coverage differs')
        guard(root, manifest)
        store = make_store(manifest)
        if store.server_info()['version'] != manifest['profile']['qdrant']['version']:
            raise RuntimeError('Qdrant version differs')
        store.ensure()
        store.validate_existing(lexical)
        if store.count() > manifest['passages']:
            raise RuntimeError('Unexpected collection count')
        upserted = skipped = 0
        for number, docs in batches(lexical):
            guard(root, manifest)
            values = cache.get_batch([p['passage_id'] for p in docs],
                                     [p['exact_input_sha256'] for p in docs])
            if values is None:
                raise RuntimeError(f'Cache disappeared at batch {number}')
            if store.matches(docs, values):
                skipped += 1
            else:
                store.upsert(docs, values)
                upserted += 1
            if number % 100 == 0:
                print({'batch': number, 'upserted': upserted,
                       'skipped': skipped, 'model_requests': 0}, flush=True)
        guard(root, manifest)
        result = verify_batches(lexical, cache, store, manifest)
        print({**result, 'upserted_batches': upserted,
               'skipped_batches': skipped, 'model_requests': 0}, flush=True)
finally:
    lexical.close()
'@ | & .venv/Scripts/python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Restore Qdrant that bai. Giu log va resume sau khi sua nguyen nhan.' }
```

Nếu DB có ID/payload/vector khác snapshot, adapter sẽ báo lỗi. Giữ nguyên collection để kiểm tra, không xóa tự động. Cache thiếu/hỏng phải lấy lại file từ máy cũ hoặc bản backup. Một lần restore có thể mất nhiều phút đến hàng chục phút, riêng full verify trước đây khoảng 25 phút. Tránh để Windows sleep khi chạy.

Đây là đoạn hướng dẫn mới, đã kiểm cú pháp Python nhưng chưa chạy restore thật trong đợt cập nhật tài liệu. Codex trên máy mới cần thử một collection tạm bằng fixture/cache nhỏ trước khi chạy toàn bộ nếu chuyển thành tool production. Sau restore, chạy CLI `m3_full verify` và diagnostic hybrid ở mục kiểm tra sau chuyển máy, lưu evidence mới. Chỉ chốt phục hồi khi full verify PASS đủ 415.693 points và diagnostic có provenance đúng.

### Khi thiếu artifact ngoài vector cache

M0, M1, navigation, passages và lexical/sparse indices có code dựng local. Tuy nhiên rebuild có thể thay manifest, elapsed time, collection identity và seals, làm chain hiện tại từ chối mở. Dựng vào output mới, kiểm lại theo milestone và tạo revision/config/receipt mới khi cần. Chỉ riêng cache gốc không phục hồi được lịch sử ledger hoặc chứng nhận compatibility bị mất. Nếu mất cache vector thì việc tạo lại vector cần Modal và một run trả phí được người dùng/AG thực hiện.

Ưu tiên lấy đủ artifact đã có trên máy cũ, chuyển cache vào root như quy ước, copy về vị trí runtime và kiểm hash. Giữ gói nguồn cho đến khi full cache audit, DB verify và diagnostic hoàn tất.

## Việc Codex tiếp tục làm

Đọc `docs/plan/M3_FULL_SEARCH.md`, `reviews/m3_full_search_plan_ag_review_v1/` và review sparse. Draft full-search còn mô tả lựa chọn đã điều chỉnh trong code, như dense một request exact top 4.096. Chốt decision delta trước triển khai phần còn lại, giữ policy các kênh đã nghiệm thu.

1. `search_case` và query-reading helpers `case_map`/`case_anchors`. Tìm trong án đã biết, cho phép đọc query case, trả handles/preview/coverage có provenance.
2. `search_phrase` trên raw stream xuyên ranh giới chunk. Khóa matching mode, Unicode casefold mapping, char↔UTF-8 byte offsets, repeated matches và cursor. Mọi hit round-trip đúng raw bytes.
3. `search_identity` cho tên/citation quan sát được, kèm raw source spans và method version. Giữ rõ lead chưa xác minh danh tính.
4. `open_source` đọc M2 JSON đã seal, mở full parent + neighbors, dedup raw intervals, byte budget/pagination và requested/delivered/pending. Tránh tokenize/rebuild cả case chỉ để mở hit. Agent token budget áp ở M4.
5. AG kiểm local các công cụ mới. Codex chuẩn bị manifest/lệnh cho một query embedding thật qua Modal bằng `m3_sparse search-hybrid`; người dùng/AG chạy, lưu latency/usage/errors, Main nghiệm thu để chốt M3.

Khi tích hợp harness, giữ session xuyên nhiều tools. Guard hiện lặp khoảng 7 lần mỗi hybrid query, có thể gom tại biên request nếu tests vẫn bắt drift/invalidation. `revalidate()` mở session thứ hai tạm thời, cần tính thêm catalog heap khi chạy nhiều worker. AG đã ghi hai mục này non-blocking.

Sau M3 mới triển khai M4 rồi M5–M7 theo plan. Chưa tự chốt controller model/tokenizer/budget, threshold selector, reranker, approximate dense policy hoặc tune trên holdout. Giữ request/token/latency cả lỗi và retry. Báo đúng phạm vi nghiệm thu engineering và đánh giá nhãn.

## Prompt mở đầu cho Codex mới

> Đọc CODEX_HANDOFF.md và AGENTS.md. Kiểm checkout, commit, runtime assets và fingerprints thực tế. Tôi đặt vector cache ở cache/vectors/ tại root repo. Dùng mục khôi phục chi tiết để copy artifacts/cache về đúng vị trí, kiểm đủ cache và phục hồi Qdrant local bằng cache-only khi DB chưa có. Kiểm script bằng collection tạm trước khi dùng full, ghi báo cáo restore riêng và giữ nguyên ledger lịch sử. Báo phần đã phục hồi, phần thiếu và tiến độ M0–M7. Sau đó chốt decision delta của M3 full-search rồi triển khai search_case/case_map/case_anchors, phrase/identity và open_source theo thứ tự phụ thuộc. Giữ modules/config/artifacts đã bind hash, thêm revision/module mới khi cần. Dùng implementer và tester theo AGENTS.md. Chuẩn bị lệnh Modal để tôi hoặc AG chạy. Thiếu data/DB chỉ chặn kiểm tích hợp tương ứng, vẫn tiếp tục code và fixture tests làm độc lập được.
