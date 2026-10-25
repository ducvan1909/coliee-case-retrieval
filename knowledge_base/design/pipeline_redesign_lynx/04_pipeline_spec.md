# Đặc tả preprocessing và KB — agent soạn AU theo legal point

Phiên bản thiết kế: KOS-style authoring, bổ sung ngày 2026-10-24. Thay P2 làm hướng thiết kế chính. K0 v1 đã chạy nhưng chưa đạt chất lượng; cải tiến dưới đây mới ở thiết kế, chưa sửa runtime. [Hướng authoring](37_kos_style_authoring_direction.md), [cải tiến theo KOS](39_kos_authoring_improved.md). Bản P2 nguyên vẹn trong history_before_kos_direction_20261021/.

## 1. Mục tiêu và ranh giới

Xây AU có giá trị viện dẫn: proposition tự đủ nghĩa, đúng chủ thể/người phát biểu, giữ điều kiện, rationale và ngoại lệ cần thiết. Bảo toàn raw source và evidence để agent đọc lại khi cần. Chất lượng authoring là mục tiêu chính; schema/offset chỉ là kiểm tra nguồn và giao thức.

Giữ Issue như metadata mở, CiteSite và NN cho query preprocessing. Chưa chọn cách nối NN–AU, Issue gate, alias/hierarchy matching, retrieval view, candidate pool, reranker hoặc tập án cuối.

Các quyết định:

- Agent chọn nội dung đáng viện dẫn và soạn AU theo case; không bắt mỗi block thành một extraction TARGET.
- SourceBlock/SentenceAtom là địa chỉ, không phải semantic partition hoặc ranh giới AU.
- AU có thể dùng nhiều evidence spans qua nhiều block/vùng đọc của cùng case.
- Không giới hạn quyền tạo AU vào TARGET gốc; nguồn trước gọi là context được dùng nếu đã mở và được gắn evidence/owner đúng.
- Không planner LLM toàn cục, NER/cue/rhetorical-role enrichment hoặc verifier toàn corpus mặc định.
- Không gán no-AU cho nguồn chưa đọc; dừng theo budget giữ partial/not_assessed.
- Độ dài field chỉ cảnh báo; không retry/repair vì vượt ngưỡng.
- Không dùng gold, KOS Claim/Issue/reference outputs hoặc citation chưa che để hướng dẫn authoring/selection.

```text
CaseSource bất biến
  → bản đồ SourceBlock/SentenceAtom local
  → CaseWork và các ReadScope có thể mở
  → agent đọc/chọn + soạn AU ↔ tool đọc nguồn
  → host kiểm nguồn/contract + commit draft
  → ghi assessment; validate có giới hạn nếu phạm vi công việc kết thúc với0AU
  → KB snapshot có chất lượng và reading coverage rõ ràng
```

## 2. Bước xử lý

### Bước 0 — Source và địa chỉ local

Giữ text nguyên bản, source version/hash và half-open offsets. Parser local tạo block có thứ tự, SentenceAtom, paragraph/heading quan sát được, quote/list/citation/marker spans và adjacency. Heading thiếu giữ unknown, không sinh giả; nguồn không marker vẫn truy cập được.

Không dựng LegalUnit partition, global semantic graph hoặc bắt mọi câu có kind. Phần này 0 token LLM; vẫn phải báo CPU/storage/update cost.

### Bước 1 — Tạo CaseWork

Host tạo navigation theo nguồn, ReadLedger, catalog evidence và draft store. Không gửi toàn source cho một planner riêng. Initial scope là gói nguồn bounded theo policy thí nghiệm; navigation/search chỉ là công cụ mở nguồn, không phải evidence hoặc no-AU classifier.

CaseWork là đơn vị công việc của agent, không có nghĩa toàn case phải vừa một prompt. ReadScope có thể gồm một hoặc nhiều block, giữ thứ tự và gaps rõ ràng. Mọi source vẫn mở được qua tool, không shortlist theo KOS.

### Bước 2 — Agent đọc và soạn

Request đọc nội dung thật và đề xuất AU, không thêm bước phân loại rhetorical role hoặc planning bắt buộc. Agent có thể mở thêm nguồn khi cần làm rõ rule, speaker, condition, exception hoặc phản hồi tòa. Navigation/tool-only turns vẫn tính chi phí.

