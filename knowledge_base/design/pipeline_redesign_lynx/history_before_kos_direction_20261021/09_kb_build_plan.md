# Kế hoạch xây KB theo kiến trúc P2

## 1. Mục tiêu

Xây KB có thể:

- mở lại nguyên văn và exact span;
- biết block nào đã được phân tích, block nào lỗi hoặc chưa xử lý;
- lưu AU có evidence, attribution và điều kiện;
- giữ Issue metadata mở mà không ép matching;
- cập nhật, resume và kiểm toán chi phí;
- cung cấp dữ liệu cho retrieval về sau mà không materialize text lặp.

Kế hoạch này chỉ bao gồm preprocessing và xây KB. Nó chưa triển khai NN–AU joining, candidate retrieval hoặc reranker.

## 2. Các kho dữ liệu cần tạo

| Kho | Nội dung | Canonical hay tạm |
|---|---|---|
| source_store | CaseSource, text ref, hash, metadata | Canonical |
| context_store | SourceBlock, SentenceAtom, structural relation, sidecar | Canonical có version |
| run_store | AnalysisRegionManifest, ContextHint/Obligation, CoverageLedger, request ledger | Theo run |
| au_store | AU candidate/accepted/rejected/unresolved và evidence | Canonical có version |
| issue_store | Issue, alias, proposal và link | Canonical có version |
| query_workspace | Query source, CiteSite, NN và trace | Theo query |

Source text chỉ lưu một lần. Block, atom, region và AU tham chiếu source bằng SpanRef.

## 3. Dữ liệu cần chuẩn bị

### 3.1. Source và cấu trúc

- corpus manifest và source hash;
- exact offsets;
- SourceBlock adjudication sample;
- paragraph marker, heading candidate, list, quote, footnote và editorial labels;
- hard cases: thiếu heading, bracket year, wrapped line, OCR noise và paragraph dài;
- structural relation evidence.

### 3.2. AU và context

- AU exact spans;
- kind;
- attribution;
- condition, exception và limit spans;
- context obligation cần thiết;
- hard negatives;
- cross-block AU examples;
- duplicate/fragment adjudication.

### 3.3. Issue

- preferred labels đã phân xử;
- alias candidate và false-equivalence examples;
- nil, unresolved và multi-Issue examples;
- provenance/version.

Issue labels không dùng làm NN–AU match labels trong đợt này.

### 3.4. Query

- marker và non-marker CiteSite;
- NN proposition/constraints/exact spans;
- leakage policy;
- citation đã che, không dùng gold hoặc bản không che.

## 4. Các giai đoạn xây dựng

### Giai đoạn A — Source contract

1. Kiểm kê corpus và khóa manifest.
2. Lưu source bất biến, hash và metadata.
3. Viết round-trip, offset và mutation tests.
4. Chốt dependency/invalidation contract.

Đầu ra: source_store và source validation report.

### Giai đoạn B — Structural pre-pass

1. Parse SourceBlock leaf có thứ tự và không chồng lấn.
2. Tạo SentenceAtom bên trong block.
3. Chạy baseline citation, marker, quote và speaker-cue rules.
4. Lưu sidecars và observed structural relations.
5. Audit parser trên calibration và development.

Đầu ra: context_store và parser error ledger.

Không gọi LLM ở giai đoạn A–B.

### Giai đoạn C — Scheduler và AnalysisRegion

1. Tạo primary target phủ mọi content SourceBlock; block vượt cap được chia thành derived slices theo SentenceAtom nhưng không đổi cấu trúc canonical.
2. Sinh ContextHint bằng rule local.
3. Batch target theo proximity và caps.
4. Dựng AnalysisRegionManifest bằng SpanRef.
5. Khởi tạo CoverageLedger.
6. Render text chỉ ngay trước request.

Đầu ra: versioned region policy, manifests và initial coverage ledger.

Không dùng agent ở bước này. Scheduler không được auto-skip block dựa trên citation/AU cue.

### Giai đoạn D — AU extraction

1. Khóa tập nhãn AU và few-shot examples.
2. Chọn model zero-shot/few-shot trên development; không fine-tune.
3. Chạy cùng fixed schema theo region manifests.
4. Host kiểm tra processed target ids, hash, span và duplicate.
5. Tạo ContextObligation khi thiếu context cụ thể.
6. Mở bounded context tối đa theo policy.
7. Route ca khó sang model/agent sửa theo budget.
8. Ghi AU và trạng thái CoverageLedger.

Đầu ra: au_store, obligation/repair ledger và cost report.

### Giai đoạn E — Issue metadata

1. Tạo IssueProposal từ evidence của AU/NN.
2. Chuẩn hóa kỹ thuật để lookup.
3. So preferred labels và accepted aliases.
4. Phân xử thành accepted link, nil, unresolved hoặc rejected.
5. Version registry, alias và link.

