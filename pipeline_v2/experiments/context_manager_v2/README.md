# CM2–CM3: integrated offline controller

Prototype riêng: `cli.py`/`stress.py` chỉ chạy offline; `live.py` đã được nối CM4
theo yêu cầu người dùng, gồm prepare local và run inference do user/AG chạy.
Xem `CM4.md` trước khi dùng lệnh run. Không deploy hoặc sửa production, CM1 đã
nghiệm thu, snapshots hay run cũ. Code/local PASS chưa là live-provider PASS.

## Thành phần và API

- `EvidenceStore(raw_reader)` kiểm full source hash, exact UTF-8 slice và canonical
  ref (kể cả provenance overlay). `window(record, offset, byte_limit, requested_span)`
  dùng `slice_record`, giữ components/hash và trả requested/offered/pending ranges.
  Không tóm tắt, không tự bỏ negation/exception hay suy đoạn đủ ý pháp lý.
- `Engine(directory, identity, tools, count_tokens, raw_reader, ..., hybrid_search)`
  tái dùng `AdaptiveHarness`, `M3Tools`, `RunState`, source guards và M4 assessment
  validator. `hybrid_search` trong offline CLI là response đã lưu, không khởi tạo
  model embedding; module transport chặn mọi lời gọi thực.
- `prepare()` dựng đầy đủ source-purpose tools cùng context tools, đếm prompt thật,
  kiểm hard cap 8.500/output 512, rồi ghi immutable manifest và admission.
- `reply(request_id, action, status)` nhận action scripted hoặc unknown/error, kiểm
  schema của admission đó, dịch source action theo policy hiện hành. Response
  malformed cũng được ghi, không silently retry. Mọi receipt ở đây là simulator,
  không phải receipt của provider.
- `execute_pending()` thực thi source action local, reload hoặc validator thật;
  context command chỉ ghi chuyển focus/page/continuation, không giả một source-read.
- `step(callback)` tiện cho script: prepare → callback chọn action → reply → execute.
  `inspect()` trả context, state và usage simulator; không gọi provider.

## Context và evidence lifecycle

Sau lượt live đầu tiên, bản `cm4-feedback-v3` bổ sung bounded action feedback,
ordered candidate list và boundary `results_ready`. Duplicate không phải no-hit.
Xem `LIVE_FEEDBACK_FIX.md` cho chẩn đoán, replay và namespace preflight mới;
không chạy lại namespace cũ bằng code mới.

Xem `MODEL_CONTEXT_FLOW.md` để có sơ đồ vòng model/host, bảng dữ liệu được lưu
và toàn bộ tools theo điều kiện cấp. Sửa sau nghiệm thu dùng version mới
`cm23-offline-v2-pair-progress`: tiến độ và missing reason gắn từng pair;
resume tiếp phần chưa đọc, explicit reload mới reset đọc lại từ đầu. Artifact
CM2–CM3 đã nghiệm thu trước đó giữ nguyên và không resume bằng code version mới.

Toàn bộ unique pool và exact per-search needs giữ trong ledger. Registry model
chỉ hiện một trang tối đa 5 ứng viên; shrink cards trước khi giảm cửa sổ raw để
vừa cap. Results giữ native order của operation tương ứng. Pool là kho first-seen,
không dùng điểm RRF giữa nhiều queries như global rank. Đây không phải reranker.

Trong stage reading, không cấp tool search tạo need mới hoặc chọn B khác.
Model có thể đọc tiếp, assessment hoặc ghi rõ evidence thiếu rồi chuyển focus.
Page controls không đổi focus; cursor bind revision và immutable request manifest.

Mỗi need–candidate có queue canonical root refs riêng. Khi park, giữ đầy đủ root
refs, offsets và pair targets bên ngoài prompt. Raw hiện tại chỉ có A/B của focus;
park không invalidates assessment. `reload_pair_evidence` nạp lại cặp hiện tại;
`resume_pair_evidence` ở trang parked đưa cặp cũ trở lại mà không search/source-read
lại. Trang parked có next/previous để các cặp ngoài trang vẫn truy cập được.

