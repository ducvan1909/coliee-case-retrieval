# Cơ sở quyết định P2: SourceBlock và AnalysisRegion cho preprocessing AU

> **Trạng thái:** P2 đã được chọn làm kiến trúc hiện hành trong `03_decision_log.md`, `04_pipeline_spec.md`, `05_experiment_plan.md` và `09_kb_build_plan.md`. File này giữ lập luận, phương án đối chứng, rủi ro và chi tiết để truy vết quyết định; khi có xung đột, `04_pipeline_spec.md` là nguồn đặc tả chính. P2 chưa được implement hoặc xác nhận bằng pilot. Phạm vi không gồm NN–AU matching, retrieval view, reranker hoặc chọn case cuối.

## 1. Vấn đề cần sửa

Thiết kế trước P2 đi theo chuỗi `sentence atom → boundary scorer → LegalUnit partition → AU extraction`. Hướng đó có ba giả định chưa được chứng minh:

1. tồn tại một partition LegalUnit duy nhất phù hợp cho speaker, condition, legal point và AU;
2. lỗi tách sentence có thể được sửa đầy đủ bằng cách ghép lại;
3. boundary F1 cao sẽ đồng thời tăng AU recall và giảm token.

Trong source hiện tại, paragraph marker dạng `[số]` là structural signal mạnh nhưng không phải semantic boundary. Một paragraph có thể chứa nhiều proposition; một AU hoặc condition có thể chạy qua nhiều paragraph. Vì vậy proposal này giữ paragraph/block làm cấu trúc nguồn, còn context đọc là view tạm có thể chồng lấn.

## 2. Đối chiếu với các quyết định đã loại bỏ

| Ý trong đề xuất ban đầu | Xung đột/rủi ro từ audit cũ | Quyết định trong proposal này |
|---|---|---|
| Dựng block tree đầy đủ | Heading có thể thiếu/sai; marker/heading hard boundary đã bị bác bỏ | **Bỏ tree bắt buộc.** Dùng danh sách SourceBlock có thứ tự và structural relations tùy chọn |
| Dựng semantic dependency graph toàn corpus trước AU | Gần với full KG/enrichment chưa có bằng chứng; tăng compute và lỗi lan truyền | **Bỏ global semantic graph.** Chỉ lưu observed structure, worker hints và context obligations; quan hệ pháp lý phải gắn với AU evidence |
| Materialize AnalysisRegion cho mọi block | Có thể lặp lỗi V15: gần như mọi paragraph active, payload/schema phình | **Bỏ materialization eager.** Region được dựng theo batch khi AU extraction chạy; cache chỉ lưu manifest/SpanRef |
| Sentence và paragraph cùng là candidate output | V14 đã gặp parent–child overlap và duplicate payload | Request chỉ có **một mức target là SourceBlock**; SentenceAtom chỉ là địa chỉ exact span, không phải candidate song song |
| Heading quyết định section và context | Heading false positive/thiếu; structure recognition vẫn là open problem | Heading chỉ tạo structural hint; thiếu  heading giữ `null/unknown`, không sinh heading giả |
| Mọi worker chạy toàn corpus | NER/term/role transfer và compute chưa được chứng minh | Baseline chỉ dùng structural/citation/quote rules; worker khác phải qua ablation và throughput gate |
| LLM quyết định boundary trên toàn corpus | Token cao, protocol/schema failures và chưa có boundary gold tự nhiên | Không dùng LLM làm global boundary scorer; model ngôn ngữ chỉ làm AU extraction và repair có ngân sách |
| Agent repair đọc lại toàn case | Tái tạo context lặp V13–V15 | Repair chỉ nhận unresolved target với bounded region; whole-case provider read không phải default |
| Global finalizer hoặc schema có field theo mọi paragraph | Đã gây single-point failure và schema/payload lớn | Output fixed schema theo batch, chỉ trả `processed_target_ids`, AU candidates và context requests |
| Structure/schema PASS chứng minh semantic quality | Audit đã có omission, wrong kind, attribution và heading false positive | Báo riêng structural validity, semantic AU quality và run completion |
| Full RDF/LKG hoặc distributed orchestration | Không có benefit đủ cho pilot | JSONL/SQLite + versioned SpanRef/sidecar; không RDF/microservice |

Những bất biến vẫn giữ:

- source/hash/exact offsets là nguồn sự thật;
- marker/heading chỉ là signal, không là semantic truth;
- NER không suy speaker; citation không chứng minh treatment; rhetorical role không tự thành AU;
- annotation dự đoán có status, producer, version và provenance;
- AU accepted phải có exact evidence và witness theo acceptance profile;
- Issue vẫn là metadata mở; proposal này không dùng Issue để nối NN–AU;
- cache, retry, resume và invalidation theo fingerprint;
- model extraction, repair và retrieval về sau có thể khác nhau.

## 3. Kiến trúc đề xuất

```text
Immutable CaseSource
  ↓
Structural pre-pass
  ↓
Ordered SourceBlock map + SentenceAtom addresses
  ↓
Minimal local sidecars + structural relations
  ↓
Batch scheduler và AnalysisRegion manifest tạm
  ↓
Few-shot AU extraction model
  ↓
Host span validation, dedup và coverage ledger
  ↓
Selective repair
  ↓
AU store + Issue proposal/link pipeline hiện hành
```

Không có bước tạo partition semantic bắt buộc phủ source. `LegalUnit` chỉ được giữ làm arm đối chứng để pilot có thể bác bỏ P2.

## 4. Lớp dữ liệu canonical

### 4.1. CaseSource

```text
CaseSource
  case_id
  source_version
  source_hash
  text_ref
  char_length
  metadata
```

Text nguồn không bị chép vào từng block hoặc region.

### 4.2. SourceBlock

`SourceBlock` là đơn vị cấu trúc quan sát được, không phải AU hoặc LegalUnit.

```text
SourceBlock
  block_id
  case_id
  order
  block_type
  content_span
  marker_span?
  parser_confidence
  source_hash
  producer_version
```

`block_type` tối thiểu:

```text
numbered_paragraph
unnumbered_paragraph
heading
list_item
quotation_block
footnote
table_or_form
editorial
unknown
```

Mọi ký tự nguồn phải truy cập được. Các SourceBlock canonical là **một lớp block lá không chồng lấn**; whitespace/marker giữa block vẫn có SpanRef hoặc thuộc block theo policy đã version hóa. `quotation_block`, `list_item` hoặc `footnote` chỉ là block riêng khi chúng đứng độc lập ở lớp lá. Quotation/list/citation nằm bên trong numbered paragraph được lưu như structural span/annotation của paragraph đó, không tạo thêm SourceBlock chồng lấn. Quy tắc này ngăn lặp lại lỗi paragraph và sentence/child cùng được chọn như hai item độc lập.

### 4.3. SentenceAtom

SentenceAtom chỉ là địa chỉ bên trong SourceBlock:

```text
SentenceAtom
  atom_id
  block_id
  order_in_block
  source_span
  protected_span_refs[]
  source_hash
```

SentenceAtom không giới hạn AU. AU có thể nằm trong một atom, nhiều atom hoặc nhiều block.

### 4.4. StructuralRelation

Chỉ biểu diễn cấu trúc bề mặt có evidence:

```text
StructuralRelation
  relation_id
  relation_type
  source_block_id
  target_block_id
  evidence_spans[]
  status
  producer
  version
```

Các loại ban đầu:

```text
heading_governs
list_member_of
quotation_member_of
footnote_of
continues_layout
```

Structural span lồng bên trong block dùng exact `SpanRef` và annotation sidecar; nó không cần node SourceBlock hoặc parent tree riêng. `StructuralRelation` chỉ nối các block lá khi quan hệ thực sự đi qua block, chẳng hạn heading riêng chi phối các paragraph sau hoặc một list gồm nhiều list-item block.

Không lưu `qualifies`, `responds_to`, `condition_for` hoặc `same_legal_point` như global accepted edge ở bước này. Những quan hệ đó chỉ được giữ dưới dạng context hint/unresolved hoặc witness cụ thể trong AU.

### 4.5. Adjacency

Adjacency được suy từ `SourceBlock.order`; không cần một graph semantic:

```text
previous(block_id)
next(block_id)
range(first_block_id, last_block_id)
```

Có thể materialize `previous_id`/`next_id` để tăng tốc, nhưng chúng là derived fields và phải tái tạo được.

## 5. Structural pre-pass

Structural pre-pass chạy local, không dùng LLM:

1. phát hiện line/paragraph breaks và gộp wrapped lines;
2. phát hiện `[số]` ở đầu paragraph;
3. bảo vệ citation year, case name, abbreviation, quotation và list marker;
4. phát hiện heading/list/quote/footnote/table/editorial block;
5. tạo SourceBlock map có exact offsets;
6. tạo SentenceAtom bên trong từng block;
7. tạo structural relations có evidence.

### 5.1. Xử lý `[số]`

`[12]` được coi là paragraph-marker candidate khi thỏa pattern vị trí và context; sequence continuity chỉ tăng confidence, không là điều kiện cứng. `[1987]` trong citation hoặc bracket number nằm giữa câu phải được bảo vệ.

Marker được lưu tách:

```text
marker_span  = exact span của "[12]"
content_span = phần nội dung paragraph
```

### 5.2. Heading thiếu hoặc sai

- Không tạo heading giả để hoàn thành tree.
- `heading_governs` vắng thì block vẫn nối với document root bằng order/adjacency.
- Heading candidate confidence thấp không trở thành hard boundary.
- Topic/role prediction không được ghi đè cấu trúc nguồn; nếu cần chỉ tạo annotation candidate.

### 5.3. Paragraph quá dài

Paragraph vẫn là một SourceBlock. Scheduler có thể chia nó thành các target slices theo SentenceAtom để phù hợp context cap, nhưng slice là derived workload và luôn giữ `parent_block_id`; không tạo canonical block hoặc LegalUnit mới nếu chưa qua phép thử.

## 6. ContextHint và ContextObligation

Để tránh global semantic graph, proposal dùng hai record nhẹ.

### 6.1. ContextHint

Worker local có thể đề xuất:

```text
ContextHint
  hint_id
  target_block_id
  hint_type
  related_block_ids[]
  evidence_spans[]
  status              # candidate | accepted_by_contract | unresolved
  producer
  confidence?
```

Loại hint cho phép:

```text
open_quote
open_list
dependent_lead_in
speaker_continuity_candidate
topic_continuity_candidate
condition_cue_candidate
reference_to_previous
```

Hint chỉ giúp dựng context; nó không khẳng định quan hệ pháp lý.

### 6.2. ContextObligation

Obligation ghi điều model/host còn cần làm rõ:

```text
ContextObligation
  obligation_id
  target_id
  obligation_type
  requested_direction_or_ref
  reason
  status              # pending | satisfied | unresolved | budget_exhausted
  searched_spans[]
  stop_reason?
```

Ví dụ obligation:

```text
missing_speaker
possible_prior_condition
open_quotation
unresolved_reference
possible_following_qualification
```

## 7. AnalysisRegion là view tạm

`AnalysisRegion` không phải canonical text record và không được dựng eager cho mọi block.

```text
AnalysisRegionManifest
  region_id
  case_id
  target_block_ids[]
  target_slice_refs[]?
  context_span_refs[]
  included_hint_ids[]
  obligation_ids[]
  unique_source_chars
  repeated_source_chars
  estimated_input_tokens
  policy_version
  source_hash
  fingerprint
```

Region text được host render từ SpanRef khi dispatch. Cache lưu manifest và kết quả, không sao chép source thành một kho text mới.

### 7.1. Dựng region ban đầu

Với một nhóm target liền nhau:

1. thêm target spans;
2. thêm heading observed gần nhất nếu còn trong cap;
3. thêm block cần để đóng quote/list hoặc dependent lead-in;
4. thêm tối đa local neighbors theo policy;
5. gộp span chồng lấn trước khi render;
6. ghi lý do cho từng context span.

Không mở toàn section chỉ vì cùng heading. Không dùng NER/role/topic để hard-filter target.

### 7.2. Context expansion

Model có thể trả `needs_context` cùng obligation. Host chỉ mở theo tool/policy đã khóa, tối đa số expansion đã đăng ký. Vượt cap giữ `unresolved` hoặc `budget_exhausted`, không âm thầm kết luận `no_au`.

Whole-case scan bằng provider không phải default. Whole-case local inspection chỉ là control offline hoặc fallback đã ghi riêng chi phí.

### 7.3. Chồng lấn và ownership

- Mỗi SourceBlock xuất hiện làm primary target đúng một lần trong coverage workload, trừ retry/repair có ledger.
- Context block có thể xuất hiện ở nhiều region nhưng không trở thành target lặp.
- AU owner là block chứa `start_char` của AU; evidence/condition có thể nằm ở block khác.
- Exact/contained duplicate được host xử lý deterministic; ambiguous semantic duplicate chỉ vào bounded reconciliation, không global finalizer.

