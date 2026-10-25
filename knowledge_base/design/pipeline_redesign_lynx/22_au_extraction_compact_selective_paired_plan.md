# Kế hoạch so AU extraction: packet gọn và selective context

## 1. Câu hỏi và giới hạn

Kiểm tra: **trên cùng TARGET, context chọn lọc có giúp model giữ đúng điều kiện, attribution và evidence của AU, với chi phí bổ sung đủ nhỏ không?**

Thử nghiệm này không đánh giá lại thứ tự đọc, không đổi AU taxonomy/schema, không xây toàn KB hoặc nối NN–AU qua Issue; không đổi reranker. Chỉ dùng toàn nguồn KOS-5 đã khóa: 013009, 013948, 011904, 045155, 099980. Không gọi inference trong lúc viết kế hoạch này.

KOS-5 là calibration/development vì đã dùng để phát hiện và sửa gap. Không gọi kết quả là held-out, human gold hoặc cải thiện tổng quát. Ưu tiên kết quả extraction, không coi tăng số AU hoặc protocol PASS là tăng chất lượng.

Hai arm:

| Arm | Input | Khác biệt được phép |
|---|---|---|
| G — gọn | TARGET + context baseline của global-priority | Không thêm nguồn |
| S — selective | Cùng TARGET + context được policy21 bổ sung | Chỉ context nguồn và catalog/grammar tương ứng |

Chọn **host ghép context trước, một request extraction mỗi arm**. Không thêm planner/repair/verifier model vào extraction chính. Chưa thử vòng agent đọc rồi gọi tool: đây là câu hỏi khác và phải tính thêm context gửi lại, output và lượt điều phối.

## 2. Bằng chứng đầu vào và những gì tái sử dụng

Đọc các tài liệu/file sau trước khi implement:

- `AGENTS.md`: phân công, phạm vi và evidence gate.
- `20_single_priority_dependency_offline_plan.md`, `21_selective_context_offline_plan.md`: các policy đã khóa.
- `knowledge_base/pipeline_v1/outputs/region_priority_variants_20261013/RESULT.md`, `order/revision02/{report,inventory,frozen_snapshot}.json`: baseline hiện hành.
- `knowledge_base/pipeline_v1/outputs/selective_context_offline_20261013/{RESULT.md,ACCEPTANCE.json}` và `main/revision01/{report,inventory,frozen_snapshot,source_audit}.json`: selective hiện hành.
- `knowledge_base/pipeline_v1/selective_context_offline/{policy,core}.py`: cách chọn context; không sửa theo output model trong đợt này.
- `knowledge_base/pipeline_v1/au_compact/{core,manifest,runner,prompting,decoding,jobs_client,review_packet}.py`: catalog atom, renderer, prompt, grammar, transport, normalization và review.
- `knowledge_base/pipeline_v1/contracts/compact_au_model_output.v1.json` và `plan10_au_model_output.v1.json`: contract chuẩn.
- `knowledge_base/pipeline_v1/au_runtime_config.py`, `knowledge_base/config.py`: cấu hình chung.
- `knowledge_base/pipeline_v1/outputs/source_store_v1/`, `outputs/plan03_source_blocks_v1/`, `outputs/plan04_sentence_atoms_v1/` và các manifest/policy đang được các report trên bind.
- `selected_kos_manifest.v1.json` cùng `G:/Legal-AI/kos_sample`: chỉ dùng audit tham khảo sau khóa workload; không đưa KOS AU, NN, Issue hoặc gold vào prompt.

Code hiện có đã hỗ trợ compact AU, EBNF theo request, jobs, warmup, cache, host normalization và review packet. **Chưa có adapter paired workload cho inventory SourceBlock/selective**; không giả định manifest AU-compact cũ đã là workload cần thử.

Đặc biệt: offline kế hoạch21 ước lượng JSON packet/scaffold, còn AU runtime gửi prompt/few-shot và atom catalog. Phải đo lại payload thực; không chuyển con số 248.396 thành dự toán token inference.

## 3. Khóa workload trước output

### 3.1. Kiểm kê tất cả 431 TARGET bằng adapter local

1. Rebuild/validate source, SourceBlock và SentenceAtom theo các binding đã khóa.
2. Với từng region, tạo refs G/S từ chính xác span baseline/selective; TARGET và source hash giống nhau.
3. Dùng cùng `build_evidence_catalog` và renderer AU-compact cho hai arm. Catalog mở nguyên atom; phần atom ngoài span TARGET vẫn là `CONTEXT_PADDING`, không trở thành chủ sở hữu proposition.
4. Ghi ba loại delta riêng: raw source spans, atom catalog, nội dung model thực sự đọc. So sánh nội dung sau khi chuẩn hóa duy nhất request identity; không bỏ text hoặc role tags khỏi phép so.
5. Khóa `target_id`, TARGET_BODY spans/text/atom IDs. Context thêm không được làm TARGET dài hơn hoặc đổi role của atom cũ.

