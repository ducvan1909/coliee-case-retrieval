# Pilot TARGET-only → bổ sung context chọn lọc v2

Profile opt-in `primary_support_v1` (plan28) dùng stage1 wire riêng
`au-target-primary-support-v1`, giữ default `baseline_v2` và bốn profile cũ.
Top-level keys/decision/reason không đổi. Anchor chỉ có `anchor_id`, `kind`,
`primary_ref_id`, `supporting_ref_ids`, `needs_context`: một primary TARGET ref,
0–7 supporting TARGET refs khác primary và không trùng nhau, tổng tối đa8.
Tối đa3 anchor với ID theo fixed slot. Cho phép dùng lại ref giữa các AU vì một
atom có thể chứa nhiều proposition; không xác nhận chúng độc lập về ngữ nghĩa.
Grammar có branch hữu hạn cho từng primary, loại ID đó khỏi supporting enum;
host vẫn kiểm duplicate/cap. Không sinh claim/quote/offset trên wire.

Host giữ `primary_evidence=[one primary]`, `supporting_evidence` riêng theo
source order, đầy đủ provenance/offset/hash/quote. `supporting_ref_ids` và union
`target_ref_ids` được sắp theo source. `primary_claim` tương thích chỉ bằng
nguyên văn primary (không cap300), `claim_origin=host_extracted`,
`primary_representation=extractive_primary_ref_with_separate_support`.
Primary là neo địa chỉ, không bảo đảm chứa trọn proposition; điều kiện/ngoại lệ
có thể nằm trong supporting. Không ghép supporting thành primary hoặc sửa OR/AND.
Vai trò primary chỉ được hướng dẫn trong prompt, không regex hard-filter hay
speaker classifier mới.

Stage2 giữ wire hiện tại và tối đa một request/TARGET. INPUT của profile mới có
`SELECTED_TARGET_EVIDENCE=[{ref_id,text}, ...]`: union nguồn đã chọn theo source
order, mỗi ref đúng một lần cho cả request, kể cả khi nhiều AU dùng chung.
`locked_anchors` có ID/kind, `primary_ref_id`, `supporting_ref_ids`, derived
`target_ref_ids`, `primary_representation`, `needs_context`; vai trò được gắn
bằng ID. Không gửi `primary_claim` hoặc lặp quote trong evidence của từng anchor.
Context chỉ qualify/attribute, không rewrite primary, thay support hay tạo AU mới.
`build_stage2` kiểm raw keys/version và dựng lại normalized từ catalog; so sánh
toàn bộ normalized để chặn thay đổi cả primary/supporting và mọi derived field.

