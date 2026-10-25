# K0 — triển khai local và cách chạy

Ngày2026-10-23. Module `knowledge_base/pipeline_v1/k0_authoring/`, entry script `experiments/run_k0.ps1`. K0 không phải K1 và không đọc toàn nguồn năm án. Chưa chạy inference/deploy trong đợt implement.

## Đã triển khai

- `prepare` xác minh checkpoint A, lấy source từ catalog/payload16 request stage1 thực sự gửi; 3case011904/045155/099980,16scope,58evidence parts. Không đưa KOSClaim, reference labels, context chỉ có sẵn hoặc lời giải review vào prompt.
- CaseWork/ReadLedger tách source available, delivered, assessed, unresolved. AU owner theo case/source, có thể qua nhiều scope trong cùng case; không còn TARGET-anchor gate.
- Mỗi lượt vừa authoring vừa chọn hành động tiếp: open_region, search_source, get_drafts hoặc finish_case. Host submit các AU hợp lệ trong cùng response; optional replace_id tạo revision chain, không sinh lại toàn collection.
- Có get_case/open_region/search_source/get_drafts/submit_aus/finish_case local; search chỉ trong union K0, preview không là evidence. Không planner riêng, cue/NER worker hoặc semantic verifier mặc định.
- Field claim/limits dài chỉ warning, không truncation hoặc shortening. JSON/type/kind/evidence sai vẫn bị từ chối; lỗi một AU giữ draft hợp lệ khác và dừng case đó để kiểm tra. Case khác không bị rollback.
- Trần8AU/response là transport ceiling, không quota theo case/block. Model còn điểm chưa soạn thì continuation/get_drafts trong ngân sách.
- Receipt trước state, intent trước POST, resume replay receipt để không commit/call lặp. Counter/source/code/policy/model và payload được fingerprint. Mock/live ở thư mục riêng; source/cached response đổi thì bị chặn trước inference.

Wire envelope là aus, assessed_scope_ids, next_action. AU giữ claim/kind/evidence_ids/limits, replace_id tùy chọn. Output chất lượng chỉ grounded_draft/not_assessed; không tự reviewed_supported.

## Token và giới hạn

Input6000, output800 mỗi request; tối đa12 POST model gồm retry; tổng reservation input+output<=30000 và usage provider quan sát<=30000. Hai tổng được kiểm riêng, không cộng reserve với actual để tính chi phí. Usage thiếu hoặc vượt trần chặn admission mới, vẫn giữ receipt để truy hồi. Không tăng cap để che run partial.

Đã thêm tokenizer local đúng revision Qwen3.5-9B đã dùng trong deployment: `c202236235762e1c871ad0ccb60c8ee5ba337b9a`. Chỉ tokenizer.json/config (~12,8MB), không weights. Tokenizers0.22.1 và Jinja3.1.6; asset hashes và phiên bản lib được khóa trong workload.

Reserve lấy max(số token chat-template render, số token toàn serialized HTTP payload)+128. Đây là dự phòng local, **không phải usage provider**; grammar thường không phải prompt nhưng vẫn tính trong reserve bảo thủ. Thiếu tokenizer/dependency thì fallback UTF8bytes+128 có nhãn rõ và có thể làm workload chạm budget sớm. Không tự download trong prepare/run. Thiếu asset phải fetch tường minh; asset bị thay sai hash phải fail.

Nếu thiết lập môi trường mới:

```powershell
G:
cd G:\Git\coliee-case-retrieval
.\.venv\Scripts\python.exe -m pip install -r knowledge_base\pipeline_v1\k0_authoring\requirements.txt
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.k0_authoring.token_budget fetch
```

Dùng knowledge_base/.env hiện có, giữ model/endpoint identity như A và thinking false. Không tạo env mới, không tự fallback model hoặc deploy.

## Cách chạy

Local + mock, không inference:

```powershell
G:
cd G:\Git\coliee-case-retrieval
$run = "knowledge_base\pipeline_v1\outputs\k0_$(Get-Date -Format yyyyMMdd_HHmmss)"
& .\knowledge_base\pipeline_v1\experiments\run_k0.ps1 -Mock -OutputRoot $run
```

Sau local PASS, smoke endpoint một POST mới, đã gộp readiness/warmup:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_k0.ps1 -Execute -MaxNewRequests 1 -OutputRoot $run
```

Smoke có thể lưu run incomplete chỉ do invocation_limit, không phải endpoint lỗi. Chỉ tiếp tục khi receipt verified, không có protocol/grammar/admission error:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_k0.ps1 -Execute -OutputRoot $run
```

Resume giữ nguyên `$run`, không reset giới hạn. Native grammar compile/EOS trên endpoint chưa được xác nhận bằng local/mock; smoke là bước cần thiết trước full run, không được quảng bá 100% constraint guarantee. Không sử dụng `run_au_claim.ps1` hoặc length-recovery để chạy K0.

## Output và cách đọc

- input/workload.json và input/preflight.json: source union, identity/counter và cap.
- mock/ hoặc live/run.json: kết quả từng case, draft AU, reading state, protocol/semantic status và chi phí.
- runtime_ledger.json, receipts/, attempt_receipts/: payload/job/usage/provenance và phục hồi.
- state.json: state suy từ receipt, không là nguồn tin độc lập thay raw response.
- readiness.json: HTTP health warmup, không phải inference token.

`work_scope_complete=true` nghĩa đã xử lý phạm vi K0 theo state protocol; cả3case vẫn `case_source_status=partial`, và semantic_quality=not_assessed. Không coi mock3request hoặc source-offset PASS là semantic gain, token savings thực, hoặc đủ điều kiện mở K1.

Đánh giá sau live dùng nguồn và failure set A, so cùng union/model với A/v2. So riêng grouping, actor, attribution, qualification và omission. Không tự sửa ngữ nghĩa từ KOS/reviewer vào output.

## Nghiệm thu local ngày 2026-10-23

47 test PASS (K0, token budget, regression AU claim). Mock complete: 3 case, 16 scope, 58 evidence part; 3 POST giả lập, 0 request provider. Chạy lại không POST lặp; tạm dừng sau 1 POST rồi resume giữ tổng 3 POST. 102 file bảo vệ giữ nguyên hash. Reservation mock: input 8190 + output 2400, không phải usage hoặc token tiết kiệm thực.

Checkpoint: `knowledge_base/pipeline_v1/outputs/k0_ready_20261023/ACCEPTANCE.json`; workload và mock/run.json cùng thư mục. Code đã khóa trong workload; đổi code phải prepare workload mới. Chưa đánh giá ngữ nghĩa hoặc native grammar endpoint.

## Chẩn đoán sau live — 2026-10-23

K0 live5request hợp lệ nhưng0AU. Đã chạy native CPU replay exactgrammar5request cũ và3probeendpoint riêng: synthetic cógrammar0AU; synthetic bỏgrammar córule/exception nhưngsaiwire; case011904 authoringmộtlượt vẫn0AU. Chưa đạt positivecontrol, chưa mởK1. Package/checkpointK0giữ nguyên; chẩn đoán khônglà phiênbảnsửapipeline. Báo cáo: `knowledge_base/pipeline_v1/outputs/k0_diagnostic_v3_20261023/EVALUATION.md`. Bướcđềxuất là đốichứng vídụwire đầyđủ rồigrammar JSONtổngquát; chưathựchiện.
