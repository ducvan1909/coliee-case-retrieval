# Đặc tả pipeline preprocessing và xây KB AU

## 1. Mục tiêu và ranh giới

Pipeline này chịu trách nhiệm:

1. bảo toàn source, provenance và địa chỉ exact span;
2. tạo bản đồ cấu trúc nguồn để model đọc theo vùng có kiểm soát;
3. trích xuất, sửa và lưu AuthorityUnit (AU) có evidence;
4. giữ Issue như nhãn mở có provenance cho AU và NoticeNeed (NN);
5. phát hiện marker/CiteSite và tạo NN từ query;
6. cung cấp source và context cho giai đoạn retrieval về sau.

Pipeline chưa chọn cách nối NN với AU, retrieval view, candidate generation, reranker hoặc tập án cuối. AU và NN có thể mang Issue metadata, nhưng Issue chưa phải điều kiện ghép cặp.

Các bất biến:

- source bất biến, source hash, exact span và provenance là nguồn sự thật;
- annotation dự đoán không tự trở thành kết luận pháp lý;
- SourceBlock và SentenceAtom là đơn vị địa chỉ/cấu trúc, không mặc nhiên là AU;
- không tạo một partition LegalUnit ngữ nghĩa bắt buộc phủ toàn source;
- mọi ký tự thuộc block nội dung phải nằm trong một primary target có trạng thái trong CoverageLedger; thiếu citation, marker hoặc AU cue không cho phép tự bỏ qua;
- AU phải truy về evidence nguyên văn cùng attribution, condition, exception và limit cần thiết;
- Issue là nhãn mở có trạng thái và provenance;
- marker là tín hiệu mạnh để neo CiteSite/NN nhưng không xác định authority được cite;
- lỗi một worker hoặc target không làm mất source hay kết quả hợp lệ khác;
- model trích AU đọc AnalysisRegion đã khóa; agent sửa chỉ đọc ca cần sửa.

~~~mermaid
flowchart TB
    S[CaseSource bất biến] --> SP[Structural pre-pass]
    SP --> SB[SourceBlock map có thứ tự]
    SB --> SA[SentenceAtom addresses]
    SA --> W[Sidecar và structural relations]
    W --> SC[Batch scheduler]
    SC --> AR[AnalysisRegion tạm có giới hạn]
    AR --> D[Model trích AU few-shot]
    D --> V[Host kiểm tra span và CoverageLedger]
    V --> O{Thiếu context hoặc bất định?}
    O -- Có --> CR[ContextObligation hoặc repair chọn lọc]
    O -- Không --> AU[AU store có provenance]
    CR --> AU
    AU -. Issue metadata .-> IS[Issue registry mở]
    Q[Query source] --> MK[Marker và citation cue detector]
    MK --> CS[CiteSite]
    CS --> NN[NoticeNeed]
    NN -. Issue metadata .-> IS
~~~

## 2. Các lớp lưu trữ

| Thành phần | Phủ dữ liệu | Vai trò |
|---|---:|---|
| Source store | Toàn bộ source | Nguồn kiểm chứng bất biến |
| SourceBlock map | Toàn bộ source; leaf block không chồng lấn | Địa chỉ cấu trúc và thứ tự nguồn |
| SentenceAtom map | Text bên trong block | Địa chỉ câu, không phải partition pháp lý |
| Annotation sidecar | Theo worker | Tín hiệu có version, xây lại được |
| Structural relation store | Quan hệ quan sát được | Adjacency, containment và continuation; không phải semantic graph |
| Region/run store | Theo lần chạy | Manifest, hint, obligation và coverage ledger |
| AU store | Candidate/accepted/rejected/unresolved | Proposition có evidence |
| Issue registry/link store | Issue mở và link từ AU/NN | Metadata semantic có provenance |
| Query workspace | CiteSite, NN và trace | Đầu vào cho nghiên cứu retrieval sau |

AnalysisRegion là gói context tạm cho một request. Text của region không được sao chép thành dữ liệu canonical; manifest chỉ tham chiếu SpanRef.

## 3. Pipeline corpus-time

### Bước 0 — Nạp source và khóa provenance

Host lưu nguyên văn, source hash, source version và case metadata. Offset dùng đoạn nửa mở [start char, end char). Source mới tạo version mới; parser, worker và model không được ghi lại source.