## 8. Lịch chạy toàn corpus và kiểm soát token

Phân tích AU trên toàn corpus vẫn có chi phí tuyến tính theo source; SourceBlock không tự làm bước này rẻ. Proposal chỉ được giữ nếu batching/cache làm chi phí tuyệt đối phù hợp.

### 8.1. Batch contract

Mỗi request dùng một granularity:

- target là một nhóm SourceBlock hoặc target slices có cùng parent block;
- SentenceAtom chỉ là địa chỉ để model chọn quote/span;
- không có field bắt buộc cho từng paragraph ngoài `processed_target_ids`;
- schema cố định, không chứa enum mọi block/sentence trong case;
- target/context spans được host deduplicate trước dispatch.

Các cap phải khóa trước pilot:

```text
max_target_blocks_or_slices
max_unique_source_chars
max_input_tokens
max_output_tokens
max_au_candidates
max_context_expansions
max_repairs
max_requests_per_case
```

Chạm cap tạo checkpoint và unresolved ledger; không tính dừng sớm là tiết kiệm thành công.

### 8.2. CoverageLedger

Host lưu:

```text
CoverageLedgerEntry
  target_id
  region_ids[]
  status              # pending | processed | needs_context | unresolved | error
  au_ids[]
  request_ids[]
  unique_chars_seen
  repeated_chars_seen
  stop_reason?
```

Ledger giúp phát hiện omission do target chưa xử lý mà không buộc schema model có một record semantic cho mọi paragraph.

### 8.3. Cache và resume

Cache key gồm:

```text
source_hash
target spans
context spans
hint/obligation versions
model/prompt/schema/config versions
```

Resume không gọi lại target có kết quả hợp lệ. Source/worker/policy đổi chỉ invalidate dependency closure. Báo riêng originating, charged và amortized cost.

## 9. AU extraction và repair

AU extraction model chạy zero-shot/few-shot; không fine-tune hoặc self-training trong đợt này. Tập nhãn thủ công dùng làm evaluation và few-shot examples.

### 9.1. Output tối thiểu

```text
AUExtractionBatch
  processed_target_ids[]
  au_candidates[]
    target_id
    evidence_atom_ids[]
    exact_quotes[]
    claim
    kind
    attribution_candidate
    condition_refs[]
    exception_refs[]
    limit_refs[]
    unknowns[]
  context_requests[]
  unresolved_target_ids[]
```

Model không được tin cậy để tự tính offsets. Host ánh xạ atom ID + exact quote về `[start_char, end_char)`, kiểm tra source hash và ownership.

### 9.2. `no_au`

`no_au` chỉ hợp lệ khi target đã được ghi trong `processed_target_ids`, context obligations bắt buộc đã satisfied/not-applicable và output qua host contract. Citation/marker/role vắng không đủ để kết luận `no_au`.

### 9.3. Repair

Repair model chỉ nhận:

- target unresolved hoặc output vi phạm acceptance profile;
- exact region + delta context cần thiết;
- lỗi/obligation cụ thể;
- fixed output schema.

Không repair toàn case và không yêu cầu repair model trùng extraction model.

## 10. Vai trò của LegalUnit trong pilot

P2 đã thay LegalUnit trong đặc tả hiện hành. Trong pilot, LegalUnit partition chỉ còn là arm đối chứng:

| Arm | Context unit | Ý nghĩa |
|---|---|---|
| P0 | Numbered/unnumbered paragraph với fixed neighbors | Baseline cấu trúc rẻ |
| P1 | Sentence → boundary scorer → global LegalUnit partition | Đối chứng kiến trúc cũ |
| P2 | Ordered SourceBlock + temporary AnalysisRegion | Kiến trúc hiện hành cần kiểm chứng |

Việc chọn P2 ở mức thiết kế không khóa kết quả pilot. Nếu P1 tương đương hoặc tốt hơn với chi phí thấp hơn, quyết định kiến trúc phải được mở lại. Nếu P0 tương đương, không giữ relation/hint/obligation chỉ vì chúng tạo nhiều metadata hơn.

## 11. Kế hoạch pilot trên năm án calibration

### Giai đoạn 1 — Offline, không gọi model

