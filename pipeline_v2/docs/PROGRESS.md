# Tiến độ pipeline_v2 ngày 12/11/2026

## CM4 — 23/11/2026, phân biệt kết thúc partial với complete

Final còn unresolved search query hoặc deferred pair trả `stop_reason=partial` và `review_status=partial_with_unresolved_queries` / `partial_with_deferred_pairs`. Giữ prediction đã có, selection status và provenance; không kích baseline fallback khi đổi nhãn. Host citation matches vẫn được ghép vào prediction của run partial. Run xét xong giữ `complete`; lỗi/budget giữ trạng thái riêng. Chỉ áp dụng run mới, không sửa ledger/báo cáo lịch sử. Prepare namespace mới do code binding thay đổi.

Kiểm local bản production cuối: smoke engine/offline terminal/citation 36/36 đạt. Suite liên quan 67 ca có 66 đạt, một kỳ vọng cũ về prediction khi thiếu selector đã sửa; chạy lại ba regression sau sửa đều đạt (unresolved và mở lại, deferred, host citation partial). Kiểm diff với CRLF đạt. Không gọi inference/deploy; chưa có kết quả COLIEE mới.

## CM4 — 23/11/2026, ngân sách permit và evaluator CM4

Host kiểm toàn bộ query sau render instruction/special tokens/EOS bằng tokenizer embedding pin trước khi ghi permit. Nhóm vượt cap được chia lại, giữ nguyên text, hash, offsets và citation provenance; span đơn quá cap trở về unresolved để sửa. Regression nhóm 454 token tách 2+1 và thực thi, biên 448/449, citation provenance và fit lặp đều đạt. Live dùng embedding profile từ manifest; không cắt nguồn âm thầm.

Evaluator v2 nhận cả run root và session, freeze ledger cùng journal/diagnostics/reranker receipts, nối action cha–nhánh theo fingerprint của truy vấn durable và kiểm kết quả branch. Báo riêng hybrid pool 50, scored passages, top 10 passage, B duy nhất, kết luận định danh do model suy luận, pending và prediction precision/recall/F1. Prediction chưa có giữ unavailable/null; thiếu diagnostics giữ recall chưa xác định. Có thống kê reranker cùng controller/embedding usage.

Kiểm local bằng `.venv/Scripts/python.exe`: **87/87 PASS** cho cap, source gate, survey, passage, live, tool repair, evaluator và retrieval diagnostics; regression evaluator riêng sau review **6/6 PASS**. Bản sửa cap/evaluator còn được kiểm với implementation dual_search ở HEAD trước thay đổi đồng thời về reranker. Artifact thật `cache/cm4-query-review-v30-ag-20261120-105534942` freeze/score qua cả root/session đồng nhất: 3 diagnostics verified, 3 embedding requests lịch sử, 0 unknown attempt, prediction unavailable. Không gọi inference/deploy mới; chưa có artifact source-bound/reranker live local, chưa kết luận cải thiện COLIEE. Prepare namespace mới trước pilot vì code binding thay đổi.

## CM4 — 23/11/2026, đồng nhất truy vấn source-bound cho reranker

`DualSearch` truyền nguyên `source_query_text` đã kiểm nguồn/hash cho reranker trong nhánh `source_bound`, cùng chuỗi retrieval nhận: anchor và các citation/group members scoped được ghép thêm. Nhánh dual-query cũ giữ truy vấn rerank nguyên văn anchor. Giữ nguyên passage pool, top-k và kiểm provenance.

Kiểm local bằng `.venv/Scripts/python.exe -m unittest pipeline_v2.experiments.context_manager_v2.tests.test_dual_search pipeline_v2.experiments.context_manager_v2.tests.test_passage_review`: **32/32 PASS trong 52,248 giây**. Regression kiểm truy vấn hai bước trùng nhau khi có/không có supports và từ chối support lệch nguồn trước retrieval/rerank. Không gọi inference/deploy; chưa có số đo recall/F1 mới. Prepare namespace mới trước pilot vì code binding thay đổi.

## CM4 — 23/11/2026, tự cấp vùng A kế tiếp

