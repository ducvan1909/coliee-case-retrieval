# CM4 incremental runtime và input profiles — kiểm local 24/11/2026

Đã triển khai kế hoạch [CM4_INCREMENTAL_RUNTIME_SNAPSHOT](../../docs/plan/CM4_INCREMENTAL_RUNTIME_SNAPSHOT.md), stage A–D ở mức code/local. Base `0c2da9f`; binding của working tree ghi trong các JSON receipt. Chưa chạy inference hoặc deploy; không sửa ledger, seal hay báo cáo lịch sử. Batch-only, mở packet lớn hơn và đổi model/output cap không thuộc implementation này.

## Thay đổi và mặc định

- Ledger có head/suffix API; CM4 giữ runtime state/context/index và exact prefix hash tăng dần. Hook chỉ cập nhật sau commit, invalid/rebuild khi lỗi; public views tách khỏi dữ liệu canonical. Shared harness ngoài CM4 giữ đường mặc định.
- Engine compile một common frame theo operation, dùng chung history facts, raw/verified record, feedback và exact projection memo. Giữ thứ tự first-fit/menu, decoder/ref/aliases và source plan. Kiểm lại nguồn fresh trước admission. Preview không publish state/exposure.
- Query, passage exposure, read/repair, M6 registry và hierarchical map có index dùng lại. Paid-search reuse vẫn đối chiếu cached search outcomes với journal/provenance, không bỏ kiểm receipt vì cache hit.
- `compact_catalog_v1` chỉ đổi descriptor batch: gom common fields, giữ decision-specific ref/quote rules và tool đơn. Decoder schema giữ nguyên.
- `phase_instructions_v1` chọn template theo pha, giữ common source/identity obligations. Frozen prompt spec chứa instruction literal/hash, body/schema/rendered hash, tokenizer, input count và output cap; count/send dùng cùng spec. Registry được freeze khi prepare.
- `deterministic_candidate_paging_v1` chỉ auto khi trang hiện tại đã chốt, không còn lựa chọn cần model và đúng một page target chưa giao. Admission lưu overlay; preview và auto transition chưa tính đã expose cards. Pending, repair/recovery, identity packet, STOP, nhiều target hoặc vòng trang đều chặn auto.

Runtime/cache bật trong CM4 mới. Catalog/instructions/paging **mặc định vẫn `full/full/manual`**; ba profile mới opt-in, chưa được coi là nghiệm thu chất lượng model. Planner vẫn dùng full counter để giữ packet baseline; prompt compact render sau khi packet đã chọn, không tự lấy thêm raw từ headroom.

## Kiểm trên bản cuối

| Kiểm | Kết quả | Phạm vi |
| --- | --- | --- |
| CM4 discover | **228/228 PASS**, 68,337 s | Bao gồm runtime, frame, descriptor/profile, paging và các regression hiện hành. |
| Shared M4/M6/transport/timing | **85/85 PASS**, 11,303 s | Hook shared, transport legacy/frozen, adaptive/hybrid/navigation. |
| Baseline `0c2da9f` so current | **10 stage PASS** | Exact wire/schema/handles/dispatch/aliases/coverage/excerpts/context và state; chỉ bỏ declared code binding khi so config. |
| Final CLI preflight trên án gốc | **3.443 input token**, 0 inference | `021095.txt [0,929)`, frozen spec count/hash khớp, plan binding khớp code cuối. |

Tổng hai suite cuối: **313 test PASS**. Thời gian chạy test không phải benchmark pipeline. Các lỗi đã gặp và sửa trước chốt: memo feedback bỏ side effect context; StateView cho gọi mutator; public result/manifest/harness-events còn alias canonical cache. Regression kiểm mutation sâu, cache-hit semantics, postcommit failure, stale view và suffix từ Engine khác.

Review độc lập trước vòng cuối kiểm thêm prefix/state/hash trên ledger 716 event và retrieval-index trên run khác 596 event; auto paging restart/exposure/fault cùng các điều kiện chặn. Agent review hết hạn mức sau khi phát hiện public harness alias; implementer sửa và Main chạy lại hai suite cuối, không âm thầm đổi model tester. Script [compare_legacy.py](compare_legacy.py) tái hiện differential 10 stage trên baseline local Git objects; [legacy_parity_final.json](legacy_parity_final.json) ghi binding và kết quả cuối. Đây là fixture có script, không phải chứng minh ngữ nghĩa.

Lệnh kiểm đã chạy:

```powershell
.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py'
.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m4_harness pipeline_v2.tests.test_m4_modal_qwen pipeline_v2.tests.test_m6_adaptive pipeline_v2.tests.test_m6_hybrid pipeline_v2.tests.test_m6_live pipeline_v2.tests.test_m6_reply_diagnostics pipeline_v2.tests.test_m6_query_navigation pipeline_v2.tests.test_m6_paragraph_anchor pipeline_v2.tests.test_runtime_timing
.venv/Scripts/python.exe pipeline_v2/reviews/cm4_incremental_runtime_20261124/compare_legacy.py <new-report-path.json>
.venv/Scripts/python.exe pipeline_v2/reviews/cm4_incremental_runtime_20261124/measure_local.py <new-report-path.json>
```