API hiện có không đổi; chọn profile khi prepare hoặc probe:

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context prepare --prompt-profile primary_support_v1 --output-root "$out/prepare"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context anchor-order-probe --prompt-profile primary_support_v1 --mock --output-root "$out/probe"
```

Probe vẫn tùy chọn, sáu ca synthetic, chỉ stage1; riêng profile mới có hai TARGET
refs `t-synthetic` và `t-support`, yêu cầu primary là ref đầu và supporting không
rỗng `["t-support"]` trong cả sáu ca, gồm compliant1/2/3. Mock/build instructions
dùng đúng keys mới; bốn probe profile cũ giữ nguyên. Đây vẫn chỉ là kiểm tra
hình thức, không semantic hoặc bằng chứng toàn bộ constraints.
Wire/profile/prompt/code/payload binding phân biệt cache, cần
prepare/root mới; không migrate artifact cũ. Local protocol/mock không chứng
minh decoder live, semantic quality, retrieval hoặc tiết kiệm token.

Sửa thứ tự anchor (kế hoạch27): stage1 grammar dùng slot1/2/3 với literal ID
riêng, chỉ cho prefix [],[1],[1,2],[1,2,3]. Positive cần ít nhất một anchor;
negative rỗng. Validator không nới. Receipt lỗi mới có error_code an toàn như
anchor_slot_order bên cạnh error=output_protocol_validation để tương thích.
Đây là ràng buộc định danh, không phải thứ hạng hoặc chứng minh AU đúng.

Probe riêng dùng sáu tình huống tổng hợp, không đọc corpus và không chạy stage2:

```powershell
$out = "knowledge_base/pipeline_v1/outputs/anchor_order_probe_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context anchor-order-probe --mock --output-root "$out/local"
# Chỉ chạy lệnh tiếp theo khi chủ động muốn gọi endpoint.
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context anchor-order-probe --execute --concurrency 1 --output-root "$out/live"
```

Không có --mock/--execute thì chỉ chuẩn bị. Mặc định profile evidence_first_v1;
có thể chọn --prompt-profile khác với root mới. Probe hiện fresh-root-only,
không resume; không tạo root mới để tự retry mù sau lỗi. Xem receipts và ledger
trước khi chạy thêm. Endpoint exit0 yêu cầu mọi response verified và positive
không rỗng; output valid nhưng negative/unresolved là inconclusive, không mở
khóa extraction. Số anchor khác yêu cầu nhưng vẫn hợp lệ được báo riêng là
instruction mismatch, không tự thành lỗi grammar. Xem probe.json, workload.json,
runtime_ledger.json, receipts và attempts. Readiness dùng cùng transport runner.
Mock không xác nhận decoder live hoặc ngữ nghĩa; endpoint probe chỉ kiểm hình thức.
Grammar/payload/code hash mới yêu cầu prepare/root mới cho workload extraction;
artifact invalid cũ giữ nguyên, không tự biến thành PASS.

Profile opt-in `evidence_first_v1` (design26) dùng stage1 wire riêng
`au-target-selection-v1`: anchor chỉ có `anchor_id`, `kind`, `target_ref_ids`,
`needs_context`; top-level decision/reason giữ các enum hiện có. Model không
viết `primary_claim`; host từ chối field này trong raw selection. Tối đa3 anchor,
8 refs/anchor; vượt cap bị từ chối, không tự cắt refs. Stage1 EF có hướng dẫn
riêng, không kế thừa yêu cầu viết claim của baseline/attribution/grouping.

Host sắp evidence theo source offsets và giữ nguyên từng span/hash/quote.
Normalized anchor có `claim_origin=host_extracted`,
`primary_representation=extractive_source_spans_with_explicit_gaps`,
`primary_gaps=[{start_char,end_char}, ...]`. Field tương thích `primary_claim`
là trích xuất nguồn do host dựng, không phải semantic claim tổng hợp:
các span liền nhau nối nguyên văn; giữa span rời có marker `[GAP start:end]`.
`primary_evidence` chứa từng span gốc và là evidence chuẩn để kiểm nguồn.
Không áp cap300 lên nguồn host trích; giới hạn300 của text model và supplements
lịch sử vẫn giữ. Source được chọn không tự chứng minh legal eligibility.

Stage2 EF giữ wire đầu ra `au-context-supplement-v2` và tối đa một job/TARGET.
Model INPUT chỉ gửi quotes TARGET đã chọn **một lần** qua `primary_evidence`,
kèm `primary_representation` và `primary_gaps`; bỏ field tương thích
`primary_claim` khỏi INPUT để tránh lặp nguồn. Host normalized/result vẫn giữ
field đó. Hướng dẫn EF stage2 giải thích span rời không phải một quote liên tục;
context chỉ qualify/attribute evidence đã khóa. Không gửi lại TARGET chưa chọn,
không có request diễn giải bổ sung. `build_stage2` revalidate raw selection đúng
keys/version hoặc normalized EF được host dựng lại và so sánh toàn bộ để chặn
thay đổi derived evidence/provenance. Mock fixture dùng wire selection thật.

CLI prepare nhận `--prompt-profile evidence_first_v1`; default vẫn baseline.
Profile/prompt hash, EF wire version trong request identity và code/payload hash
phân biệt cache; phải prepare/root mới khi code đổi. Các profile lịch sử và
payload stage2 của chúng giữ nguyên. Không thay retry, env, worker hay deploy.
Local prepare/preflight/mock/resume chỉ kiểm protocol; live decoder và semantic
quality cần đánh giá riêng, chưa được chứng minh bởi triển khai này.

Module thử nghiệm theo design24 và profile opt-in của design25: giữ32 TARGET của frozen presentation manifest,
packet **G** gốc, Qwen/Qwen3.5-9B, thinking=false, output cap800. Không thay P0/P1,
schema dùng chung, model hoặc reranker. Context chỉ lấy trong catalog G đã khóa;
chưa có tìm context xa, lượt ngữ nghĩa thứ ba hay tự dispatch TARGET mới.

Stage1 chỉ nhận atom được cắt đúng phần giao với span TARGET. Không đưa
CONTEXT_PADDING vào prompt. Ref do host cấp giữ atom ID gốc, case/source hash,
offset và quote nguyên văn. Model chọn tối đa ba anchor ID hữu hạn, một hoặc
nhiều TARGET refs, kind, primary_claim dự kiến ngắn được TARGET hỗ trợ và enum
needs_context. Claim dự kiến chưa phải kết luận pháp lý đã xác minh. TARGET chưa
đủ tạo anchor có thể trả needs_context/unresolved không anchor; không ép negative. Anchor
đủ thông tin trở thành provisional AU trực tiếp, không gọi stage2. Global
unresolved vẫn unresolved dù đã có draft. Holding cụ thể hoặc application về
thủ tục có thể là AU dù không nêu abstract rule. Prompt dùng ví dụ synthetic ngắn
để phân biệt với fact, editorial, lời đương sự và attribution chưa rõ; ví dụ
không phải evidence hoặc gold.

Stage2 tối đa **một job mỗi TARGET**, chứa tất cả locked anchors. Prompt chỉ nhận
quotes của primary refs đã chọn, không đọc lại toàn TARGET, cùng context G
(gồm padding đã cắt khỏi stage1). Mỗi anchor có quyết định keep/reject/unresolved;
bổ sung condition/exception/speaker/scope phải có context refs hữu hạn. Host giữ
nguyên primary claim, kind và primary evidence, lưu supplements riêng, không nối
chúng thành legal conclusion. Draft sai phải reject/unresolved, không rewrite.
Draft bị khóa có thể gây thiên lệch khi đọc context; ID và khóa cơ học không bảo
đảm ownership hoặc chất lượng ngữ nghĩa.

Common Stage2 gate áp dụng cho **mọi profile**: tối đa một supplement mỗi slot,
theo thứ tự condition → exception → speaker → scope; gom mọi context ref cần
thiết của slot vào cùng item (tối đa8 refs). Không phải điền đủ bốn slot.
condition là prerequisite, exception là ngoại lệ, speaker là người nói/nguồn
được evidence hỗ trợ. scope là domain, chủ thể, tình huống hoặc giới hạn áp dụng
của proposition đã khóa; không chứa ghi chú chung, ngày tháng, diễn biến hay
rationale. Mỗi fact mới trong text phải được quote context đã cite hỗ trợ;
ID hợp lệ không chứng minh support ngữ nghĩa. Lời đương sự không phải endorsement
của tòa; không thêm primary conclusion hay suy mandatory requirement từ ví dụ
factual. Ví dụ synthetic: “license rule only applies to commercial vehicles”
hỗ trợ scope; “respondent says delay harmless” không chứng minh mandatory warning.
Các ví dụ tự tạo, không lấy KOS hoặc đoạn calibration làm evidence.

Không có qualifying/attribution information hữu ích được hỗ trợ thì dùng
`supplements=[]`. Nếu context thiết yếu còn thiếu, anchor phải unresolved,
không keep/global complete; dùng `qualification_unresolved`, `unclear_attribution`
hoặc `context_insufficient` phù hợp và global reason tương thích decision.
Không ép supplement để che bất định. Cap text300 chars, refs8, output800 giữ nguyên.

Không có anchor thì `build_stage2` luôn trả `[]`, bất kể needs_context flags.
Stage1 needs_context/unresolved không anchor được host tự ghi vào revisit queue
với status `target_review_required`, reason code và `reason_text` tiếng Việt do
host ánh xạ; không cần gọi người gán nhãn để tạo queue. Queue không có cơ chế tự
dispatch hoặc agent loop; không promote thành negative. Nhánh stage2 không anchor
chỉ phòng vệ protocol khi caller dựng job thủ công: chỉ cho phép
unresolved/revisit_target, không tạo AU từ context. Global revisit không promote
anchor thành AU sẵn sàng.

API cho Main/tester:

- `prepare(output_root, *, manifest=DEFAULT_MANIFEST, parent=DEFAULT_PARENT, cfg=None, prompt_profile='baseline_v2')`
- `preflight(workload_or_path, *, cfg=None)`
- `build_stage1(row, identity) -> job`
- `validate_stage1(model_json, job) -> normalized`
- `build_stage2(row, normalized_stage1, identity) -> [] | [job]`
- `validate_stage2(model_json, job) -> normalized`
- `runner.run(workload_or_path, *, output_root, cfg=None, execute=False, mock=False, concurrency=4, target_ids=None, opener=urlopen)`

`prompts.py` giữ ba profile lịch sử cùng hai profile selection opt-in:

- `baseline_v2` mặc định: common INSTRUCTIONS và stage1 TARGET_INSTRUCTIONS
  giữ nguyên chính xác baseline v2. Literal CONTEXT_INSTRUCTIONS giữ nguyên làm
  historical base; `instructions_for` append `CONTEXT_EVIDENCE_ADDITION` vào stage2.
  Các alias cùng tên trong `core` vẫn khả dụng.
- `attribution_v1`: baseline + hướng dẫn attribution ngắn và đối chứng synthetic
  tax/license tự tạo. Giữ cited origin/reporting/current voice trong primary_claim
  khi nguồn hỗ trợ; bất định dùng speaker và unclear_attribution hiện có, không
  bắt buộc taxonomy voice hoàn chỉnh. Thêm 529 byte UTF-8 mỗi stage1 (kể newline).
- `legal_point_v1`: attribution + hướng dẫn nhóm holding/rationale cùng một AU,
  nhiều refs; factual premise không tự thành holding riêng; rule/exception khác
  nhau vẫn riêng. Ba anchor là trần, không phải quota. Thêm 499 byte so với
  attribution (1028 byte so với baseline, kể newline) mỗi stage1.

Ba profile lịch sử dùng **chính xác cùng instruction stage2 mới**: historical base +
newline + CONTEXT_EVIDENCE_ADDITION. Common Stage2 gate fix này khác instruction
stage2 trong snapshot cũ; exact stage1 baseline và mọi stage1 profile additions
được bảo toàn. Snapshot/artifact lịch sử không đổi; primary đã khóa vẫn không
được rewrite. Không thêm step, model, tool hay field trong model contract; version
v2 giữ nguyên. Profile là metadata của host, không thêm field profile vào INPUT
của model. `build_stage1(row, identity)` mặc định baseline nếu fixture thiếu
prompt_profile; nếu row khai prompt_sha thì hash phải đúng.

Prepare khóa `prompt_profile` và `prompt_sha` ở workload cùng mỗi row. Hash là
SHA256 của UTF-8 compact JSON array `[stage1_prefix, stage2_prefix]`, mỗi prefix
gồm common instructions, newline, stage instructions và `\nINPUT:\n`. Hash này
bind đúng instruction; payload hash bind thêm toàn source/ID/grammar. Preflight
kiểm lại profile/hash và row dựng từ clipped source nguyên vẹn, báo byte tổng,
byte baseline và delta. Request identity chứa profile/hash nên payload/job ID
khác nhau kể cả stage2; chỉ instructions stage2 giống nhau. Run report và kết quả
từng TARGET ghi profile/hash; receipt vẫn bind code và workload như trước.

Chọn profile ở `prepare --prompt-profile baseline_v2|attribution_v1|legal_point_v1|evidence_first_v1|primary_support_v1`
hoặc `anchor-order-probe --prompt-profile ...`.
Preflight/run không có runtime override; CLI từ chối flag đó ngoài prepare.
Ví dụ attribution opt-in, dùng root mới:

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context prepare --prompt-profile attribution_v1 --output-root "$base/attribution_prepare"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context preflight --workload "$base/attribution_prepare/workload.json" --output-root "$base/attribution_preflight"
```