1. Parse SourceBlock cho năm án và round-trip toàn source.
2. Đo precision của `[số]`, heading, quote/list/footnote trên mẫu adjudicated.
3. Tạo SentenceAtom trong block và kiểm tra protected spans.
4. Dựng P0/P1/P2 manifests bằng mock.
5. Đo region size, overlap ratio, repeated chars, cap violations và invalidation.

### Giai đoạn 2 — Khóa nhãn và tình huống

Khóa AU exact spans, attribution, condition/exception/limit refs và context obligations trước khi xem output model. Phải có:

- heading thiếu hoặc sai;
- bracket year/citation dễ nhầm marker;
- paragraph dài nhiều proposition;
- AU chạy qua block;
- condition ở block trước/sau;
- party statement và court response;
- quotation/list chạy qua block;
- án dài nhưng ít AU;
- output hợp schema nhưng omission.

### Giai đoạn 3 — So ba arm

Dùng cùng AU model, few-shot examples, schema semantic và output cap. Chỉ context construction khác nhau. Chạy calibration để sửa contract; held-out riêng mới dùng quyết định.

## 12. Metrics và cổng quyết định

### 12.1. Cấu trúc

- source round-trip/hash/offset: bắt buộc 100%;
- SourceBlock coverage và overlap;
- marker/heading/quote/list precision-recall theo slice;
- parent-child false relation;
- resume/invalidation idempotence.

### 12.2. AU và context

- AU span precision/recall/F1;
- proposition faithfulness;
- attribution severe error;
- missing condition/exception/limit;
- cross-block AU recall;
- duplicate/fragment rate;
- unresolved và false `no_au` rate;
- context-obligation satisfaction.

### 12.3. Chi phí

- unique/repeated source chars và token;
- overlap ratio = rendered source chars / unique source chars;
- requests, expansion, retry và repair;
- provider input/output/reasoning tokens;
- CPU/GPU giờ, RAM/VRAM, wall-clock;
- cold build, resume và incremental update;
- dự toán toàn corpus theo phân bố độ dài, không chỉ trung bình năm án.

### 12.4. Quy tắc chọn/bỏ

- Bỏ P2 nếu structural validity không đạt tuyệt đối.
- Bỏ worker/hint không tạo gain AU/context ngoài độ bất định hoặc làm compute vượt gate.
- Bỏ semantic hint nếu chỉ làm tăng region size/repair mà không giảm omission.
- Bỏ P2 nếu gain chỉ xuất hiện khi whole-case provider read hoặc vượt cap.
- Không chọn P2 chỉ vì boundary metric tốt hơn; AU/context quality và chi phí tuyệt đối mới là tiêu chí.
- Nếu evidence chưa đủ power để loại trừ severe-error regression, kết luận `insufficient evidence`, không pass.
- Không tuyên bố cải thiện retrieval từ pilot preprocessing này.

## 13. Điểm yếu còn lại

1. AU extraction trên mọi target vẫn có thể quá đắt cho 9.556 án; proposal chưa chứng minh break-even.
2. Block parser có thể sai với OCR/wrapped lines và citation dạng lạ.
3. Bounded context vẫn có thể bỏ court response/condition ở xa.
4. Batch nhiều target có thể làm model over-select hoặc bỏ target; CoverageLedger chỉ phát hiện trạng thái xử lý, không chứng minh semantic completeness.
5. Overlapping region có thể tăng token nếu batching/cache không hiệu quả.
6. AU ownership theo start offset giải quyết duplicate kỹ thuật, không giải quyết semantic duplicate.
7. Tập calibration không đủ để kết luận chất lượng toàn corpus.

## 14. Trạng thái sau khi chấp nhận P2

- SourceBlock và AnalysisRegion đã thay global LegalUnit trong thiết kế hiện hành; LegalUnit chỉ còn là arm P1 đối chứng.
- Chưa chốt parser/model/worker, số block, batch size hoặc token cap; chúng phải được khóa qua pilot.
- Không chấp nhận semantic dependency graph, heading/marker hard boundary hoặc auto-skip block không citation/AU cue.
- Chưa chốt Issue alias hierarchy, NN–AU matching, retrieval view hoặc ranking.
- Chưa mở rộng sang KOS hoặc toàn corpus trước khi pilot và held-out gate đạt.
- Việc chấp nhận P2 ở mức thiết kế không phải bằng chứng rằng P2 tốt hơn P0/P1; `05_experiment_plan.md` có quyền loại P2 nếu dữ liệu không ủng hộ.