## Số đo local

[local_measurement_final.json](local_measurement_final.json) giữ binding, samples và OS working-set. Ledger lịch sử mở `mode=ro`, SHA-256 file trước/sau không đổi. Năm cặp phép đo legacy/incremental xen kẽ trên **cùng workload lấy state + context + exact prefix hash**, không phải full compile:

| Số đo | Legacy full read/replay/context scan/hash | Runtime đã ấm |
| --- | ---: | ---: |
| p50 | 1.434,376 ms | 12,407 ms |
| Full read runtime | — | 1 lần bootstrap; steady reads không full replay |
| Event runtime decode/apply | — | 716/716, một lần mỗi event |

Bootstrap runtime mất 3,081 s trong mẫu cuối. OS working-set trước/sau bootstrap khoảng **68,0 → 176,3 MiB**; runtime còn giữ canonical history, RunState và indexes, RAM tăng tuyến tính theo run, không O(1). Working-set/peak sau toàn script còn gồm baseline objects và tokenizer nên không quy hết cho runtime. Mẫu cuối chạy khi máy còn kiểm local khác; các sample có biến thiên, chưa dùng p95 năm mẫu làm thống kê ổn định. Các phép đo trước cũng giữ receipt riêng, không ghi đè để chọn số tốt nhất.

Input đo bằng tokenizer/chat template pin, **cùng packet nguồn và decoder** lấy từ audit gốc:

| Packet | Full | Chỉ compact catalog | Compact + phase instructions |
| --- | ---: | ---: | ---: |
| A `[0,929)` | 6.546 | 4.392 (**−32,9%**) | 3.437 (**−47,5%**) |
| A `[929,2551)` | 7.621 | 5.176 (**−32,1%**) | 4.221 (**−44,6%**) |
| Chọn permit | 2.525 | 2.525 | 1.471 |
| Danh sách hai B | 2.071 | 2.071 | 1.021 |
| Đọc B | 3.969 | 3.969 | 3.009 |
| Identity-only | 2.860 | 2.860 | 1.852 |

Các packet downstream dùng original raw với pool/decision được script, không phải real retrieval. 3.437 là fixed-packet sample của audit; **3.443** là actual CLI namespace cuối có refs/feedback riêng, không nhập hai phép đo thành một packet. Không suy tỷ lệ tiết kiệm token này ra toàn run, độ chính xác hoặc latency remote.

## Preflight và pilot tiếp theo

Namespace cuối local: `cache/cm4-incremental-compact-final-20261124`. `plan.json`, `preview.json`, `trace.jsonl` có code binding/profile registry/spec; **0 controller, embedding và reranker calls**, chưa có admission inference. Chỉ stage compile initial được đo 1,604 s; startup source/index 33,280 s. Không so con số này với run cũ khác tải để tuyên bố full compile speedup. Preflight cache không được chuyển bằng Git.

Lệnh prepare đã kiểm local, tạo namespace mới khi chạy lại:

```powershell
.venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir cache/<fresh-namespace> --reranker-function-id fu-S8RKhdaJennebaBP7lTrH2 --survey-first --profile-timing --catalog-profile compact_catalog_v1 --instruction-profile phase_instructions_v1 --candidate-navigation deterministic_candidate_paging_v1
```

Function ID trên là pin dùng cho local prepare, **chưa gọi/hydrate để xác minh deployment hiện tại**. Người dùng/AG kiểm pin trước pilot được giao. Sau prepare, giữ cấu hình từ plan; run không được truyền lại các cờ profile:

```powershell
# Người dùng hoặc AG chạy inference; Codex chưa thực thi lệnh này.
.venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/<fresh-namespace>
```

So từng stage (runtime/full → catalog → instructions → paging), cùng packet/khối lượng xử lý; tính cả repairs, retries, failures, partial và unknown. Giữ gold ở evaluator, đánh giá attribution/proposition/identity/omission riêng; schema PASS không chứng minh chất lượng không suy giảm. Không resume run lịch sử bằng binding mới; fallback full là namespace mới hoặc policy đã bind từ prepare.

## Giới hạn còn lại

- Chưa có paired model comparison, speedup live, recall/F1 hoặc nghiệm thu không suy giảm chất lượng. Các profile prompt mới chưa đổi default.
- Common frame không bỏ mọi catalog/projection: distinct span, decoder choices và exact final fit vẫn cần dựng/đếm; không hứa tokenize đúng một lần mỗi compile. Source integrity checks giữ nguyên.
- Chưa benchmark full compile ở nhiều prefix dài cùng RSS/paired workload để chốt các mục tiêu p50/p95 trong kế hoạch. Đã có projection benchmark, exact differential và real-source preflight; báo đúng ba lớp này.
- DB restore/replace tại chỗ khi Engine đang sống không phải workflow hỗ trợ. Runtime kiểm file identity/head và frozen config, vẫn cần namespace/runtime mới khi đổi snapshot/binding.
- Batch-only, tự nới packet/shortlist và đổi GPU/scale-down chưa thực hiện. Việc đọc ít token hơn không tự đảm bảo prefix caching hay tốc độ generation tốt hơn.