Không tự merge Issue bằng embedding/clustering; không dựng hierarchy hoặc dùng Issue làm gate.

### Giai đoạn F — CiteSite và NN

1. Khóa query source/hash.
2. Tạo CiteSite từ marker/citation cue với origin.
3. Dựng bounded context.
4. Trích NN và exact evidence.
5. Tạo IssueProposal/Link nếu có.
6. Kiểm tra leakage.

Đầu ra: query_workspace. Chưa tạo CandidatePair.

### Giai đoạn G — Snapshot và pilot

1. Publish versioned source/context/AU/Issue snapshot.
2. Chạy P0/P1/P2 trên năm calibration case.
3. Khóa development/held-out và chạy kế hoạch 05.
4. Đo cold build, resume và incremental update.
5. Chọn cấu hình cuối hoặc giữ baseline.
6. Chỉ sau gate mới lập kế hoạch mở rộng KOS/toàn corpus.

## 5. Build manifest

Mỗi build phải ghi:

- corpus/source snapshot và hash;
- parser, segmenter và worker versions;
- SourceBlock schema và region policy version;
- hint/obligation rules;
- AU model, prompt, schema, examples và generation settings;
- Issue registry/alias/link schema và snapshot hash;
- caps cho target, chars, input/output, candidate, expansion, retry và repair;
- cache fingerprint;
- run status, failure ledger và cost summary.

## 6. Tool và dữ liệu cần để sử dụng KB

### Source/context tools

- lấy case và block list;
- mở exact span;
- lấy sentence atoms/sidecars/relations;
- mở rộng context theo budget;
- dựng lại AnalysisRegion từ manifest.

### Audit/build tools

- xem target coverage;
- xem request, retry, expansion và repair trace;
- xem unresolved obligations;
- xác minh source hash/offset;
- invalidate theo dependency;
- resume build.

### AU/Issue/query tools

- lấy/list AU theo case, status và kind;
- mở AU evidence/context;
- lấy Issue, alias, proposal và link;
- lấy CiteSite và NN.

Retrieval agent về sau chỉ được coi AU accepted là AU view mặc định, nhưng vẫn có thể mở source/context qua tool. Annotation hoặc Issue thiếu không làm source biến mất.

## 7. Tiêu chí readiness

### Build readiness

- source round-trip/hash/offset và block coverage đạt 100%;
- mọi primary target phủ content block có trạng thái cuối rõ ràng;
- không có accepted AU thiếu evidence bắt buộc;
- lỗi không bị ghi thành no-AU;
- resume/invalidation không áp dụng lặp;
- token/compute/request/overlap được đo thật;
- P0/P1/P2 được so bằng cùng AU workload.

### Use readiness

- AU mở được exact evidence và context;
- source vẫn mở được khi annotation lỗi hoặc thiếu;
- CiteSite/NN truy về exact query source;
- Issue metadata luôn kèm status/provenance;
- alias/proposal/link không được thăng accepted chỉ do string/embedding match;
- schema PASS, CoverageLedger complete và semantic correctness được báo riêng.

Readiness này không xác nhận retrieval.

## 8. Thành phần phải benchmark

| Công việc | Baseline | Biến thể | Quyết định |
|---|---|---|---|
| SourceBlock parsing | Rule structural | Parser/model nhẹ nếu cần | Source/block accuracy và throughput |
| Sentence segmentation | Rule pháp lý | Segmenter khác | Protected-span error |
| Citation/reference | Regex/grammar | Sequence labeler | AU/context gain |
| NER | Tắt hoặc gazetteer | Legal NER | Gain trừ compute/transfer error |
| Terms/topic | Tắt | Term/small encoder | Region/context gain |
| Speaker/role | Cue rules | Sequence model | Attribution/AU gain |
| Context | P0 fixed neighbor | P1 LegalUnit; P2 hint/obligation | AU/context quality và absolute cost |
| AU extraction | Rule baseline | Few-shot language model | Recall, faithfulness, stability, throughput |
| Repair | Không repair | Model/agent theo queue | Gain theo budget |

## 9. Dữ liệu còn thiếu trước khi triển khai model

1. SourceBlock gold và parser hard cases.
2. AU gold có attribution/condition và cross-block examples.
3. Context obligation gold.
4. Hard-negative AU examples.
5. CiteSite/NN gold cho marker và zero-marker slices.
6. Issue examples có nil/unresolved/multi-label và false alias.
7. Benchmark phần cứng/model và ngân sách vận hành.

Thiếu các dữ liệu này vẫn cho phép triển khai source contract, parser rule, manifests và mock tests; chưa cho phép tuyên bố AU/NN semantic quality hoặc hiệu quả toàn corpus.
