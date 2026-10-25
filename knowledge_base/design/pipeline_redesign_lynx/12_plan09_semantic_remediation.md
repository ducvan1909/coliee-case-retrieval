# Kế hoạch sửa semantic cho Plan 09

## 1. Mục tiêu và giới hạn

Mục tiêu là sửa lỗi attribution đã biết, tìm các lỗi cùng loại trong 212 target đã checkpoint, hoàn tất 157 target còn thiếu của `099980` và quyết định model-silver có đủ ổn định để phục vụ phát triển hay không.

Kế hoạch này chỉ xây model-silver và không tạo human gold. Plan 10 tiếp tục khóa trong thời gian remediation; sau R1–R5, model-silver chỉ được mở cho thí nghiệm phát triển có nhãn `evaluation_against=model_silver`, không được dùng để tuyên bố chất lượng độc lập.

Finding khởi đầu là `P09-S01`: case `013948`, target `at-3f8c7b00587a03395a1070fa`. Evidence mở đầu bằng “Mr. Bayavuge submits…” nhưng proposal gán `holding/current_court`.

## 2. Tài liệu và dữ liệu bắt buộc

Mọi agent phải đọc trước khi làm:

- `04_pipeline_spec.md`, AuthorityUnit contract và quy tắc attribution;
- `05_experiment_plan.md`, metric omission/attribution/kind;
- `11_incremental_implementation_plans.md`, Kế hoạch 09 và cổng Plan 10;
- `pipeline_v1/au_annotation_guideline.v1.md` và `pipeline_v1/terra_au_annotation_prompt.v1.md`;
- `pipeline_v1/evaluation/plan09_independent_evaluation.md`;
- `pipeline_v1/reports/plan09_model_silver_progress.latest.json`;
- packet, source hash và canonical proposal tương ứng trong `outputs/plan09_au_gold_v1/`.

Nguồn quyết định semantic luôn là raw source được mở bằng `open_source`; không đọc `source.txt` bằng API có thể chuẩn hóa CRLF. KOS artifact, output cũ và Issue không được dùng làm gold.

## 3. Nhu cầu thực thi

### Model và agent

| Vai trò | Công cụ/model | Trách nhiệm | Không được làm |
|---|---|---|---|
| Agent điều phối | Chat chính, GPT-6 | khóa manifest, chia batch, quản lý checkpoint, tổng hợp metric và quyết định gate | tự sửa semantic label mà không có review record |
| Agent annotation | `gpt-5.6-terra`, reasoning `low` | hoàn tất target thiếu; review lại target rủi ro; tạo proposal hoặc amendment có exact evidence | gọi output là gold; sửa trực tiếp proposal cũ; suy speaker từ NER |
| Agent kiểm thử độc lập | `gpt-5.6-sol`, reasoning `low` | chạy validator/test; audit source độc lập; tìm attribution, kind, condition và omission errors | tạo nhãn thay cho annotation agent; coi schema PASS là semantic PASS |

Không cần Modal, Qwen, embedding hoặc NER model mới cho đợt sửa này. Cần quota Codex cho Terra để xử lý khoảng 40 batch còn thiếu và các batch review lại. Nếu quota chưa có, chỉ chạy được scanner, validator, report và test offline; trạng thái phải giữ `partial_resumable`.

### Công cụ và artifact

Cần dùng hoặc bổ sung:

- `open_source`, packet renderer và exact-span/hash validator hiện có;
- `checkpoint-model-proposal`, progress report và duplicate-owner guard;
- semantic defect registry và quarantine queue mới;
- amendment contract có `supersedes_proposal_id`, reviewer, reason và source hash; proposal gốc bất biến;
- risk scanner local dùng cue báo lời nói như `submits`, `argues`, `contends`, `according to`, tên party/Board/officer và quotation/reporting context;
- báo cáo coverage, số amendment, số lỗi nghiêm trọng còn mở và audit sample.

Scanner chỉ tạo hàng đợi. Cue không tự đổi speaker, kind hoặc AU.

## 4. Các bước triển khai tách cổng

### P09-R1 — Cách ly finding đã biết

