# CM4 v26 — sửa blocker dựng map sau truy hồi

Ngày 19/11/2026. Đầu vào: run AG `cache/cm4-query-review-v25-ag-20261119-213640055`, 17 events / 4 controller requests đã thành công, rồi lỗi compile trước request 5. Trạng thái: **đạt kiểm local và replay read-only đúng boundary lỗi; chưa chạy inference/deploy mới**. Bản sửa nằm trong working tree; HEAD base `7c230e5` không đủ phân biệt revision, dùng code bindings để đối chiếu.

## Kết luận về run AG

- Đây là host projection failure, không phải model kết luận sau trang đầu: model chưa được giao card nào, chưa đọc B hoặc đánh giá A→B. Không suy từ run này rằng model sẽ đọc đủ hoặc dừng sớm.
- Usage lịch sử theo báo cáo AG: controller 4 requests, 22.255 input / 397 output tokens; embedding 1 request, 36 input tokens; không retry/unknown. Provider latency controller 50.086,85 ms; transport elapsed 312.687,80 ms. Các số này thuộc run lỗi cũ, không phải usage bản sửa. Giữ nguyên nguồn receipts.
- AG review đủ 4/4 lượt, kèm dòng lỗi kỹ thuật request 5 chưa admit. Query `reply evidence judicial review` bỏ điều kiện quan trọng “available at an earlier date”, là evidence query rộng so với mệnh đề; chưa có phép đo để kết luận nó làm mất gold hay giảm recall.
- Ground 1.(b) / phần A còn lại là **chưa xét tại lúc crash**, không chứng minh model bỏ sót vĩnh viễn. Attribution `party` tại ground 1.(a) có căn cứ. Chưa đủ evidence kết luận năng lực hiểu toàn án, identity hoặc quan hệ nguồn.

## Root cause và sửa

`IntegratedHarness._registry` gọi shared registry trước khi biết mode. Shared registry dựng query map, rồi CM4 mới bỏ map khi đang results/assessment. Bản map với trạng thái đã đọc/tìm vượt 2400 tokens dù nó không được dùng. Đếm canonical refs/hash trước projection còn khác payload ngắn model thực sự nhận.

- `engine.py`: truyền cờ navigation rõ ràng theo mode; ngoài query mode không dựng map thừa. Vẫn dựng candidate/lead/evidence registry và giữ coverage từ ledger.
- `query_options.py`: chỉ adapter CM4 đếm map sau compact projection bằng counter pin có instructions/chat template. Canonical refs, source hashes và spans vẫn giữ ở host. Không sửa reader/count policy M6 thường.
- Giữ cap map **2.400**, input **8.500**, output **512**, cumulative rộng; không đổi prompt query, model, index, RRF hoặc top 50 để chữa host bug.
- Map thực sự không vừa sau projection được ghi failure `query_navigation_map_unfit` với 0 admission mới; runner có thể ghi kết quả partial thay vì exception không có result. Không giả hoàn tất review.

Engine `cm4-query-review-v26`, live CLI vẫn `cm4-live-v2`. Không resume plan v25 bằng code v26.

## Kiểm local

- Implementer: MapFirst suite **7 tests PASS**, 7.609s. Ba regression mới: skip map ngoài query mode; projected map/status/totals đúng cap và giữ routes/literal previews; map unfit có terminal receipt không admission.
- Main: toàn CM4 **129 tests PASS**, **243.099s**, 0 skip. Lệnh `-m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q`.
- Main: regression M6 query navigation **11 tests PASS**, **13.478s** (`-m unittest pipeline_v2.tests.test_m6_query_navigation -q`).
- Tester_advanced độc lập: map-first + query-review **17 tests PASS**, **39.232s**; probe 5 mode ngoài query không gọi map; map với 6 children/status đầy đủ đếm **1.664/2.400** sau projection so với 2.615 canonical tokens, giữ raw previews/routes/canonical metadata. Không provider/gold.
- Main replay đúng history AG: `cache/cm4-map-projection-v26-replay-20261119-1/report.json` **PASS**. Results payload **4.352 tokens**, query payload **4.207 tokens**, map **1.504/2.400**. Giữ **50 hits**, survey exposed **0**, 4 controller requests nguồn không bị phát lại; **0 controller/embedding/retrieval requests mới**. Hash ledger/plan/trace lịch sử không đổi. `report.code_binding == live.binding()` trên code cuối: **True**.
- `git -c core.whitespace=cr-at-eol diff --check`: PASS.

## Lệnh kiểm lại boundary từ run lỗi, không inference

```powershell
$out = 'cache/cm4-map-v26-check-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.reviews.cm4_map_projection_fix_v1.check_saved_run --source-run cache/cm4-query-review-v25-ag-20261119-213640055 --out-dir $out
```

Script chỉ mở ledger nguồn read-only, dựng hai preview results/query từ history trong namespace dẫn xuất mới, cấm controller/retrieval bằng mocks, kiểm hash evidence cũ không đổi. Đây không phải live run/resume/provider receipt. Script tùy chọn nếu máy có run cũ; không cần chuyển run cũ để prepare pilot mới.

## AG chạy lại sau local PASS

Tiếp tục pilot một A `021095.txt` đã được giao. Không tự deploy hoặc mở A khác. Dùng [AG_CHECK hiện hành](../cm4_query_review_v24/AG_CHECK.md), fresh namespace v26. Không dùng run lỗi cũ hoặc preflight v25. Soát binding trước inference và giữ admission unknown nếu phát sinh; không resend.

```powershell
$cmRun = 'cache/cm4-query-review-v26-ag-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $cmRun --loop-guard-mode warn
if ($LASTEXITCODE -ne 0) { throw 'Prepare failed; do not run inference.' }
Get-Content (Join-Path $cmRun 'plan.json')
# Xác nhận code/root/config bindings và 8500/512, top50, uncapped, warn.
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir $cmRun
```

AG giám sát toàn run, STOP khi cần và review ngữ nghĩa từng lượt theo mục 6; báo `semantic_steps.md`, `semantic_review.md`, usage cả lỗi/unknown. Đợt này kiểm tiếp survey/đọc B/assessment; chưa thay prompt để tránh trộn tác dụng fix host với sửa query.
