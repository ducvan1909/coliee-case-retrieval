# CM4 v27 — giữ focus query và điều hướng survey

Ngày 19/11/2026. Đầu vào: run AG `cache/cm4-query-review-v26-ag-20261119-220452736`. Trạng thái: **đạt kiểm local và replay prefix thực tế; chưa inference/deploy mới**. Code nằm trong working tree; dùng bindings, không chỉ HEAD base `7c230e5`, để đối chiếu revision.

## Kết quả run v26 và cách diễn giải

- Fix map v26 đã vượt blocker cũ. Run có **49 controller admissions**, **48 actions**, 1 hybrid search trả 50 hits; AG STOP, T49 reply đã nhận nhưng action không execute. Query chưa concluded, **10/50 survey**, **0 raw B**, **0 assessments**, chưa prediction. Exit 0 chỉ là dừng sạch, không phải task/semantic PASS.
- Usage AG báo: controller **305.153 input / 5.706 output tokens**, provider latency **720.040,83 ms**, transport elapsed **1.125.822,38 ms**; embedding **1 request / 36 input tokens**, remote **0,723s**, client RPC **394,942s**, hybrid **512,269s**. Không retries/unknown được ghi nhận. Đây là usage run lỗi/dừng cũ, không phải usage bản sửa.
- Có evidence model lặp phân loại, đi lùi và rời survey chưa hoàn tất. Host đồng thời cấp screening khi query đang khóa, tạo permits không thể tìm tiếp và hướng model về vùng “unscreened”. Không quy toàn bộ thất bại cho hiểu sai pháp lý.
- **T08 không xóa/ghi đè searched positive.** Ledger giữ positive `p000002` với proposition `[1067,1302]`, đồng thời thêm negative phủ `[929,2551]`; negative rộng che các nhu cầu chưa xét. Đây là lỗi coverage/contradictory decision, không phải mất record search.
- **Một proposition approved không làm cả paragraph screened.** Đề xuất loại mọi paragraph approved khỏi unscreened sẽ che nhu cầu khác (ground 1.(b)); v27 không làm như vậy.
- `signal_ref == proposition_ref` không mặc định sai; cần kiểm câu có đủ mệnh đề/dấu hiệu nguồn không. Query text `reply evidence judicial review` vẫn quá rộng so với điều kiện “available at an earlier date”, nhưng chưa có đo recall để quy lỗi backend/gold. Không đổi prompt query trong đợt này.

## Thay đổi host

Engine `cm4-query-review-v27`, live CLI vẫn `cm4-live-v2`, gate v4.

1. Query đang mở: bỏ `assess_source_need`, defer/resume/revisit gate khỏi schema và chặn ở reply/execute, không chỉ ẩn prompt. Vẫn cho navigation/đọc A và xử lý candidate đúng query. Sau conclusion mới mở lại screening/tìm nhu cầu khác.
2. Payload thay gợi ý screening bằng `query_gate_paused`; giữ nguyên records, permits đã có và coverage thật ở host. Không đánh paragraph screened giả. Không sửa lịch sử run v26 để “chữa” negative cũ.
3. `cm_page.survey_position` cho biết vị trí kết quả, tổng số, cards đã giao/chưa giao và first unseen; `next_unseen` chọn phần chưa khảo sát bằng existing `show_context_page`, không thêm tool mới. Return results trỏ phần chưa thấy đầu tiên, loại alias `results` trùng previous/next. Vẫn cho quay lại có chủ đích/đọc A.
4. Priority chỉ cấp các assignment làm đổi phân loại. Một descriptor tool trong prompt; decoder có nhánh eligibility theo priority. Cho đổi `read_next`/`maybe`/`low_priority`, không dùng lặp cùng classification với lý do khác làm tiến triển giả. Reply gốc vẫn có trong receipt.
5. Helper `cli.choose` chọn nhánh phù hợp tham số thay vì mặc định nhánh đầu. Không đổi model/embedding/index/RRF, top50 hoặc caps **2400/8500/512**, không tăng context lên 12k.

Warn-only/STOP do AG giám sát vẫn giữ. Model có thể còn đổi priority vô ích hoặc điều hướng kém; local PASS không bảo đảm hết lặp hay hiểu đúng án.

## Kiểm local

- Implementer: query-review + source-gate **24 tests PASS**, **16.591s**. Bao phủ khóa gate, A reading, coverage một proposition không phủ paragraph, next-unseen/return từ A, không offer assignment priority không đổi.
- Main: suite CM4 cuối **132 tests PASS**, **165.188s**, 0 skip (`-m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q`).
- Main: replay đúng prefix trước **T08/T12/T44 PASS**, input **4.038/4.091/4.819 tokens**, survey exposed giữ **5/10/10**, next-unseen offsets **5/10/10**, không cấp gate mutations và có paused feedback. `cache/cm4-survey-focus-v27-replay-20261119-1/report.json`, code_binding khớp code cuối. Hash ledger/plan/trace/result/STOP nguồn không đổi; **0 controller/embedding/retrieval requests mới**.
- Tester_advanced độc lập: schema không có gate mutations; forged pending gate action bị guard host từ chối trước mutation; 5→2 cards theo fit chỉ tăng exposure khi có reply; back/resume chọn đúng first unseen, survey hết không còn ghost route; positive một mệnh đề không làm cả paragraph complete. Không provider/labels hoặc sửa evidence.
- `git -c core.whitespace=cr-at-eol diff --check`: PASS.

Lệnh kiểm saved prefixes, tùy chọn trên máy có run AG (không bắt chuyển run cũ để chạy pilot mới):

```powershell
$out = 'cache/cm4-survey-v27-check-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.reviews.cm4_survey_focus_fix_v1.check_saved_turns --source-run cache/cm4-query-review-v26-ag-20261119-220452736 --out-dir $out
```

Script cấm controller/retrieval, dùng prefix trước T08/T12/T44, kiểm gate mutations không được cấp, gợi ý screening bị pause, next-unseen lần lượt 5/10/10, không tăng exposure và hash evidence nguồn không đổi. Đây là projection check, không phải resume hay live/model behavior mới.

## AG chạy lại một A sau local PASS

Pilot `021095.txt` vẫn trong phạm vi đã giao. AG kiểm metadata/Qdrant/bindings rồi chạy trọn prepare→live→giám sát→review toàn bộ lượt theo [AG_CHECK](../cm4_query_review_v24/AG_CHECK.md). Không tự deploy, không mở A khác, không resume v26 STOP bằng v27, không xóa STOP hay sửa receipts cũ. Fresh run tạo inference/embedding mới là pilot mới, không tự resend unknown request.

```powershell
$cmRun = 'cache/cm4-query-review-v27-ag-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $cmRun --loop-guard-mode warn
if ($LASTEXITCODE -ne 0) { throw 'Prepare failed; do not run inference.' }
Get-Content (Join-Path $cmRun 'plan.json')
# Kiểm code/root/config bindings, 8500/512, top50, uncapped, warn trước gửi.
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir $cmRun
```

Review riêng: có theo được next-unseen và survey đủ không; còn lặp/né bằng priority khác không; quay về A có mục đích không; sau conclusion có xét được nhu cầu khác trong cùng paragraph; khi tới B có phân biệt identity/reliance với similarity không. Không coi survey đủ là hiểu án/gold PASS. Báo usage/latency đầy đủ kể cả STOP và retry, cùng `semantic_steps.md`/`semantic_review.md`.