Kế hoạch21 chỉ có 2 raw packet đổi. Nếu atom expansion làm hai arm đọc cùng nguồn, ghi `effective_context_noop` và không gọi đó là cặp thử context. Nếu không còn cặp thay đổi thực, dừng trước inference: chưa có can thiệp cần thử. Không nới policy để tạo thêm ca sau khi nhìn output.

### 3.2. Pilot tối đa 32 TARGET

- Lấy toàn bộ TARGET có **context đọc thực sự khác** giữa G/S: dự kiến không quá2 trên KOS-5 hiện tại.
- Lấy thêm30 control không đổi: 6 mỗi án. Chọn từ source-only strata: legal/rule cue, application cue, reporting/party/quotation cue, qualification cue, không citation/marker cue, và vùng giữa/cuối án hoặc vùng dài. Đây là strata heuristic, không phải nhãn AU đúng.
- Chọn tuần tự theo strata ưu tiên cố định, rồi SHA-256 của `seed=au-context-pilot-v1|case_id|region_id`; tránh trùng TARGET. Nếu stratum thiếu, dùng thứ tự hash còn lại cùng án. Khóa danh sách và lý do trước mọi output model.
- Không chọn control từ KOS-positive, AU cũ hoặc output extraction. Cặp gap đã biết giữ tag `known_gap`; báo riêng khỏi các cặp chưa xem, không trộn thành chứng minh chất lượng.

Hai arm có cùng **logical workload**. Với control có messages/catalog/decoding ngữ nghĩa giống hệt, chỉ inference một lần và ánh xạ response đó cho cả hai arm, ghi `shared_identical_input`. Không tính đó là hai quan sát độc lập. Nếu khác chỉ vì bookkeeping ID, dùng một canonical physical request để tránh tạo biến nhiễu.

Dự kiến tối đa **34 extraction request**: 2 TARGET thay đổi ×2 arm +30 control ×1. Không chạy cả431 TARGET ×2 trong pilot này. Hai cặp thay đổi quá ít để suy luận thống kê tổng quát, dù chúng đều cải thiện.

## 4. Model, prompt và contract cố định