`continue_raw_evidence` trỏ đúng root, offset, pair và revision. Khi một root hết,
có route sang root tiếp theo. Root chỉ được đánh dấu hoàn tất tại action commit
sau response thành công, không khi mới offer. Reload rõ ràng mới reset coverage
cho lượt đọc lại; continuation thường không quay vòng về root đã hoàn tất.

`cm_coverage` và `cm_unoffered_raw_count` phân biệt phần được offer trong cửa sổ
hiện tại và các roots khác còn chờ. `pending_source_count` ở model view là pending
của tập evidence focus, không phải toàn bộ queue nội bộ RunState. Ledger giữ
canonical dữ liệu toàn run; phần không ở prompt không bị xóa khỏi pool/catalog.

Assessment đi qua `validate_assessment_state`: chỉ raw refs trong payload hiện tại,
đúng A/B và canonical catalog. Missing attribution/container/quotation giữ pending;
unknown có thể accepted về giao thức, không trở thành human gold. `prediction`
giữ pending_selection khi chưa có selector được nghiệm thu.

## Độ bền và drift

Manifest immutable gắn exact payload, schema đầy đủ, source prefix, context focus,
counter/code bindings. Schema context hợp nhất có `cm_schema_fingerprint`; schema
source riêng vẫn giữ fingerprint mà translator đã kiểm. Host không diễn giải
response cũ bằng registry mới nhất. Artifact thay đổi bị từ chối.

Crash sau admission hoặc trong source action giữ unknown và chặn run tiếp; không
resend, không xóa admission. Source drift qua prepare/source-read/reload dùng đường
`source_drift` của M4 để invalidates assessments phụ thuộc và dừng. Khi đọc lại
bytes đã có, canonical refs/provenance không bị thay; dedup không được làm mất
route để queue lại records đó.

Code binding gồm modules CM2/3, accepted CM1 core và chuỗi nguồn/validator/policy
hiện hành. Code/config/source/tokenizer thay đổi yêu cầu namespace mới. Không sửa
historical receipts/seals để resume qua guard.

## Kiểm local

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.cli --help

$cmReplay = 'cache/cm23-ag-replay-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.cli --output-dir $cmReplay

$cmStress = 'cache/cm23-ag-stress-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.stress --output-dir $cmStress
```

CLI replay local và module stress riêng; entry point inference riêng ở `live.py`.
Các đường dẫn evidence cuối xem `AG_CHECK.md` và
`REPORT.md` do Main tổng hợp. Mỗi output cần namespace mới; không ghi vào source
run. Replay source thật phải kiểm hashes trước/sau, dùng tokenizer pin, không đọc
gold. Corpus retrieval mới và recorded search replay phải được báo riêng; source
reads/within-case search local không được giả thành 0 chỉ vì không inference.

## Giới hạn nghiệm thu

Tất cả turns/receipts của Engine là scripted offline; `RunState.usage.requests`
đếm lượt mô phỏng, không phải request provider. Admitted token count là prompt
được đếm thật nhưng reported provider telemetry không được bịa. Reports phải tách
scripted turns, 0 inference mới, chi phí lịch sử và unknown rõ ràng.

Hiện kiểm source-aware byte windows và context fitting, chưa chứng minh model
chọn vùng đủ ngữ cảnh hay đủ raw cho pháp lý. Nếu tối thiểu catalog/window vẫn
không vừa, trả unfit và không admission. Metadata host/ledger vẫn tăng theo run;
Model view hiện ưu tiên một cửa sổ A và một cửa sổ B, không tự ghép nhiều đoạn
attribution rời vào cùng payload. Các roots còn lại phải mở qua continuation;
nếu chưa đủ quotation/attribution thì giữ pending/unknown theo validator. Việc
cửa sổ có chứa raw A/B không chứng minh đủ ngữ nghĩa pháp lý.
prompt bounded không phải bảo đảm CPU/RAM host bounded. Không tự thêm LLM summary,
subagent, MMR/reranker, đổi K/fusion/model/chunk/selector hay dùng holdout.

Trước CM4 cần AG review độc lập full catalog, continuation đa root, park/reload,
drift/unknown/resume, exact source refs và kết quả stress/replay. Engineering PASS
không chứng minh semantic correctness, pool recall hoặc final COLIEE F1.