Điều kiện đạt là source round-trip, hash và offset đúng tuyệt đối.

### Bước 1 — Structural pre-pass và SourceBlock map

Parser local duyệt source theo thứ tự và tạo leaf SourceBlock không chồng lấn. Baseline nhận diện:

- paragraph marker như [12], đồng thời phân biệt bracket year/citation;
- đoạn văn, dòng độc lập, list item, quote block, footnote và vùng trống;
- heading candidate dựa trên hình thức nguồn;
- editorial hoặc boilerplate khi có evidence cấu trúc.

Heading chỉ là heading candidate; không gán loại ngữ nghĩa và không sinh heading giả. Thiếu heading làm section ref rỗng, không làm mất block.

Quote/list/citation nằm trong paragraph được lưu như nested sidecar span, không tạo child block chồng lấn. Structural relation chỉ phản ánh điều quan sát được: next, previous, contained in, continues và governed by heading khi evidence đủ mạnh.

Không dựng block tree bắt buộc và không suy quan hệ pháp lý hoặc chủ đề ở bước này.

### Bước 2 — SentenceAtom và feature workers local

Sentence segmenter tạo SentenceAtom bên trong từng SourceBlock. Nó bảo vệ abbreviation, tên án, citation, paragraph marker, quotation và list syntax. Sentence chỉ là địa chỉ nhỏ để gắn annotation và exact span.

P2 không chấm toàn bộ khe giữa các sentence để tạo một partition LegalUnit. Sentence boundary chỉ dùng để định địa chỉ, bảo vệ span và chia derived target khi một SourceBlock quá dài.

Baseline toàn corpus:

1. structural parser;
2. marker detector;
3. citation/reference rules;
4. quote-balance và speaker-cue rules;
5. sentence segmentation có luật pháp lý.

Worker tùy chọn gồm citation sequence labeler, NER pháp lý, terminology/topic-shift detector, speaker/quotation model và rhetorical-role sequence model. Chúng mặc định tắt; chỉ bật từng worker nếu held-out ablation cho thấy lợi ích AU/context đủ bù compute và chi phí cập nhật.

Mỗi Annotation phải có annotation id, case/source hash, SpanRef, worker type, value, confidence nếu có, status, producer/version, evidence refs và dependencies.

NER không được dùng để suy speaker. Citation mention không chứng minh treatment. Rhetorical role rule hoặc conclusion không tự trở thành AU. Term/entity/role output chỉ có thể đề xuất Issue.

### Bước 3 — Lập lịch và dựng AnalysisRegion

Mỗi SourceBlock nội dung tạo một primary target. Nếu block vượt cap, scheduler chia nó thành các AnalysisTargetSlice theo ranh giới SentenceAtom. Slice là workload phát sinh, giữ parent block id và exact span; nó không trở thành SourceBlock hay LegalUnit mới. Các primary target phải phủ toàn bộ nội dung block đúng một lần; phần context chồng lấn không được tính lại vào coverage.

Scheduler nhóm nhiều target gần nhau vào request để giảm prompt/schema lặp. Retry hoặc repair phải được ledger ghi rõ.

ContextHint là sidecar nhẹ do rule local tạo, không dùng LLM hoặc agent. Baseline gồm open quote, open list, dependent lead-in, reference to previous, citation/quote continuation và speaker continuity candidate.

Mỗi hint giữ target ref, related ref, hint type, exact evidence span, rule id và version. Hint chỉ đề nghị thêm context; không tạo semantic edge, không chứng minh speaker/condition và không được loại target.

Scheduler dựng AnalysisRegionManifest từ:

1. một hoặc nhiều primary target, là block hoặc slice của block dài;
2. bounded neighboring blocks;
3. block liên quan bởi structural relation đã xác nhận;
4. context do hint đề nghị trong giới hạn;
5. budget còn lại của case/run.

Region có thể chồng lấn, nhưng context span không được tính thành primary target lần nữa. Model phải trả processed target ids. Host gán AU cho block chứa start offset của evidence; slice chỉ giúp điều phối. Text chỉ được render khi gửi request. Manifest ghi unique chars, repeated chars, input estimate và lý do đưa từng span vào.