- Model baseline: `Qwen/Qwen3.5-9B`, như deployment tự host hiện có. File `deployments/modal/qwen35_9b_bulk.py` đang pin revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`; khi chạy phải đối chiếu revision thực của endpoint. Không suy model đang live chỉ từ file deploy.
- Dùng cấu hình từ **`knowledge_base/.env`** qua loader chung; không tạo `.env` riêng hoặc thêm credential vào manifest/report. Preflight xác nhận `AU_MODEL` khớp manifest; nếu endpoint/model/revision khác thì block, không tự đổi model.
- `enable_thinking=false`, temperature0, cùng prompt identity của `au_compact/prompting.py`, cùng synthetic few-shots; không thêm hint metadata/KOS cho riêng S. Template/prompt version giống nhau; chỉ vùng source/catalog/ID hợp lệ thay đổi.
- Decoder: EBNF hiện hành, `string_decoder=host_validated`; không quay về JSON-schema decoder cũ. Hai arm dùng cùng generator/version; grammar cụ thể khác catalog CONTEXT là thay đổi cần thiết, phải log riêng.
- `transport=jobs`; tối đa một request đang inference trong phép đo ban đầu, một replica. Không trộn concurrency/bulk tuning vào ablation context.
- Contract giữ `compact_au_model_output.v1.json`: positive/hard_negative/unresolved, coverage complete/needs_split, tối đa3 AU, claim<=300 ký tự, 1–3 evidence IDs/AU, kind/speaker/attribution_role/needs_context hiện có. Model chọn atom IDs; host suy offset/quote và chuẩn hóa contract đầy đủ.
- Giữ output cap **800 token/request** như compact manifest hiện tại. Không tăng cap hoặc rút schema chỉ cho một arm. Length/needs_split là kết quả cần ghi, không được tự sửa JSON hoặc bỏ điều kiện để thành công.

Host chỉ xác minh schema, ID, source/hash/offset/quote và record normalization. Proposition thuộc TARGET, evidence đủ điều kiện hoặc speaker đúng vẫn cần review ngữ nghĩa. AU có cùng topic hoặc một TARGET evidence ID chưa chứng minh ownership.

## 5. Adapter và runner cần implement

Tạo module riêng `knowledge_base/pipeline_v1/au_context_paired/` với các phần:

| Phần | Trách nhiệm và đầu ra |
|---|---|
| `build.py` | Validate binding, tạo refs G/S, atom catalog, render prompt; khóa workload, control sampling, logical→physical request mapping |
| `preflight.py` | So invariants, cap và tổng reservation; tính token estimate/usage plan; không gọi mạng |
| `runner.py` | Warmup, smoke, paired dispatch, ledger/cache/jobs resume; ghi response/receipt từng request |
| `review.py` | Tạo hồ sơ review giấu arm, reference checklist và paired comparison; không tự gán semantic PASS |
| `compare.py` | So chất lượng/cost theo pair và subgroup; giữ run lỗi/thiếu riêng |
| `__main__.py` | CLI `build`, `preflight`, `run`, `review-packet`, `compare` |

Tái sử dụng helpers AU-compact; không copy cả runtime hoặc sửa đường chạy AU cũ chỉ để phục vụ pilot. Nếu helper private không đủ ổn định, tạo adapter nhỏ có test. Thay đổi helper dùng chung phải có regression trước khi chạy remote.

`workload.json` phải chứa:

```text
experiment/version/seed; calibration flag
source+block+atom+prior report bindings; selective policy hash
prompt/schema/decoder/renderer/model/endpoint nonsecret identity
pair_id; case_id; source_hash; canonical target_id; TARGET spans
G/S refs, atom catalog and rendered-message fingerprints
raw_delta/effective_delta; known_gap/control stratum
logical_arm -> physical_request_id; shared_identical_input
per-request input/output reservations; locked execution order
```

ID job vật lý/cache phải phân biệt mọi request có khác payload, model hoặc runtime identity. Không dùng chỉ target_id làm job key. Shared control có một receipt thật, không copy rồi cộng usage hai lần.

## 6. Cổng offline và ngân sách thực thi

### Cổng A — Build/preflight local

- Verify policy/source/report/code fingerprints, không overwrite output cũ.
- TARGET_BODY/hash/offset/quote/catalog TARGET giống nhau giữa G/S; S là bổ sung context, không thay nguồn.
- Test atom crossing TARGET/context, partial atom, overlapping contexts, escape text, attribution quote; nguyên source truy cập được.
- Test no-op sharing không tạo hai request, mapping response đúng target, catalog IDs hợp lệ; mỗi AU phải có TARGET atom theo contract.
- Test cache tách G/S khi input khác, resume không dispatch lại terminal receipt, crash sau reserve/submit không nhân đôi job, lỗi một cặp không bỏ kết quả cặp khác.
- Preflight không được gọi Modal hoặc tự tải tokenizer/checkpoint.

Phân biệt ba con số: **prompt tokens model đọc**, **HTTP bytes chứa grammar**, **reservation host**. Runner AU hiện có reserve theo `full_prompt_utf8_bytes`; đây là bound bảo thủ, không phải usage token. Không dùng nó để kết luận token tăng giảm hoặc âm thầm đổi loader/budget.

Nếu tokenizer đúng revision đã có local, đếm messages/chat-template theo tokenizer; nếu không, dùng estimate ghi rõ và lấy provider usage khi chạy. Grammar bytes/compile latency báo riêng, không cộng toàn bộ JSON payload thành input token.

### Ngân sách pilot khóa trước run

- Tối đa34 extraction request unique; mọi request thực gồm warmup/probe/retry được ghi riêng trong ledger tổng, không bị bỏ khỏi cost.
- Trần vận hành đợt này: **100 provider POST attempts**, gồm warmup, smoke/probe và retry; GET polling ghi riêng, không coi là inference attempt.
- Warmup tối đa50 attempts trong tối đa600 giây, thoát ngay khi endpoint sẵn sàng; không reset hạn mức lúc resume. Khi warmup hết trần thì checkpoint và dừng.
- Source-free decoder smoke tối đa2 request với chính generator/runtime; không chạy lại toàn constraint suite226 ca nếu endpoint/code đã có evidence tương ứng và không đổi.
- Mỗi extraction job chỉ cho một lần resubmit lỗi provider xác nhận chưa nhận job. Timeout/ack mất thì lookup/poll cùng job key, không tạo request khác. Receipt semantic/schema/length không được retry trong primary experiment.
- Output reserve extraction tối đa34×800=27.200 token; output warmup/probe ghi riêng theo cap thực. Tổng input reservation lấy từ **workload rendered thực**, không dự đoán bằng cost offline kế hoạch21.
- `AU_MAX_REQUESTS`, `AU_MAX_PROVIDER_ATTEMPTS`, `AU_MAX_TOTAL_INPUT_TOKENS`, `AU_MAX_TOTAL_OUTPUT_TOKENS` là cap chung runtime: preflight chỉ ra giá trị cần đủ so reservation và thử nghiệm cap ở trên. Không sửa `.env` trong bước nghiên cứu; không lấy USD/request giả định làm giới hạn.
- Provider usage thiếu phải là `unknown`; không ghi token0 cho request remote đã chạy mà thiếu usage. Chạm cap giữ incomplete, không coi tiết kiệm.

### Cổng B — Remote smoke trước toàn pilot

Sau khi người dùng cho chạy thật: warmup → decoder smoke → một cặp context có thay đổi và hai control không đổi. Dùng cùng workload/physical IDs/cache để smoke trở thành một phần pilot, không chạy lại khi mở rộng.

Chỉ tiếp tục nếu jobs/grammar/host contract và ledger đúng, không có length/schema failure chưa hiểu hoặc endpoint/model mismatch. Smoke không phải semantic gate cho toàn pipeline. Nếu hai arm đều length do cap800, giữ kết quả và đề xuất thí nghiệm cap riêng, chưa mở rộng.

### Cổng C — Hoàn tất pilot

Khóa thứ tự G/S counterbalanced bằng pair hash: một nửa cặp G trước, một nửa S trước; không chạy toàn G rồi toàn S. No-op controls xen theo order khóa. Prefix cache vẫn để cùng cấu hình, log hit counters; không đổi model/server giữa arm. Nếu deploy/config đổi, tách run, không gộp như paired cùng điều kiện.

Resume lấy jobs theo ID và commit receipt/usage trước request tiếp. Warmup khi cần có ledger riêng; terminal result hợp lệ được reuse. Ghi queue/inference/poll/normalization latency riêng nếu có; phân biệt coldstart và warm. Không mặc định container cần restart sau mỗi run.

## 7. Review semantic và metric

Không thêm vòng repair vào output extraction. Review là **đánh giá ngoài pipeline**, không được chỉnh response để làm kết quả tốt hơn.

Trước khi xem output, tạo reference checklist có evidence từ nguồn cho32 TARGET: proposition có khả năng là AU, chủ sở hữu, điều kiện/exception/limit/speaker cần giữ, factual/party/history distractor, dependency xa. Reviewer được mở nguồn cần thiết; model extraction chỉ nhận packet arm. Đây là checklist model-assisted/Codex, không phải human gold.

Hai reviewer độc lập theo luồng repo: Main chuẩn bị evidence/checklist, `tester_advanced` kiểm tra checklist và review output; `implementer` không tự nghiệm thu kết quả của mình. Có thể review mù theo X/Y, giấu arm/order/model metadata và KOS. Sau review mới mở mapping G/S. Bất đồng giữ `disputed`, không biểu quyết biến thành gold. Không bắt buộc người dùng annotation/adjudication trong pilot này.

Review mỗi proposal và cả TARGET, không chỉ AU đã sinh:

1. **Authority qualification/ownership:** proposition ở TARGET thật, không kéo AU mới từ CONTEXT hoặc biến party assertion/fact thành authority.
2. **Claim support:** mọi clause có evidence; điều kiện, exception, assessment scope/purpose và legal force không bị bỏ hoặc đảo.
3. **Attribution:** statute/quoted precedent/current court/party phân biệt; court response có bằng chứng riêng.
4. **Omission:** proposition ở TARGET được checklist nêu có bị bỏ; hard_negative/unresolved có hợp lý; mixed target không bị reject hết.
5. **Coverage/duplicates:** needs_split/max3AU/max3evidence có che thiếu coverage; nhiều AU không mặc nhiên tốt hơn.

Mỗi verdict có case/hash/evidence spans, lỗi cụ thể và severity; unsupported conclusion hoặc mất qualification làm đổi nghĩa là severe. Khi nguồn/checklist chưa đủ, ghi unknown/disputed. Review chất lượng không đánh đồng với output hợp schema.

Report tách:

- Changed-input pairs, known-gap pairs và shared controls; không tăng sample size bằng no-op shared response.
- G→S: tốt hơn/xấu hơn/không đổi/disputed; số severe errors, omission, attribution, condition/exception/limit và context-only AU. Claim text khác không tự là AU khác; ghép proposal theo TARGET proposition/evidence, không chỉ string match.
- Field/semantic scores đối chiếu checklist chỉ ghi `model_assisted_reference`; không gọi precision/recall gold. Raw KOS excerpt exposure là metric phụ, không làm nhãn đáp án.
- Total input/output/reasoning tokens thực, request/attempt, retry, warmup, cache, source/context gửi lặp, latency và job recovery; denominator đầy đủ kể cả failed/unresolved/needs_split.
- Extraction cost, review cost và operational overhead riêng. Token Codex reviewer không có usage thì ghi unavailable/estimate, không tuyên bố tổng end-to-end cost đã đo đủ.
- Usage shared controls tính một lần cho executed cost. Chi phí hai arm độc lập nếu triển khai giả định có thể mô phỏng từ receipts, nhưng không nhân đôi thành billing thực.

## 8. Điều kiện quyết định

| Kết quả | Quyết định |
|---|---|
| S mở điều kiện đúng và model sửa lỗi severe của G, không tạo severe lỗi mới trong cặp đã review | Giữ selective ghép trước cho thử tiếp trên tập khóa mới; chưa bật default toàn corpus |
| G/S đều đúng, S chỉ tăng token | Không có bằng chứng semantic benefit; giữ G cho loại tình huống đó |
| S kéo proposition từ CONTEXT/sai speaker/claim rộng hơn | Không chấp nhận S cho tình huống ấy; ghi lỗi ownership/prompt, không repair để cứu metric |
| Context đủ nhưng cả hai extraction sai | Đây là hạn chế model/prompt/contract; tách nghiên cứu model hoặc schema cap khỏi ablation context |
| Adapter khiến hai arm đọc cùng nguồn | No-op; không chạy inference paired hoặc tuyên bố context giúp ích |
| Run thiếu/usage unknown/reviewer disputed | Kết luận chưa đủ bằng chứng; giữ checkpoint và tách phần chưa đo |

Không đặt mục tiêu30% tiết kiệm trong phép thử này: selective hiện **thêm** context so G. Câu hỏi là chất lượng bổ sung có đáng chi phí hay không. Không dùng hai cặp KOS-5 để suy độ tin cậy toàn corpus. Để xác nhận tổng quát cần khóa tập án mới có nhiều dependency và negative controls trước tuning tiếp theo.

## 9. Bàn giao và thứ tự implement

1. **Adapter + workload builder:** implementer làm; tester kiểm tra target/catalog/delta/no-op mapping. Bàn giao `inventory_audit.json`, workload và messages render khóa. Chưa remote.
2. **Preflight + runner/cache/jobs:** implementer làm; tester dùng mock failure/resume và cap. Bàn giao preflight, execution plan, test report. Chưa remote.
3. **Semantic checklist/review adapter:** Main và tester_advanced kiểm tra evidence và blind mapping; implementer chỉ làm phần serialize/compare. Khóa checklist trước inference.
4. **Warmup + smoke:** chỉ chạy khi đã cho thực thi, lưu checkpoint rồi nghiệm thu giao thức.
5. **Pilot đủ + blind review:** chạy các physical request còn lại, không lặp smoke/control. Báo kết quả đúng giới hạn calibration.

Output riêng `knowledge_base/pipeline_v1/outputs/au_context_paired/<run_id>/` gồm:

```text
workload.json, inventory_audit.json, config_nonsecret.json
rendered_inputs/, preflight.json, execution_plan.json
warmup/, probe/, receipts/, cache/, execution_ledger.json, run.json
reference_checklist.json, blind_review_packet.json, review_decisions.json
comparison.json, RESULT.md, remaining_failures.json
```

Đã có CLI `au_context_paired` và script `au_context_paired/run_pilot.ps1`; lệnh build/preflight/run/review-packet/compare được ghi trong README module. Script không truyền `-Execute` chỉ kiểm tra local; có `-Execute` chạy warmup/probe/smoke, `-Full` tiếp tục cùng receipt/ledger sau smoke PASS.

## Trạng thái

Ngày2026-10-14: đã implement module riêng, khóa32 TARGET/34 physical requests và chạy build/preflight/dry-run local. Tester độc lập27/27 test PASS; Main chạy lại23 test tại checkpoint trước rồi6/6 accounting test cuối. Source review độc lập kiểm tra32 notes; Main tích hợp corrections và khóa checklist v2, giữ3 administrative eligibility unknown. Artifact ở `outputs/au_context_paired/implementation_20261014/`.

Preflight với `.env` hiện có fail vì cap20/20/120000 không đủ; với override34/100/500000/40000 thì PASS. Extraction input reservation là302.085 UTF-8 bytes toàn prompt, không provider token. Không sửa `.env`, schema/prompt/decoder AU cũ hoặc spec04/05. Chưa gọi endpoint, xác minh revision live hoặc chạy extraction: kết quả semantic/token provider vẫn pending.