Prompt hash đổi cho mọi profile do stage2 prefix mới; code hash tự bao gồm
`prompts.py`; workload đã prepare bằng code cũ bị chặn.
Không migrate workload/ledger hoặc sửa artifact lịch sử: prepare và run trong
root mới, không cần sửa `.env` hoặc deploy. Profile được giữ/bỏ dựa trên đối chứng ngữ nghĩa riêng; baseline vẫn
mặc định, chưa promote attribution/grouping qua kiểm protocol hoặc mock. Hướng
dẫn synthetic không phải evidence/gold và không rewrite source.

contracts.py định nghĩa version/enum và tập keys chính xác; model không tự ghi
offset. Hai grammar đều là JSON EBNF có root, ID/enum hữu hạn. Host chặn ref,
slot, needs enum, anchor và JSON object key trùng; kiểm string length và nhất
quán decision. V2 chỉ nhận reason code tương thích decision theo map trong
contracts.py; không nhận free-text reason. Global output và anchor stage2 được
thêm reason_text chính xác từ REASON_TEXT_VI của host. build_stage2 loại các keys
normalization trước khi revalidate, rồi dựng lại evidence từ catalog. Grammar stage2 khóa thứ tự/số lượng/ID anchor. **Chưa xác minh
compile grammar** vì venv không có xgrammar; chưa kiểm grammar mới trên remote.
Cần đợt remote probe hai TARGET được cho phép riêng trước full32. Module không
tự thực hiện probe hoặc deploy.