Mỗi request có cap đã khóa theo thí nghiệm: số target, source chars, input/output tokens, AU candidates và context additions. Không dùng whole-case provider read mặc định.

### Bước 4 — Trích xuất AU bằng model few-shot

Model trích AU là model ngôn ngữ zero-shot/few-shot, không phải classifier được huấn luyện và không phải agent tự điều phối tool. Model đọc AnalysisRegion và chỉ đánh giá target ids được chỉ định.

Khi gửi nguồn cho model, SentenceAtom vẫn là địa chỉ nguyên văn. Atom giao với target không đồng nghĩa toàn atom thuộc target: host đánh dấu chính xác phần giao raw TARGET bằng `TARGET_BODY`, phần ngoài hoặc khoảng trống bằng `CONTEXT_PADDING`. Primary proposition phải nằm trong body; padding chỉ bổ sung context. Host giữ nguyên văn bản/offset và đánh dấu phần đọc, không yêu cầu model tự đếm ký tự. Renderer có version trong cache/checkpoint; thay ranh giới raw TARGET phải thay nội dung prompt dù atom ID vẫn giữ nguyên.

Output fixed schema gồm processed target ids, AU candidates, no-AU target ids, context requests và warnings.

Mỗi AU candidate phải có:

- claim chuẩn hóa nhưng không thay evidence;
- exact evidence span và target owner;
- speaker/attribution candidate;
- conditions, exceptions và limits nếu có;
- kind, confidence, lý do và producer/config fingerprint.

Tập kind tạm giữ tương thích KOS: holding, standard of review, statutory hook, procedural rule, fact-pattern rule và foreign law. Foreign law khác trục với các kind còn lại và statutory interpretation từng xuất hiện ngoài enum; phải audit trước migration.

Model extraction, model sửa và retrieval agent về sau được chọn và định version độc lập. Có thể dùng chung ví dụ đã phân xử, nhưng không dùng output model để tự mở rộng gold. Không fine-tune, weak labeling hoặc self-training trong giai đoạn hiện tại.

### Bước 5 — Kiểm tra host, ContextObligation và sửa chọn lọc

Host kiểm tra target coverage, source hash, offset/quote, span thuộc source/region, duplicate kỹ thuật, schema và output caps. Đây không phải xác minh ngữ nghĩa.

Khi model hoặc validator phát hiện thiếu context cụ thể, host tạo ContextObligation gồm target, loại nghĩa vụ, hướng/span được yêu cầu, lý do, producer, run id và trạng thái pending, satisfied, unresolved hoặc budget exhausted. Host được mở thêm một vùng bounded theo policy. Obligation bắt buộc chưa giải quyết không được âm thầm chuyển thành AU accepted hoặc no-AU.

Model/agent sửa chỉ nhận candidate có trigger:

- attribution hoặc reporting voice mơ hồ;
- proposition có nguy cơ thiếu condition, exception hoặc limit;
- quote/citation hay AU evidence chạy qua nhiều block;
- output xung đột sidecar;
- duplicate/conflict giữa AU;
- target bị bỏ sót hoặc no-AU có rủi ro;
- obligation còn unresolved trong ngân sách sửa.

Agent sửa không đọc toàn case mặc định. Trạng thái AU là candidate, accepted, rejected, unresolved hoặc superseded.

Plan 12 dùng RepairTask có error_origin để phân biệt lỗi do host, model flag hoặc agent review chỉ ra. Agent có tools get_repair_task, open_span, expand_context, get_related_aus và submit_revision; host giữ quyền kiểm tra case/source, cap, checkpoint và commit revision. Agent nhận context ban đầu, có thể đọc thêm theo nhu cầu trong tối đa hai lượt model và một expansion; mỗi response chỉ một tool call, lượt cuối chỉ submit. Tool không gửi lại nguồn đã supplied. Response gọn được host dựng thành contract lưu đầy đủ, không suy nội dung ngữ nghĩa bị thiếu; decoder ràng buộc envelope/action/type/enum và host kiểm tra nguồn. Không repair nối tiếp revision trong cùng vòng. Sửa sai attribution khi evidence đã đủ không mặc định mở context.