1. Ghi `P09-S01` vào semantic defect registry với proposal, target, exact evidence và loại lỗi.
2. Đánh dấu target là `quarantined_pending_review`; không xóa hoặc sửa proposal gốc.
3. Sửa `lock-silver` để từ chối snapshot còn finding nghiêm trọng chưa đóng.

**Đạt khi:** proposal gốc còn nguyên; progress/report hiện quarantine; silver lock thất bại có mã lỗi xác định.

### P09-R2 — Tạo hàng đợi attribution-risk offline

Quét 212 target đã review và proposal của chúng. Đưa vào queue:

- AU có evidence chứa speaker/reporting cue;
- claim vượt ra ngoài evidence hoặc ghép lời party với nhận định của tòa;
- `holding/current_court` trong span có party, Board, officer, investigator hoặc lower-court voice;
- quotation/citation kéo qua ranh giới speaker;
- AU thiếu neighboring context cần để xác định người nói.

**Đạt khi:** queue tái lập từ source/proposal, có reason code và không tự đổi nhãn.

### P09-R3 — Review lại và sửa bằng amendment

Terra review từng target trong queue từ raw source và context lân cận. Kết quả là giữ nguyên, đổi `kind/attribution/evidence`, chuyển hard-negative hoặc `unresolved`. Mọi thay đổi đi qua amendment và validator; coordinator checkpoint tuần tự.

Agent kiểm thử đọc độc lập toàn bộ amendment nghiêm trọng. Nếu hai agent bất đồng, giữ `unresolved`; không biểu quyết bằng số model và không ép tạo AU.

**Đạt khi:** `P09-S01` được đóng bằng amendment/adjudication; không finding nghiêm trọng nào còn mở.

### P09-R4 — Hoàn tất `099980`

Resume đúng 157 target thiếu từ progress report. Mỗi batch dùng `open_source`, checkpoint nguyên tử và validator. Retry không tạo owner thứ hai. Không chạy song song các worker cùng sửa proposal manifest; nếu chạy song song, worker chỉ ghi staging ở shard riêng và một coordinator checkpoint tuần tự.

**Đạt khi:** 369/369 target có đúng một canonical owner; run lỗi được báo riêng; không dùng blanket hard-negative hoặc blanket unresolved.

### P09-R5 — Audit semantic độc lập

Agent kiểm thử thực hiện:

- review 100% attribution-risk queue và 100% amendment;
- review toàn bộ unresolved;
- sample phân tầng ít nhất 20% AU dương tính, tối thiểu 30 target, theo case và `kind`;
- sample ít nhất 10% hard-negative, tối thiểu 30 target, ưu tiên đoạn có court finding hoặc reporting cue.

Nếu tìm thấy lỗi nghiêm trọng trong một stratum, mở rộng review stratum đó lên 100%. Báo riêng attribution, wrong kind, lost condition/exception/limit, evidence-span error và omission. Sample audit là kiểm tra tìm lỗi, không tự trở thành precision/recall estimate.

**Đạt khi:** không còn lỗi nghiêm trọng chưa xử lý trong phạm vi đã review; coverage và limitations được báo đầy đủ.

### P09-R6 — Quyết định sử dụng model-silver

- **Model-silver cho phát triển:** được phép khi R1–R5 đạt; mọi metric ghi `evaluation_against=model_silver`.
- **Đánh giá:** chỉ báo chất lượng model-silver trong phạm vi audit; không gọi là gold hoặc thước đo độc lập.
- **Plan 10:** chỉ mở cho baseline phát triển sau khi R1–R5 đạt; không tự mở chỉ vì 369/369 hoặc validator PASS.

## 5. Đầu ra và tiêu chí dừng

Đầu ra gồm defect registry, risk queue, amendment schema/tool, canonical progress, báo cáo audit độc lập và quyết định sử dụng model-silver. Dừng và giữ `partial_resumable` nếu hết quota, source/hash đổi, duplicate owner xuất hiện, hoặc validator không thể chứng minh exact evidence.

Không được tuyên bố semantic PASS khi mới sửa `P09-S01`; lỗi đó là bằng chứng phải mở rộng audit, không phải bằng chứng đây là lỗi duy nhất.