Lệnh local từ repo root (PowerShell):

```powershell
$base = "knowledge_base/pipeline_v1/outputs/au_target_context_$(Get-Date -Format yyyyMMdd_HHmmss)"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context prepare --output-root "$base/final_prepare"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context preflight --workload "$base/final_prepare/workload.json" --output-root "$base/final_preflight"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context run --workload "$base/final_prepare/workload.json" --output-root "$base/final_dryrun"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context run --workload "$base/final_prepare/workload.json" --output-root "$base/final_mock" --mock --concurrency 4
```

Lặp lệnh mock với cùng output root để resume cache. --target-id có thể lặp trên
run để chọn một/hai TARGET smoke mà không sửa manifest; mặc định đủ32. Selection
và concurrency tham gia cache binding. Prepare/execution roots phải là các thư
mục ngang hàng: guard chặn overlap với input, source và frozen artifacts **ở cả
hai chiều**. Prepare/preflight không ghi đè report. Run chỉ nhận root mới hoặc
ledger đồng nhất. Writer lock chặn hai process cùng ghi; chỉ bỏ stale lock khi
đã xác nhận process cũ dừng. Code/config/source đổi làm cache không hợp lệ; giữ
checks lịch sử và dùng prepare/root mới. Giữ nguyên các root v1 và parent frozen
cũ để tham khảo; không migrate response invalid, không tự gọi lại inference khi
đổi sang v2. Workload v2 phải được prepare mới và execution dùng root mới.