Revision keep/replace/reject/unresolved giữ proposal gốc và exact evidence; replace có thể tạo nhiều AU trong cap. Host-valid revision vẫn semantic_review_pending. Mở thêm nguồn không tự satisfy ContextObligation, submit không tự accepted; cần review có binding. So R0 không repair, R1 request cố định và R2 agent cùng model/input để quyết định có giữ runtime tool hay không. Chi tiết trong 12_plan12_agent_repair_implementation.md; triển khai offline/mock không thay gate semantic hoặc cho phép mở corpus.

Sau smoke live đầu, nhiệm vụ chuyển thành validate-first trong cùng request: model đánh giá supported/uncertain/defect_found cho từng AU. Supported giữ nguyên; uncertain bảo toàn proposal và ghi bất định; chỉ defect_found có exact evidence mới được đề xuất replace/reject. Các lỗi báo từ vòng trước là giả thuyết cần đọc lại, không phải kết luận cho cả collection. Duplicate phải tham chiếu proposal khác được giữ và supported trong cùng batch, không tạo vòng loại cả nhóm. Host lưu assessment cùng revision, không suy rằng exact quote chứng minh defect đúng ngữ nghĩa. Không thêm lượt validate mặc định hoặc đổi trần token/model. Response action-only cũ chỉ phục vụ đọc lịch sử/kiểm thử compatibility, không được bypass runtime mới.

### Bước 6 — CoverageLedger và hoàn tất case

Mỗi primary target có ledger entry gồm run/case/source hash, parent block id, target id/span, state, request ids, AU ids, obligation ids, unique/rendered chars, retry count, repair count và stop reason.

State gồm pending, processed, no-AU, unresolved hoặc error.

Case chỉ hoàn tất khi:

- mọi content target có trạng thái cuối;
- processed target ids khớp manifest;
- obligation bắt buộc có trạng thái rõ ràng;
- lỗi cục bộ không bị ghi thành no-AU;
- request, token, overlap, retry và repair được báo đầy đủ.

CoverageLedger chứng minh workload đã được xử lý, không chứng minh model đã tìm đủ AU.

### Bước 7 — Ghi Issue metadata mở

Issue là thực thể semantic độc lập, không thuộc enum đóng. Preprocessing không ép mỗi AU/NN có Issue và không tự tạo canonical Issue từ term/entity/role.

1. Curator, model AU/NN hoặc terminology worker có thể tạo IssueProposal từ exact evidence.
2. Host chỉ chuẩn hóa kỹ thuật để lookup; lookup key không chứng minh tương đương semantic.
3. Exact match với preferred label hoặc alias accepted chỉ tạo canonical-link candidate.
4. Chưa có Issue phù hợp thì giữ nil hoặc unresolved; không tự canonicalize bằng clustering, embedding hoặc confidence.
5. Sau phân xử mới materialize IssueLink.
6. Một AU/NN có thể có zero, one hoặc multiple IssueLink.

IssueAlias là record có status, provenance và version. Parent/child, broader/narrower và related-Issue không được nhét vào alias. Pipeline chưa quyết định hierarchy, merge/split Issue hoặc cách Issue tham gia NN–AU matching.

### Bước 8 — Publish KB snapshot

Snapshot gồm source store; SourceBlock/SentenceAtom map; structural relations và sidecars; versioned region policy, CoverageLedger và unresolved obligations; AU store; Issue metadata.

Chỉ AU accepted được đưa vào AU view mặc định. Candidate/unresolved vẫn truy cập được qua audit view. Region text không được materialize lặp trong snapshot.

## 4. Pipeline query-time trong phạm vi preprocessing

Query cũng là một bản án:

1. khóa query source/hash;
2. phát hiện marker và citation cue;
3. tạo CiteSite có origin;
4. mở bounded source context;
5. trích NN với proposition, constraints và exact spans;
6. ghi IssueProposal/IssueLink nếu có.

Marker gồm FRAGMENT_SUPPRESSED, REFERENCE_SUPPRESSED, CITATION_SUPPRESSED và marker tương đương. Marker là tín hiệu mạnh nhưng không phải cách duy nhất tạo CiteSite. Fallback không marker có origin riêng và không được dùng citation chưa che hoặc gold.

Giai đoạn này dừng ở AU, Issue metadata, CiteSite và NN. Không tạo CandidatePair hoặc quan hệ support giữa NN và AU.

## 5. Hợp đồng dữ liệu tối thiểu