Profile `--survey-first` cấp thẳng nguyên văn khi bắt đầu và khi vùng hiện tại đã xét xong. Host dùng cây nguồn và giới hạn context để chọn vùng còn việc, lưu lựa chọn ở admission và dùng lại khi replay. Model vẫn được chọn cách xử lý mục chưa đủ ngữ cảnh. Preflight `cache/cm4-auto-survey-nav-local-20261123-151440587` mở trực tiếp `[0, 929)` của `021095.txt` với 6.546 input token và 0 request inference. Replay local ghi quyết định cho [1] rồi nhận thẳng vùng `[929, 2551)`; ledger chỉ có action đánh giá A, coverage giữ nguyên khi vùng mới vừa được cấp. Pilot cũ đã dừng với `operator_stop_file`; namespace mới cần để kiểm hiệu quả live. Xem [mục 5.5 của kế hoạch](plan/CM4_SOURCE_BOUND_SEARCH_IDENTITY.md#55-cấp-thẳng-nguyên-văn-a-ở-bước-điều-hướng-xác-định-được).

## CM4 — 23/11/2026, profile khảo sát A trước

Triển khai mục 5–9 của [kế hoạch](plan/CM4_SOURCE_BOUND_SEARCH_IDENTITY.md). Profile `--survey-first` chờ hoàn tất khảo sát A rồi cấp quyền tìm. Batch nhận tối đa ba quyết định theo ref. Receipt Modal `finish_reason=length` đã xác thực và chưa có action cho phép giảm nhóm 3 → 2 → 1, giữ coverage và hàng chờ. Lượt chốt B ánh xạ nhãn do model trả và tự hiện trang ứng viên sau commit. Đường chốt citation duy nhất ghi trực tiếp vào kết quả, kiểm bằng fixture. Corpus thật có 7.708 file, chưa thấy header đạt quy tắc tự định danh hẹp. `--profile-timing` thêm thời gian các khâu và thống kê. Trần hiện dùng 1.024 token. Kết quả local/preflight là mốc kỹ thuật trước pilot AG.

Preflight `cache/cm4-survey-first-local-20261123-115942490` dùng đúng code binding, bắt đầu ở pha khảo sát với 3.270 input token và 0 request controller, embedding hay reranker. Dựng payload đầu mất 4,08 giây, trong đó 7 lần mở vùng A thử chiếm 2,66 giây. Ba phép đo local cho mỗi chế độ trên cùng payload đầu cho trung vị 4,42 giây khi tắt timing và 4,56 giây khi bật. Mẫu nhỏ chỉ kiểm chi phí ở preflight. Chưa quy được nguyên nhân của các đỉnh T181–T182 và T214–T215 trong run live.

Kiểm local bản cuối đạt 194/194 test CM4 và 35/35 test timing, transport và hybrid. Ca [5]/[18] trên byte gốc xác nhận host gom các span Hargrave đã được xác nhận cùng nguồn và giữ hai khối trích riêng với citation scoped. Các test dùng quyết định được script. Cần pilot AG để xác nhận model tự tạo đúng nhóm, mức giảm request và độ chính xác định danh.

## CM4 — chọn phạm vi A và hiển thị đủ shortlist B

Pilot `cache/cm4-identity-commit-fix-ag-20261122-181709912` ghi thành công `070847.txt = select` ở T035. Sau đó run dừng vì model qua lại giữa hai bản đồ A. Payload T045 gợi ý mở vùng chưa xét nhưng ref trỏ lên bản đồ toàn án. Bản sửa lọc lối lên khỏi catalog và schema khi bản đồ hiện tại có vùng con chứa byte chưa xét. Khi không còn lối xuống cho phần chưa xét, host cấp lại lối lên để model tiếp tục vùng khác. Chưa chạy live bản sửa điều hướng.

Pilot `cache/cm4-identity-first-ag-20261122-165805297` cho thấy model nhận mở đầu Hargrave của `070847.txt` ở T033, yêu cầu kiểm định danh ngay và trả `select` ở T034. Host từ chối ghi vì cùng ref [0, 900) xuất hiện hai lần với nhãn provenance khác nhau. AG đặt STOP sau 38 request, run chưa có prediction. Đã đồng nhất kiểu span khi kiểm trùng và mở rộng regression local tới lúc ghi quyết định. Pilot đã dừng giữ nguyên kết quả lịch sử.

CM4 bật reranker đưa tối đa 900 byte đầu của B vào lượt mở án và nhắc model đối chiếu định danh trước. Dòng metadata nhận diện được là gợi ý bổ sung. Model có thể đọc thêm hoặc để pending, và chỉ yêu cầu lượt kiểm định danh cuối khi định chọn B. Kiểm local trên nguyên văn `070847.txt` và `011064.txt` xác nhận phần mở đầu được cấp đúng vai trò, còn đoạn B trích Aqua-Gem chỉ được cấp làm bằng chứng về quy tắc. Thay đổi này đang ở mức kiểm local, chưa có kết quả inference live.

Pilot `cache/cm4-source-span-page-check-20261122-111459932` xác nhận live quay về A hai lần, dừng theo yêu cầu sau 59 request và 58 action. [2] được xét theo mục nhưng model vẫn phân loại hai căn cứ (a)/(b) thành facts. Model nhận đủ thẻ trước khi đóng cả hai lượt tìm. Ở lượt thứ hai, `070847.txt` lên đầu sau rerank và được mở nhưng model chốt không chọn. Host thiếu nhận diện chức danh Prothonotary ở phần mở đầu nên chưa cấp lượt kiểm định danh. Đã bổ sung mẫu mở đầu này và kiểm trên nguyên văn `070847.txt`: 20/20 test passage review đạt. Pilot cũ chưa có kết luận định danh hay prediction cuối.

Sau pilot dừng ở T028, regression local xác nhận `search → conclude_search_query → prepare` quay lại A với đúng ref và byte span. Nhánh khóa nguyên văn không cấp ref `remaining_visible` khi phần paragraph hiển thị có mục dạng `(a)`, `(b)` đứng đầu dòng. [1] của `021095.txt` vẫn có ref gộp. [2] vẫn có ref từng mục.

Trong luồng passage review, model được mở passage B từ trang đang có. Trước khi kết thúc lượt tìm, model phải nhận các trang thẻ còn lại. Payload chỉ rõ số thẻ chưa hiện, số B còn pending và ref mở thẳng trang chưa hiện tiếp theo. Các án chưa mở nguyên văn có thể giữ pending khi kết luận partial. Regression kiểm cả giao thẻ trang sau, lưu pending và quay về A.

Kiểm local 28/28 test passage review và span recovery, 33/33 test query review và live orchestration. Preflight `cache/cm4-source-span-page-check-20261122-111459932` dựng payload đầu 3.258 token và phát 0 request inference. AG dùng namespace này để xác nhận đường quay về A trên pilot.

## CM4 — phục hồi chọn span, 22/11/2026

Pilot `cache/cm4-source-span-recovery-ready-20261122-094355232` qua được [1] → [2] và search đầu tiên, với 27 reply hợp lệ. Sau khi chốt 4 án không chọn và kết thúc search ở T027, host crash khi dựng T028 vì source need thiếu `a_paragraph`. Đã tái hiện bằng regression search → conclude → prepare, rồi bổ sung metadata paragraph từ permit. Pilot cũ chưa có prediction. `070847.txt` đã vào shortlist nhưng chưa được mở, nên chưa có lượt kiểm định danh B.

Toàn suite đạt **171/171 PASS** trên bản trước chỉnh cuối bộ lọc catalog. Sau chỉnh bộ lọc, kiểm lại 58 test liên quan và replay T008/T020.

Đã sửa vòng lặp `no_search_needed` thiếu span ở đoạn [1] của `021095.txt`. Schema bắt buộc ref hoặc quote cho hai quyết định kết thúc. Ref `remaining_visible` ghi đúng từng khoảng chưa xét. Quote lệch đưa ref nguyên văn để xác nhận. LoopGuard đếm hợp byte mới đã xét và giữ tiến triển qua replay ledger. Reply thiếu span được ghi là schema reject; host cấp một lần sửa cùng phạm vi rồi dừng nếu lỗi lặp lại.

Kiểm liên quan trên bản cuối **58/58 PASS**. Replay reply thiếu selector cấp đường phục hồi, rồi xét [0,239), [239,285) và phần còn lại [285,927) để đóng đúng [1]. Replay nguyên văn T008/T020 xác nhận ref gợi ý hiện cả trong catalog và schema, chỉ ghi phạm vi sau khi chọn. Test LoopGuard xác nhận 239 → 285 byte và đổi lời hoặc lặp byte không tăng độ phủ. Preflight `cache/cm4-source-span-recovery-ready-20261122-094355232` khớp binding, cap 1.024, input 3.258 token, 0 request inference ở cả ba dịch vụ. Mốc live tiếp theo là tự qua [1] sang [2], rồi kiểm permit/search và định danh B. Xem [kế hoạch](plan/CM4_SOURCE_SPAN_LOOP_RECOVERY.md).

## CM4 — khóa nguyên văn A và kiểm định danh B, 22/11/2026

Đã nối hai bước mới vào profile live bật reranker. A ghi quyết định theo span, đính lời dẫn/citation theo vai trò, cấp permit chỉ chạy nguyên văn đã khóa và giữ đường đọc lại phần chưa xét. Thử nghiệm đầu dùng một nhánh nguồn, không nhân đôi RRF. B có lượt kiểm định danh riêng trước select, với ref A, tự định danh B và passage quy tắc trong B. Kết luận vẫn khóa một lần theo lượt tìm và B.

Toàn suite CM4 trên bản cuối đạt **163/163 PASS trong 135,673 giây** bằng `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests`. Local preflight `cache/cm4-source-bound-local-check-20261122-010201972` dựng payload đầu 3.233 token, 0 request đến cả ba dịch vụ. Kiểm trực tiếp nguyên văn pilot xác nhận heading `[9151,9170)` và phân biệt phần mở đầu `011064.txt` với thân [37] khi cấp vai trò tự định danh. Kế hoạch, ca kiểm và giới hạn nhận diện header/closing ở [CM4 source-bound](plan/CM4_SOURCE_BOUND_SEARCH_IDENTITY.md). Recall và độ chính xác ngữ nghĩa cần đối chứng live.

## Sửa schema xgrammar — 21/11/2026

Pilot `cache/cm4-final-once-20261121-160727278` dừng ở T030 khi schema `conclude_candidate` chứa `uniqueItems`, bị backend xgrammar từ chối trước sinh token. Đã bỏ keyword này khỏi ba mảng ref gửi model; giữ nguyên kiểm trùng `a_refs`, `b_refs`, `identity_refs` ở host và khóa kết luận một lần. Regression kiểm schema không có keyword, cả ba ca ref trùng qua được schema nhưng bị host từ chối, không ghi kết luận lỗi, và ref hợp lệ vẫn chọn được B. Nhóm passage/live/dual đạt **36/36 PASS, 14,826 giây**. Local chưa cài xgrammar, nên chưa biên dịch schema trực tiếp bằng backend; cần AG chạy namespace mới để xác minh live. Không inference/deploy trong đợt sửa.

## CM4 passage review v3 — 21/11/2026, một kết luận cho B trong lượt tìm

Đã thay chấm/sửa phiếu từng hit bằng `conclude_candidate` đúng một lần cho mỗi `(search_query_id, case_id B)`. Trước khi chốt, mặc định không chọn nhưng pending; rời tạm không tạo nhận định phủ định. Chốt select cần evidence A/B và định danh B theo ref được giao; chốt không chọn không bắt đọc hết nhóm. Schema bỏ tool kết luận sau chốt và host từ chối nộp lại/đổi nhãn, kể cả mở lại hoặc dựng lại Engine từ ledger. Vẫn cho đọc tiếp, rời và mở lại, chỉ tự gom hit trong top 10. Kết luận âm ở query khác không xóa phiếu dương đã khóa; tiến độ từng query giữ riêng.

`read_case_passages` kiểm tối đa 3 kết quả bằng hash/span/receipt, phân biệt `new_content`, `already_read`, `no_hits`; kết quả có phần mới mở từ gap chưa giao đầu tiên, không đọc lại prefix cũ vì reset cursor. `revisit_case_passage` mở lại kết quả cũ có chủ đích. Cảnh báo tiến độ không tính đổi focus/lý do là nội dung mới. `read_passage_attribution` giữ tool nhưng mô tả/nhãn đúng là ngữ cảnh ±1.200 byte để model kiểm tra, không khẳng định host nhận diện attribution.

Kiểm local: toàn suite CM4 **158/158 PASS, 127,940 giây**; sau bổ sung kiểm metadata để không gán relation giả cho kết luận âm thiếu evidence, nhóm passage/live/dual đạt **35/35 PASS, 14,372 giây** trên bản cuối. Test phủ khóa một lần cả hai nhãn, nhiều hit chung một kết luận, rời pending, resume, ref sai, top 10, tìm hit đầu cũ/hit sau mới, overlap, đuôi mới sau prefix dài, no-hit, nguồn sai và kết luận qua nhiều query cùng need. AST/prompt được kiểm local.

Review độc lập phát hiện hai lỗi (tiến độ liên query và cursor prefix cũ), đã sửa và có regression. Replay chỉ đọc đúng raw reply T045 của `cache/cm4-grouped-reading-20261121-113512216` xác nhận schema v3 từ chối `assess_passages`; sau chốt không còn tool kết luận. Đây là kiểm wiring, không chứng minh model live tự phục hồi hoặc F1. Agent implementer/reviewer chạm usage limit trước báo cáo cuối; Main nghiệm thu trực tiếp bằng code và test. Không inference/deploy mới; AG cần prepare namespace mới. Contract/tài liệu: [kế hoạch](plan/CM4_DUAL_QUERY_RRF_RERANK.md), [CM4](../experiments/context_manager_v2/CM4.md).

## CM4 passage review — 21/11/2026, đọc theo án do model điều khiển

Theo chỉ đạo mới, nhánh dual-query/rerank gom passage theo án **chỉ từ top 10 hit đã giữ**, không bổ sung passage từ pool rerank. Model mở trực tiếp một án từ thẻ kết quả, không phải survey hết hoặc gán ưu tiên trước. Gói đọc giữ span A, định danh/giới thiệu B và các vùng passage cùng B theo thứ tự nguồn; vùng chồng lấn được hợp, vùng dài có continuation.

Model quyết định đọc tới đâu, đánh giá, đọc thêm ngữ cảnh hoặc dùng `return_to_candidates` để rời án đang mở và mở lại sau. Phiếu `select` không tự đóng án; phần chưa đọc/chưa đánh giá vẫn được ghi riêng. Có thể kết luận query khi còn ứng viên dang dở và host phải lưu trạng thái partial tương ứng. Trạng thái/cảnh báo tiến độ được giao trong payload passage review. Nhánh CM4 không bật reranker giữ contract survey cũ.

Phạm vi đợt này là code và kiểm offline, không inference/deploy Modal. Chi tiết: [kế hoạch dual-query/rerank](plan/CM4_DUAL_QUERY_RRF_RERANK.md). Các checkpoint dưới đây giữ bằng chứng lịch sử; kiểm local không chứng minh chất lượng liên kết A→B hoặc F1.

Kiểm bản cuối ngày 21/11: `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests` đạt **152/152 PASS trong 129,995 giây**, không gọi provider. Nhóm passage review có 9 test, bao gồm chỉ gom top 10 và loại hit thứ 11 trong pool, hợp vùng/thứ tự nguồn, continuation, rời/mở lại đúng vị trí, giữ án sau `select`, thu hồi phiếu dương qua nhiều trang, partial conclusion và cảnh báo/lỗi trong payload. Kiểm prompt và whitespace/conflict trên các file thay đổi đạt; `git diff --check` không chạy được trong môi trường này (`must be run in a work tree`), không ghi nhận là PASS. Agent tester bổ sung test nhưng bị usage limit trước khi báo cáo; Main đã sửa fixture dang dở và chạy toàn suite trên bản cuối.

## Cập nhật pipeline hiện hành — 20/11/2026, CM4 v28

Đối chiếu code hiện tại: engine `cm4-query-review-v28`, live CLI `cm4-live-v2`, source gate v4. Đây là phần thay đổi kể từ commit `7c230e5`; các checkpoint v24–v27 và tiến độ M0–M7 bên dưới giữ làm lịch sử. Hướng dẫn chạy hiện hành: [CM4](../experiments/context_manager_v2/CM4.md), [luồng model/context](../experiments/context_manager_v2/MODEL_CONTEXT_FLOW.md), [AG_CHECK](../reviews/cm4_query_review_v24/AG_CHECK.md).

| Thành phần | Thay đổi so với pipeline trước đợt này |
|---|---|
| Query lifecycle (`engine.py`, `query_review.py`, `cli.py`) | Khóa từng search query tới khi có conclusion; phải survey toàn bộ hits trước đọc raw B. Ledger giữ riêng survey/raw exposure, ưu tiên, assessment và unresolved. Query trùng sau conclusion trả lại kết quả cũ, không tự retrieval lại. |
| Source gate (`source_gate.py`, `query_options.py`) | Dùng `search_needed` / `no_search_needed` / `need_more_context`, không còn aliases gate cũ trong API CM4. Cho xét mệnh đề chưa có tên án/citation và span partial đủ ngữ cảnh; `signal_ref` tùy chọn. Positive một mệnh đề không phủ cả paragraph. |
| Đọc A và context | Ghép lại vùng A liên tục đã được giao qua `read_query_span`, kiểm provenance và cap; không lấp khoảng chưa đọc. V26 chỉ dựng map khi ở query mode và đếm theo projection CM4 thực, sửa crash sau search. |
| Focus và survey | V27 khóa gate mutations ở schema và host khi query đang mở nhưng vẫn cho đọc A; thêm first-unseen/progress, bỏ assignment priority không đổi. V28 thêm preview tối đa 320 ký tự có span/hash, đường quay lại ứng viên `read_next` chưa đọc và chặn conclusion khi còn ưu tiên chưa xử lý. Query có hits nhưng chưa đọc raw B chỉ được kết luận partial. |
| Nhu cầu đã xử lý | V28 loại span mệnh đề đã tìm khỏi lựa chọn tìm mới; chỉ tìm lại có chủ đích qua `revisit_source_need` sau conclusion. Những mệnh đề khác trong cùng paragraph vẫn được xét. |
| Live và STOP (`live.py`, `engine.py`) | Loop guard mặc định `warn`, mode `stop` chọn rõ; log kèm query progress/usage/context. STOP sau admission nhưng trước gửi ghi `submission_attempted=false` và `operator_stop_file`; tách ngân sách giữ chỗ khỏi usage provider. |
| Prompt | Giữ điều kiện/ngoại lệ pháp lý trong query; phân biệt lời đương sự với nhận định tòa; kiểm chiều A viện dẫn B và ngày quyết định đã xác minh, không suy ngày từ case ID. |
| Modal controller | Pin chuyển sang `fu-TfWPSIRNQIkZWM1W5O7HEv` theo đợt AG đổi profile/deploy đã ghi trong [bàn giao Modal](../reviews/cm4_survey_focus_fix_v1/MODAL_ACCOUNT_20261120.md). Chỉ đạo mới: giữ request gốc và chờ GPU vô hạn khi pending, không tự probe/retry/cancel vì chờ lâu. |
| Tests và tài liệu | Bổ sung query-review acceptance/current catalog và regression survey, gate, nguồn, STOP; fixture M6 nạp `explicit_leads` theo config. Tách hướng dẫn hiện hành khỏi `*_HISTORY.md` và offline replay; thêm plan Q1–Q4, báo cáo local/pilot và scripts kiểm prefix chỉ đọc. |

Giữ model/embedding/index/RRF, top 50 mặc định CM4, map cap 2.400 và input/output 8.500/512, cumulative uncapped. Chưa mở mốc mới hoặc có prediction/gold evaluation mới.

Evidence gần nhất: [pilot v27 và sửa v28](../reviews/cm4_survey_focus_fix_v1/PILOT_20261120.md). V27 có 153 admissions, 152 lượt controller thực gửi, 5 query survey đủ 250 cặp kết quả/220 án duy nhất nhưng chỉ 3 án nhận raw; AG STOP khi lặp screening. Provider: 685.243 input / 15.376 output controller tokens và 192 embedding tokens qua 5 request. Usage unknown của request embedding gián đoạn trước được giữ riêng, không coi là tiết kiệm. Chi tiết latency và run v26 ở [REPORT](../reviews/cm4_survey_focus_fix_v1/REPORT.md).

Kiểm lại trước push ngày 20/11: suite CM4 đạt **135 tests PASS trong 94,638 giây**, không gọi provider; `git diff --check` PASS. Regression M6 v15 bị skip vì thiếu fixture local (0 tests chạy), nên chưa xác minh lại regression đó trong đợt push này.

V28 đã có kiểm local 135 tests PASS và fresh prepare 3.129 tokens, 0 controller/embedding requests theo báo cáo pilot. Chưa có live/semantic acceptance v28 hoặc metric COLIEE mới. Khi code/root/settings đổi phải prepare namespace mới; không sửa plan/receipts cũ để resume. Codex chỉ kiểm local và chuẩn bị lệnh; người dùng/AG chạy inference/deploy.

CM4 v27 hiện tại: sau run v26 49 admissions, STOP sạch khi survey 10/50/0 raw B, sửa focus/cấp tool gate và route survey. Xem [REPORT v27](../reviews/cm4_survey_focus_fix_v1/REPORT.md) cho evidence, kiểm local và lệnh AG; chưa inference/deploy mới.

CM4 v26 sửa host crash sau query đầu của pilot `021095.txt`: bỏ map không dùng ở results mode, đếm map theo model projection, giữ cap 2400/8500/512. Kết quả và lệnh AG chạy lại ở [REPORT v26](../reviews/cm4_map_projection_fix_v1/REPORT.md). Chưa chạy inference/deploy mới hoặc đánh giá semantic toàn run mới.

Cleanup CM4 hiện hành ngày 19/11: engine `cm4-query-review-v25`, gate v4 bỏ aliases cũ, giới hạn catalog và recovery theo tools hiện hành, tách tài liệu lịch sử. Xem [kết quả cleanup](../reviews/cm4_query_review_v24/CLEANUP.md). Checkpoint v24 bên dưới giữ kết quả đợt triển khai trước cleanup.

## CM4 Q1–Q4 — 19/11/2026

Người dùng đã yêu cầu triển khai toàn bộ [kế hoạch query review](plan/CM4_QUERY_REVIEW_PLAN_20261119.md). Engine `cm4-query-review-v24` / live `cm4-live-v2` bổ sung khóa từng search query, survey toàn bộ tập hits trước đọc sâu, nguồn theo mệnh đề/partial span và loop warn mặc định cho AG điều khiển STOP. Kết quả local cùng hạn chế cập nhật tại [REPORT](../reviews/cm4_query_review_v24/REPORT.md); [AG_CHECK](../reviews/cm4_query_review_v24/AG_CHECK.md) có lệnh giao người dùng/AG chạy thật. Chưa có inference/deploy/live semantic acceptance mới. Trạng thái và receipts lịch sử bên dưới không thay thế kết quả đợt này.

Đã nghiệm thu kỹ thuật M3 và lượt tích hợp live M4 trên một query. Nền nguồn và passage đã qua kiểm tra toàn corpus. Full embedding, DB integrity, BM25 sparse, source tools và hybrid đã qua các bước kiểm tra ghi bên dưới.

AG review sparse đã hoàn tất ngày 10/11/2026, đạt correctness, index integrity và corpus parity, với 0 lỗi production chặn nghiệm thu. Hybrid local dùng vector cache đạt. Bốn ghi nhận còn lại liên quan startup/RAM, chi phí guard, revalidate và phạm vi M3. Khi nối harness, dùng session xuyên nhiều truy vấn; cân nhắc gom guard ở biên request sau khi giữ đủ kiểm tra invalidation. [Báo cáo AG](../reviews/m3_sparse_ag_review_v1/REPORT.md).

| Mốc | Tình trạng | Đầu ra đã có | Việc còn lại |
|---|---|---|---|
| M0 — Khóa nguồn/profile | Đã khóa nguồn, cohort và embedding profile | Manifest train, exposure/split ledger, Qwen revision và runtime L4 | Model/tokenizer/ngân sách cho agent được chốt khi sang M4 |
| M1 — Nguồn/cấu trúc | Đã nghiệm thu trong contract đã ghi | Raw registry, byte offsets, paragraph/quotation/unknown, vùng nguồn | Xử lý ngữ nghĩa tiếng Pháp được hoãn theo yêu cầu |
| M2 — Passage/context mapping | Đã nghiệm thu toàn train | 415.693 passages, 382.343 parents, 7.708 án, tokenizer và context refs | Tầng giao payload cho agent thuộc M4 |
| M3 — Chỉ mục hybrid | Đã nghiệm thu kỹ thuật | BM25 sparse, exact dense + RRF, Qdrant full verify, source tools có phân trang và lượt query embedding thật | Theo dõi latency provider và dense ở các run tiếp theo |
| M4 — Tools/harness | Đạt nghiệm thu kỹ thuật live trên một query | Probe schema phân nhánh và corpus một cặp qua policy v3. Ledger xác nhận một assessment có raw refs đúng A/B và 0 retry. [Báo cáo live](../reviews/m4_live_20261112T093650531Z/corpus/report.json) | Độ đúng ngữ nghĩa và chất lượng COLIEE được đánh giá theo mốc tương ứng |
| M5 — Baseline lịch cố định | Đường nối assessment M4 đạt nghiệm thu live trên một query | 31 ứng viên, 5 assessment đúng locator need và raw refs A/B, 30 context chờ bằng chứng, 0 retry. [Báo cáo live](../reviews/m5_live_20261112T100428470Z/assessment_report_1794478173138712200.json) | Bộ chọn số án biến thiên cần policy chốt trên discovery, rồi nghiệm thu M5 end-to-end |
| M6 — Agent thích ứng | Đã tích hợp hybrid và kiểm local; chưa nghiệm thu live/semantic | Controller purpose tools, dynamic schema, provenance, budget/resume, targeted review, hybrid M3 và ledger embedding; 97 test liên quan PASS | Nghiệm thu controller và query embedding live, nối selector/fallback M5 đã khóa, so fixed/adaptive theo cùng profile |
| M7 — Đánh giá khóa | Chưa chạy | Có split/exposure protocol | Freeze hệ thống, chạy evaluation, phân tích lỗi và cost theo protocol COLIEE đã kiểm |

Mốc M3 chỉ chốt khi đủ phạm vi trong kế hoạch tổng thể. Việc ingestion PASS hoặc hybrid trả top 20 là các gate kỹ thuật thành phần. Số top 20 của retrieval chưa phải số án noticed được chọn cuối cùng.

Ngày 11/11, full verify sau phục hồi Qdrant đạt đủ 415.693 points. Source tools đạt 54 kiểm thử liên quan và kiểm tra trên corpus thật. Mở nguồn của ba án từ kết quả cached hybrid lúc phục hồi cũng đạt. Hai lần chạy tích hợp mới với dense exact gặp timeout 120 giây, và lần chẩn đoán giới hạn 300 giây cũng hết thời gian. Gate query embedding thật đã có manifest một request và lệnh dành cho người dùng hoặc AG. [Công cụ M3](M3_SOURCE_TOOLS.md) · [Báo cáo triển khai](../reviews/m3_completion_v1/REPORT.md)

Ngày 12/11, AG chạy lại trên máy hiện tại sau khi khởi động Docker Desktop. Cả ba lượt cached hybrid đều đạt với timeout 120 giây và 0 request Modal. Dense exact mất 30,20, 12,40 và 42,11 giây. Kết quả xác nhận đường tích hợp trên máy này trong đợt kiểm tra và để ngỏ nguyên nhân của các timeout trước. [Kết quả chạy lại](../reviews/m3_completion_v1/REPORT.md)

Ngày 12/11, Main đối chiếu lượt query embedding thật với manifest, admission, ledger và stdout. Một request thành công với 184 input tokens, 0 retry. Kết quả gồm 20 án khác query, khớp RRF tính lại từ ba kênh. Main kiểm 200 passage leads với M2 đã seal và nguồn raw. Tổng thời gian 575,51 giây, trong đó RPC embedding 481,24 giây, xử lý remote 0,82 giây và dense query 13,09 giây. Đây là nghiệm thu đường chạy kỹ thuật. Chất lượng COLIEE được đánh giá ở M7. [Receipt nghiệm thu](../reviews/m3_completion_v1/real_query_execution/main_acceptance.json)

Ngày 12/11, bản M4 trước cập nhật contract đạt 11/11 test M4 và 61/61 test khi chạy chung với regression M3 liên quan. Lượt replay sáu bước trên corpus thật và kết quả hybrid đã lưu cũng đã đạt ở vòng triển khai, với 0 request live.

Contract assessment v2 áp dụng mục 2.1 của kế hoạch. Transport nhận JSON Schema theo nhánh. Host kiểm lại JSON, raw refs và provenance, ghi riêng hồ sơ thiếu bằng chứng và lỗi output, đồng thời giữ usage của lượt bị từ chối. Đạt 22/22 test M4 và 79/79 khi chạy chung với hồi quy M3/M5 liên quan. Các test xác nhận truyền đúng schema, từ chối JSON có khóa trùng, fallback và 0 request sửa output. Adapter giữ được quan hệ dẫn lời và offsets trên nguồn thật. Schema phân nhánh chưa được kiểm trên engine live. [Hướng dẫn M4](M4_HARNESS.md)

Adapter Modal đếm đúng 30 token của prompt canary đã lưu bằng tokenizer và chat template đã khóa. Replay local trên `017984.txt` dùng corpus thật và năm phản hồi giả lập, chấp nhận một assessment có raw refs A/B và dừng theo contract. Nghiệm thu live theo [lệnh dành cho AG](M4_HARNESS.md#nghiệm-thu-live-trên-modal).

Probe live đầu tiên dừng với `NotFoundError`, không có Modal call ID và không có phản hồi model. AG xác định workspace từ chối tra cứu pin bằng `version=1`. Adapter đã chuyển sang tra cứu theo tên, kiểm ID function trước khi gửi và xác minh tra cứu thành công bằng metadata Modal. [Receipt lần đầu](../reviews/m4_live_20261112T074944211Z/probe/report.json)

Probe tiếp theo đạt schema phân nhánh trên L40S, ghi một assessment chờ bằng chứng B với 601 token vào, 124 token ra và 0 retry. Lượt corpus trên `017984.txt` đạt 6/6 response theo schema và hết cap sau sáu action tìm kiếm, với 7.428 token vào, 344 token ra và 0 retry. Ledger cho thấy hit đầu đã có `open_ref` hợp lệ trong payload kế tiếp. Controller tiếp tục tìm và chưa mở B. Prompt corpus đã được sửa để ưu tiên mở hit, giao lại raw refs A/B và assess. Cần chạy lại riêng corpus để kiểm thay đổi này. [Probe đạt](../reviews/m4_live_20261112T081741491Z/probe/report.json) · [Lượt corpus](../reviews/m4_live_20261112T081741491Z/corpus/report.json)

Runner corpus hiện lọc nhánh action theo payload trước mỗi request. Khi đã có hit mở được, schema chỉ cho phép mở nguồn. Lượt assessment chỉ khả dụng khi đã giao raw refs A/B. Host kiểm lại schema của lượt trước khi chuyển action cho harness. [Quy tắc nghiệm thu corpus](M4_HARNESS.md#nghiệm-thu-live-trên-modal)

Giao diện model của runner corpus dùng tên theo mục đích và mô tả tool của lượt hiện tại. Model chọn cụm tìm và đánh giá bằng chứng. Host điền kênh, giới hạn, `open_ref` và tham số nạp lại từ state. Báo cáo lưu tên tool model nhận cùng action nội bộ tương ứng. Cần kiểm giao diện này trong lượt corpus live kế tiếp.

Lượt corpus kế tiếp trên `017984.txt` đã tìm một hit, mở đoạn B và nạp lại raw refs của cả A/B. Request assessment dừng ở cap 512 output token với `finish_reason=length`. Tổng 4 request, 9.294 token vào, 592 token ra và 0 retry. Runner corpus đã thu gọn assessment thành hai nhãn và một lý do tối đa 120 ký tự, đồng thời điền refs từ payload. Cần kiểm lại riêng corpus trên Modal. [Receipt lượt corpus](../reviews/m4_live_20261112T091854117Z/corpus/report.json)

Policy `m4-corpus-actions-v3` đạt cả sáu tiêu chí trong lượt live trên `017984.txt`. Năm request kết thúc với `finish_reason=stop`, 0 retry, 10.230 token vào, 175 token ra và tổng thời gian 249,241 giây. Lượt assessment dùng 75 token đầu ra. Ledger xác nhận assessment của `017984.txt` → `082632.txt` dùng đúng raw refs của hai phía trong payload hiện tại. Nhãn `contradicted` là suy luận của model. Đây là kết quả nghiệm thu giao thức, schema và giao bằng chứng của M4 trên một cặp. [Báo cáo](../reviews/m4_live_20261112T093650531Z/corpus/report.json) · [Ledger](../reviews/m4_live_20261112T093650531Z/corpus/events.sqlite3)

Đường nối M5 → M4 đạt 55 test local. Kiểm runner trên corpus thật `017984.txt` với phản hồi Modal giả lập nhận 31 hồ sơ ứng viên, chấp nhận 5 assessment theo locator need và giữ 30 context khác chờ bằng chứng. Đếm prompt bằng tokenizer thật được 15.238 input token qua 5 request giả lập. Gọi tiếp tục cùng run giữ tổng 5 request và usage, không gửi thêm. Đầu ra giữ `selection_status=pending_selection`. [Hướng dẫn nghiệm thu M5](M5_FIXED_BASELINE.md#nối-hồ-sơ-cố-định-vào-assessment-m4)

AG đã chạy live đường nối M5 → M4 trên `017984.txt`. Main đối chiếu basket với ledger từng context và usage tổng. Cả 5 request kết thúc `finish_reason=stop`, dùng 15.238 token vào, 266 token ra, 0 retry và không có receipt chưa rõ. Năm assessment được validator chấp nhận với đúng refs A/B và locator need, đều có quan hệ `unknown`. Ba mươi context còn lại tiếp tục chờ bằng chứng. Mỗi target dừng ở `budget:request_cap` sau một assessment theo profile đã khóa. Basket giữ `selection_status=pending_selection`. [Basket](../reviews/m5_live_20261112T100428470Z/evidence.json) · [Báo cáo live](../reviews/m5_live_20261112T100428470Z/assessment_report_1794478173138712200.json)

M5–M7 lần lượt xây baseline, agent thích ứng và đánh giá khóa.

Ngày 12/11, triển khai M6 theo giao diện tool theo mục đích tại mục 1.1 của kế hoạch. Host giữ tham số kỹ thuật, source/candidate refs và cursor; model chọn vấn đề, citation, ứng viên/trọng tâm đọc, assessment và dừng. Catalog/schema từng lượt nằm trong admission ledger; citation có tiếp tục scan; review đếm cả attempt chờ bằng chứng; counterevidence không bị chuyển thành identity support. Bản cuối đạt 80 test M3 source/M4/M5/M6 liên quan; review độc lập đạt 20/20 test M6 và không còn lỗi chặn trong phạm vi local đã kiểm.

Replay trên `017984.txt` dùng BM25 cả hai kênh, nguồn thật và tokenizer đã khóa: 6 ứng viên, 5 lượt giả lập, một assessment nhãn giả lập `unknown`, 0 request model/Modal, 0 retry; resume không gửi thêm. Bản replay cuối khớp implementation fingerprint hiện hành. Đầu ra `prediction=null`, `selection_status=pending_selection`. Tổng input được tokenizer đếm là 52.385 token, payload lớn nhất 14.426 token; đây là chi phí prompt giả lập theo cấu hình kiểm tích hợp, không phải provider usage hoặc budget đã hiệu chỉnh. Chưa chứng minh chất lượng pháp lý hoặc lợi ích so M5. [M6](M6_ADAPTIVE.md) · [Báo cáo local](../reviews/m6_local_v1/REPORT.md).

M6 có profile `channel=hybrid` dùng ba kênh và RRF của M3, với cap và ledger embedding riêng. Kiểm local `095448.txt` qua Qdrant exact và vector cache đạt ở lượt thứ hai, sau một HTTPError ở lượt đầu. M6 mở nguồn và ghi một assessment giả lập qua 5 lượt controller giả lập. Cả hai lượt có 0 request Modal. Runner `prepare` đã lưu plan live với cap một embedding và preview payload. [Báo cáo hybrid](../reviews/m6_hybrid_local_v1/REPORT.md).

Ngày 13/11, AG hoàn tất pilot M6 hybrid trên ba query discovery. Candidate recall là 0/12. Hai query không thực hiện search, query còn lại chỉ tìm với issue một ký tự. Controller v2 giới hạn complete sau search, từ chối issue thoái hóa và thu hồi navigation binding đã dùng. Bản sửa kiểm local, chờ chạy lại live theo cùng cap. [Phân tích pilot và hướng dẫn chạy lại](../reviews/m6_discovery_pilot/PILOT_V5_FINDINGS.md)

Ngày 14/11, người dùng cho phép tối ưu retrieval theo mốc nghiệm thu. RT1 chỉ thêm capture raw kết quả các kênh ngoài payload model, link/hash và verifier, không đổi prompt/schema/caps hoặc policy retrieval. Bản local đạt 56 test M6 (1 skip do thiếu saved pilot ledger), review độc lập kiểm save/link failure và không đổi payload/call count. Có 0 request inference thật. Chưa có cached integration corpus mới vì Qdrant local chưa kết nối được và thiếu tokenizer controller pin; chờ AG kiểm, chưa mở RT2. Xem [kế hoạch RT1–RT5](plan/M6_RETRIEVAL_OPTIMIZATION.md#10-các-mốc-triển-khai-và-gate-nghiệm-thu), [báo cáo RT1](../reviews/m6_retrieval_rt1_v1/REPORT.md) và [lệnh giao AG](../reviews/m6_retrieval_rt1_v1/AG_CHECK.md).

Sau checkpoint RT1 ngày 14/11, đã tải tokenizer controller pin vào `cache/tokenizers/qwen36_27b_fp8`, kiểm SHA-256 cả tokenizer/chat template và đếm canary local đúng 30 token, 0 inference. Blocker thiếu tokenizer đã được gỡ; chưa kiểm lại Qdrant hoặc chạy corpus integration trong bước này. [Receipt tokenizer](../reviews/m6_retrieval_rt1_v1/tokenizer_setup_20261114.json).

Ngày 14/11, Main đối chiếu evidence run AG `cache/m6-retrieval-rt1-ag-20261114-103842345` và nghiệm thu RT1 engineering cached corpus: 100 án/kênh, 3 hits giao khớp pool, 91,534 giây, 0 inference thật; [receipt RT1](../reviews/m6_retrieval_rt1_v1/main_acceptance.json). RT2 đã triển khai ref tìm từ raw A bị cắt với policy v7, giữ full/partial metadata và exact spans/hashes, không gộp excerpt/gaps. Local đạt 62 test M6 (1 skip) và 9/9 cửa sổ scripted trên raw corpus thật/tokenizer pin, 0 inference/retrieval; giữ cả report lỗi script ban đầu và lượt sửa đạt. Chờ AG kiểm độc lập theo [hướng dẫn RT2](../reviews/m6_retrieval_rt2_v1/AG_CHECK.md), chưa mở RT3. [Báo cáo RT2](../reviews/m6_retrieval_rt2_v1/REPORT.md). Chưa có kết luận model chọn đoạn/query tốt hơn hoặc recall tăng.

Sau evidence AG, Main nghiệm thu RT2 bằng report/fingerprint/hashes của run `cache/m6-retrieval-rt2-ag-20261114-110349524` (9/9, 44,758 giây, 0 inference/retrieval); [receipt RT2](../reviews/m6_retrieval_rt2_v1/main_acceptance.json). RT3 đã triển khai opt-in bản đồ cấu trúc phân cấp với policy v8, ref nguồn/config, mở rộng/đọc mọi cấp, bounded page và coverage từ receipts. Bản cuối local đạt 73 test M6 (1 skip), 159 trang corpus literal/coverage và luồng navigation scripted; prepare 5.727 token, peak khi đọc raw 7.398/7.400. Allocation map 2.400 là phần của cap payload 7.400. Giữ các run lỗi/interrupted; 0 inference/retrieval thật, chưa đo semantic/recall. Reviewer subagent bị giới hạn sử dụng trước review đầy đủ các sửa cuối; chờ AG final review theo [AG_CHECK RT3](../reviews/m6_retrieval_rt3_v1/AG_CHECK.md), dừng trước RT4. [Báo cáo RT3](../reviews/m6_retrieval_rt3_v1/REPORT.md).

Theo yêu cầu bổ sung ngày 14/11, đã chuẩn bị input cap 10.000 trong profile mới và tăng context source engine lên 12.288, bind context/output vào prompt fingerprint. Local 25 tests liên quan đạt; canary prepare đúng 10.000 input token, 0 inference. **Chưa deploy hoặc nghiệm thu context live**; AG cần phối hợp app đang dùng ở máy kia, deploy và kiểm một long-context canary theo [hướng dẫn context 10.000](../reviews/m6_retrieval_rt3_ctx10000_v1/AG_CHECK.md). Evidence RT3 cap 7.400 giữ nguyên lịch sử; chưa mở RT4.

Người dùng điều chỉnh tiếp input cap còn **8.500 token**, thay profile 10.000. Profile mới giữ context engine 12.288, output 384, 8 request/actions; tổng input 68.000, total 71.072. Khi output 512 ở RT4 thì total 72.096. Dùng [hướng dẫn AG 8.500](../reviews/m6_retrieval_rt3_ctx8500_v1/AG_CHECK.md); giữ receipts 10.000 lịch sử, chưa deploy/inference thật.

Kết quả AG sau đó: local 25 tests/prepare ctx8500 đạt; AG báo deploy app v2 exit 0 (5,515 giây). Canary 8.500 đã admission một request, call `fc-01M7CBMZWGZDPFSPB4BBT9WB94` timeout ở client và cancel_requested, receipt unknown; actual input/output tokens, provider execution count/latency và cancel completion chưa rõ, embedding 0. Main kiểm local artifact/hash/tokenizer, không gửi thêm request. **Context live chưa nghiệm thu, RT3 final review vẫn chờ, chưa mở RT4.** Xem [checkpoint AG](../reviews/m6_retrieval_rt3_ctx8500_v1/ag_execution_checkpoint_20261114.json) và [bàn giao máy đích](RETRIEVAL_HANDOFF_20261114.md); không resend canary đã admission.

Nguồn đối chiếu gồm [kế hoạch M0–M7](plan/README.md), [M2 passages](M2_PASSAGES.md), [full ingestion](M3_FULL.md), [BM25 sparse và benchmark](M3_SPARSE.md), [hybrid thật](M3_HYBRID.md), [draft full search](plan/M3_FULL_SEARCH.md).