Chỉ run --execute mở quyền remote. CLI đọc AU runtime env qua study_config,
không sửa .env; dùng complete_job với digest job ID và PairedTransport riêng
mỗi worker. Mock thay provider bằng jobs server giả local nhưng vẫn đi qua
GET/POST envelope và accounting thật; provider POST bằng0. Text mock là fixture
synthetic, không phải kết quả AU có chất lượng đã kiểm.

Batch là job độc lập, C1..4; không ghép TARGET trong prompt. Aggregate RLock khóa
reserve/counters/ledger/receipt commit, network nằm ngoài lock. Recovery permit
riêng từng worker. Readiness mặc định600s; job wait dùng config, fallback1800s.
Retry cần hai Unknown-job response chính thức mới cùng health ready; không gửi
lại mù job đã quan sát/ACK. Caps bền qua resume:64 logical jobs,100 POST attempts,
800000 prompt-byte reservation,80000 output tokens. Byte reservation không phải
token provider đã đo. Không tự gọi warmup/probe POST.

Đồng hồ deadline/backoff dùng `time.perf_counter()` để tránh tick thô của
`time.monotonic()` trên Windows khi mock dùng backoff 1ms. Guard thời gian vẫn
giữ nguyên. Lỗi budget hoặc policy của host được lưu pending, không coi là lỗi
JSON do provider và không biến thành kết quả terminal để bỏ qua khi resume.

Artifact: workload/preflight, runtime_ledger.json, attempt receipts, job receipts
raw/normalized, run.json, kết quả từng TARGET và revisit queue target_review_required. Receipt
terminal được reuse; pending retrieve đúng digest. Lỗi transport/protocol từng
job được cô lập. Trước HTTP khi resume, host kiểm selection, job/payload dự kiến,
source binding, normalized response, attempt identity và receipt hash. Crash sau
reserve giữ unknown usage, không coi là chưa phát sinh request.

Report tách protocol và ngữ nghĩa: complete nghĩa là mọi job protocol verified;
failed/invalid terminal cho incomplete với terminal_done=true; pending báo
pending. Unknown jobs/attempts được ghi rõ, kể cả POST trước retry còn uncertain;
provider total là null khi thiếu evidence. Known usage chỉ là observed subtotal.
POST ACK latency, elapsed wall, client latency/poll từng stage và server inference
quan sát được là các trường riêng. Chưa đo riêng readiness duration. Protocol
completion không chứng minh semantic quality, tiết kiệm hay retrieval hiệu quả.