Các record canonical và run-time:

| Record | Trường bắt buộc chính |
|---|---|
| CaseSource | case id, source version/hash, text ref, char length, metadata |
| SpanRef | case id, source hash, start/end char |
| SourceBlock | block id, SpanRef, block type, ordinal, marker/heading candidate nếu có, parser version |
| SentenceAtom | atom id, block id, SpanRef, ordinal, segmenter version |
| AnalysisTargetSlice | target id, parent block id, SpanRef, slice ordinal, policy version |
| StructuralRelation | type, source/target/evidence refs, status, producer version |
| ContextHint | target/related refs, type, evidence, rule/version |
| AnalysisRegionManifest | targets, context refs/reasons, render order, char/token budget, policy version |
| ContextObligation | target, type, requested context, reason, status, producer/run |
| CoverageLedgerEntry | target state, requests, AU/obligation ids, chars, retry/repair, stop reason |
| AuthorityUnit | kind, claim, evidence, attribution, conditions/exceptions/limits, owner, status, provenance |
| Issue records | label/subject, evidence, status, version, provenance |
| CiteSite | marker/cue refs, context refs, origin |
| NoticeNeed | proposition, constraints, evidence, Issue links, status |

## 6. Tool interface

Các tool tối thiểu:

- get case;
- get source blocks;
- get sentence atoms;
- open span;
- expand context;
- get annotations;
- get structural relations;
- build analysis region;
- get context obligations;
- get coverage;
- get/list AU;
- get Issue;
- get CiteSite;
- get NN.

Mỗi response mang case id, source hash, exact spans, producer/version và status. Tool mở source không phụ thuộc annotation; annotation thiếu hoặc lỗi không làm source mất truy cập.

## 7. Cache, retry, resume và invalidation

Cache fingerprint gồm source hash, target/context SpanRefs, task, producer/model, prompt/schema/worker/region-policy versions và generation settings.

Quy tắc:

- lưu atomically từng worker batch và request;
- resume không gọi lại cache entry hợp lệ;
- retry lỗi tạm thời theo cap; không retry semantic disagreement tự động;
- structured-output repair có cap riêng;
- lỗi một target không rollback target khác;
- source đổi invalidates dependency closure của source;
- worker đổi chỉ invalidates artifact phụ thuộc worker;
- region policy đổi invalidates region manifest và output model phụ thuộc;
- Issue registry đổi invalidates resolution phụ thuộc version;
- không ghi complete nếu dừng do budget hoặc provider failure.

## 8. Ánh xạ bằng chứng Lynx và KOS

Thiết kế dùng từ Lynx các nguyên tắc document/part/annotation/provenance, NLP service tách rời, NER/reference/terminology là feature và workflow có cache/resume. P2 không tuyên bố Lynx đã chứng minh SourceBlock hoặc AU extraction cho COLIEE; block policy, hint, region và model AU phải được đo riêng.

KOS cung cấp tập AU kind ban đầu, marker như một nguồn CiteSite/NN và ví dụ Issue mở. Artifact KOS hoặc agent review không phải gold và không chứng minh live extractor.

## 9. Các quyết định dành cho giai đoạn retrieval sau

Checkpoint Kế hoạch 11 ngày 2026-10-11: ownership của AU được kiểm tra bằng primary proposition có quote nằm trong raw TARGET, không dùng atom TARGET được thêm làm evidence phụ để hợp thức hóa claim chỉ có trong CONTEXT. Review sidecar khóa hash của run/proposal, lưu witness riêng cho claim/kind/speaker/attribution và điều kiện. Host kiểm tra nguồn/quote/offset; verdict ngữ nghĩa là đánh giá agent, không phải gold hay bằng chứng entailment tự động. Thiếu hoặc bất đồng review giữ unresolved; lỗi đã xác định bị rejected. Contract và CLI nằm trong `pipeline_v1/au_candidate_store`.

Đặc tả này không quyết định:

- cách lập plan cho retrieval agent;
- retrieval view nào được sinh từ NN;
- cách ghép NN với AU;
- Issue/alias/hierarchy có làm candidate signal hay không;
- candidate cutoff, reranker hoặc final case selection.

Các quyết định đó phải được đánh giá riêng. Không sửa ngược preprocessing để ngầm biến Issue thành hard gate.