Mỗi AU diễn đạt một legal point có thể viện dẫn. Gộp rule với rationale/application/exception trực tiếp xác định ý nghĩa, nhưng tách các quyền, nghĩa vụ và phép kiểm tra độc lập. Không mặc định mỗi câu một AU, không lấp quota bằng policy slogan hoặc statute-location metadata.

Giữ rõ current court, reported authority và party submission; giữ modal, fact-specific scope, người có quyền/nghĩa vụ. Court adoption không tự đủ nghĩa nếu chưa nêu substance của approach được tiếp nhận. Judicial rationale/application có thể là AU, documentary facts thuần thường là context.

Không fine-tune, self-training hay tự sinh gold trong giai đoạn này. Agent model đầu là Qwen/Qwen3.5-9B hiện có để thử riêng đổi workflow; không tự đổi model hoặc deploy. Model khác chỉ là thí nghiệm sau, không phải điều kiện để bắt đầu chuyển kiến trúc.

Học KOS ở cách soạn Claim–Evidence–Limits và tiêu chí đáng viện dẫn, không học quota min5AU/case. Prompt kế tiếp có ví dụ JSON đầy đủ bằng nguồn tổng hợp khác tập thử: có rule/exception, không có legal point độc lập và thiếu context. Why notice-worthy không trở thành essay bắt buộc. Positive/negative/multi-point controls phải đạt trước khi mở rộng authoring trên án thật; hiện K0 chưa qua positive control. Lộ trình và hợp đồng gọn: [39, mục4–5](39_kos_authoring_improved.md#4-dạy-contract-thay-vì-ép-số-lượng).

### Bước 3 — Mở thêm context và ownership

Agent được mở/search raw source cùng case. Quote/paragraph reference thuộc án được dẫn không tự resolve thành paragraph local. Preview/search hit phải được mở nguyên văn trước khi làm evidence.

AU owner là case/source version, không phải block chứa start offset hoặc TARGET cũ. Evidence IDs chỉ tham chiếu những span đầy đủ đã thực sự gửi; host dựng exact SpanRef/hash. Model không tự tính offset. Claim được paraphrase, không bắt literal quote-match claim.

Một legal point phát hiện ở context cũ được tạo AU riêng với anchor/evidence đúng; không thêm một TARGET ID không liên quan để hợp thức hóa ownership. Quote của án khác vẫn cần reported attribution; không tự tạo owner là án chưa có source.

Nếu thiếu premise/exception hoặc hết budget, giữ unresolved. Mở nguồn không tự chứng minh đã giải quyết dependency.

### Bước 4 — Host materialize draft

Wire AU tối thiểu: claim, kind nullable, evidence_ids và limits nullable. Host bổ sung id, source/case, spans, producer/model/prompt/schema và revision chain. Why notice-worthy là tiêu chí authoring; note ngắn tùy chọn, không bắt thêm rationale paragraph cho mỗi AU.

Kind giữ tương thích KOS: holding, standard_of_review, statutory_hook, procedural_rule, fact_pattern_rule, foreign_law; uncertain giữ null, không ép kind để sửa claim đúng. Các trục phân loại chưa tách lại trong đợt chuyển hướng.

Host kiểm schema/type/enum, evidence IDs, source binding, quote/offset, technical duplicate và output truncation. Host không tự chứng nhận entailment hoặc phát hiện đầy đủ omission.

Claim500/limits250/question200 là mức khuyến nghị có warning path/actual_length/threshold. Không cắt, reject hoặc gọi model sửa vì dài. Trần input/output token vẫn là giới hạn tài nguyên. Output bị cắt hoặc còn legal points chưa soạn thì checkpoint/partial, không coi đã xong.

Transport có thể giới hạn số AU mỗi response, nhưng không có quota ba AU mỗi block hoặc một AU mỗi case. Continuation không tự viết lại tất cả draft đã commit; chỉ sửa khi có lý do gắn nguồn.

### Bước 5 — ReadLedger và kết thúc

Tách source available, delivered, assessed, no-AU-assessed và unresolved. Địa chỉ local phủ toàn source khác model đã đọc, và cả hai khác semantic coverage. Không bắt mọi block gọi LLM; phần chưa đọc giữ not_assessed.

Agent finish có stop reason và residual scopes. Case còn nguồn chưa assessed hoặc obligation chưa giải quyết thì partial; trạng thái terminal của job không đổi case thành complete. Ngay cả full-reading complete cũng không chứng minh tìm đủ AU.

Tách work_scope_complete khỏi case_source_assessment_complete: pilot chỉ cho phép một source union bounded có thể hoàn tất workload nhưng case vẫn partial. Đây không phải lỗi protocol hoặc lý do tự mở scope vượt ngân sách.

ReadAssessment tách `has_au`, `no_au_candidate`, `uncertain`; chúng không là chứng nhận đủ AU. Theo [contract v2/41](41_read_assessment_contract_v2.md), model chỉ trả `aus`, `empty_reason`, `next_action`; bỏ list `assessed_scope_ids` khỏi wire model. Host giữ IDs/source/provenance và suy assessment conservative từ catalog/reason/action, giữ nguyên AU wire. Với0AU có kết luận cần reason ngắn; thiếu thông tin không được chuyển thành no-AU, `needs_context` không thể certify complete dù có AU. Không thêm model classification cho mọi block. Enum/lý do39 vẫn giữ; ví dụ và grammar phải chạy lại controls sau đổi wire.

CaseWork0AU trong **phạm vi được phép** có cờ cần kiểm tra, không phải extraction thành công vì schema PASS. Sau khi control đã đạt, tối đa một validate/case trong cap chung; được xác nhận rỗng, bổ sung có evidence hoặc giữ bất định. Không vòng lặp ép AU, không mở ngoài union K0, không xóa draft khác. Resume không cấp lại lượt validate. Hết budget/nguồn không vừa request thì lưu chưa validate, không chứng nhận âm. Không thêm verifier toàn corpus; [39, mục6](39_kos_authoring_improved.md#6-validate-có-điều-kiện-không-ép-sửa) quy định nhánh này.

### Bước 6 — Publish KB

Trạng thái AU: grounded_draft, reviewed_supported, needs_revision, unresolved, rejected, superseded. Schema/source hợp lệ chỉ tạo grounded_draft. Snapshot thí nghiệm có thể chứa draft nhưng không được đặt nhãn ready-for-citation.

Chỉ reviewed_supported vào view sẵn dùng làm authority; lưu review provenance rõ agent_reviewed, không human gold. Chưa có review tự động đủ tin cậy thì chưa có căn cứ công bố toàn corpus sẵn dùng. Không thêm verifier LLM toàn corpus mặc định; đo kiểm theo kế hoạch thực nghiệm trước.

Snapshot giữ nguồn/bản đồ, AU, Issue metadata và reading/quality status. Không materialize source text lặp trong AU, region hoặc snapshot.

## 3. Tool interface tối thiểu

| Tool | Input/đầu ra và trách nhiệm |
|---|---|
| get_case | Case/source version → navigation, draft summary, reading state, budget |
| open_region | Block/SpanRefs → nguyên văn + evidence IDs + source hash; gộp overlap, có continuation |
| search_source | Lexical query cùng case → navigation hits; phải open trước khi cite |
| get_drafts | AU ids/case → draft và revision, full evidence theo nhu cầu |
| submit_aus | Add/update AU cùng evidence IDs → host-valid draft hoặc lỗi cục bộ |
| finish_case | Stop reason/residual scopes → complete/partial/unresolved được host kiểm |

Tool mở nguồn không phụ thuộc NER, heading hoặc AU có sẵn. Search raw source không dùng KOS/gold/Issue accepted để làm câu trả lời. Không thêm graph tool trong pilot đầu.

## 4. Dữ liệu cần lưu

| Record | Trường chính |
|---|---|
| CaseSource/SpanRef | Case, source version/hash, raw text ref, offsets |
| SourceBlock/SentenceAtom | Địa chỉ, thứ tự, type hình thức, parser version |
| CaseWork | Case/source, policy, budget, source catalog, draft ids, run state |
| ReadScope/ReadLedger | Source spans, available/delivered/assessed state, request IDs, residual/stop reason |
| ReadAssessment | Scope/request refs do host suy, result/reason ngắn, self-report/agent-check provenance; không là nhãn gold |
| AuthorityUnit | Claim, kind, evidence, limits, owner case/source, quality status, revision/provenance |
| Issue records | Open label, alias/proposal/link, status/evidence/version |
| CiteSite/NoticeNeed | Marker/non-marker origin, proposition/constraints/evidence, optional Issue links |

Annotation sidecar và observed relations đã có vẫn giữ dưới version gốc nhưng mặc định không gửi. AnalysisTargetSlice/AnalysisRegion/ContextObligation/CoverageLedger P2 là dữ liệu lịch sử; không ép schema authoring mới phải dùng primary-target ownership hay block completion của chúng.

## 5. Issue và query preprocessing

Issue vẫn mở, nullable hoặc nhiều nhãn. Không ép mọi AU có Issue; term/entity không tự tạo accepted Issue. Alias cần trạng thái/provenance, không dùng broader/narrower thay alias. Chưa quyết định taxonomy, merge/split hoặc cách Issue tham gia matching.

Query cũng là case source: marker FRAGMENT/REFERENCE/CITATION_SUPPRESSED là tín hiệu mạnh để neo CiteSite, không phải nguồn duy nhất. NN biểu đạt nhu cầu viện dẫn từ nguồn và giữ constraints; không suy authority identity từ marker hoặc dùng citation không che. Query-time planning/retrieval/matching để giai đoạn sau.

## 6. Chi phí, cache và phục hồi

Fingerprint gồm source/map, read scopes/catalog, navigation/render, policy, model/prompt/schema và generation settings. Lưu intent trước dispatch, receipt trước assessment/commit; resume truy hồi job cũ, không gọi lại generation hợp lệ. Outcome/usage chưa biết phải được giải quyết trước redispatch.

Phiên bản ví dụ JSON, assessment và validation policy tham gia fingerprint. Validate có parent receipt và draft revision; review cũ hết hiệu lực khi source/draft phụ thuộc đổi nhưng không tự chạy lại authoring. Tính cả ví dụ few-shot, nguồn đọc lại và validate thất bại vào chi phí; không mặc định prefix cache miễn token.

Tách transient transport retry có cap với semantic revision. Không retry vì model disagreement, kind uncertain hoặc field dài. Lỗi cục bộ không xóa AU khác. Source đổi invalidates dependency closure; Issue resolution đổi không bắt đọc lại AU không phụ thuộc.

Tính navigation, planning/tool turns, toàn payload, context gửi lặp, output/reasoning, retry và lỗi. Cache transcript không đồng nghĩa source biến mất khỏi input token. Không dùng resume như fresh speedup, không quy USD/request giả định.

## 7. Migration và bằng chứng

Tái dùng source/atom stores, raw index, receipt và checkpoint; adapter tool mới không viết lại source. Artifact P2/A/soft import giữ producer, reading policy và review status cũ; không đổi nhãn thành authoring mới hoặc accepted. Ngừng length repair đã chốt ở kế hoạch36.

Lynx hỗ trợ ý tưởng document/part/annotation/provenance và service tách rời; không chứng minh AU correctness hoặc savings. KOS sample cung cấp semantic packaging, schema và chiến lược agent được ghi nhận, không cung cấp đầy đủ executable trace/model/token hoặc gold-blind corpus claim. Xem kế hoạch37 và các nguồn local được dẫn ở đó.

Thử K0 equal-exposure trước, K1 đọc chủ động sau; chưa chứng minh lợi ích. Canonical design:03/04/05/09/37 và bổ sung39; các checkpoint P2 cũ được giữ làm lịch sử.


### Checkpoint triển khai K0 — 2026-10-23

K0 case-level authoring đã triển khai riêng tại `knowledge_base/pipeline_v1/k0_authoring/`, không thay runtime lịch sử. Live5request hoàn tất giao thức nhưng0AU; diagnostic riêng chưa qua positive control. Không lấy token thấp làm tiết kiệm. Chỉ dùng16scope/3case thực sự đã gửi trong A; K1 chưa triển khai. Chi tiết lịch sử: [38](38_k0_implementation.md); thiết kế cải tiến chưa code: [39](39_kos_authoring_improved.md).
