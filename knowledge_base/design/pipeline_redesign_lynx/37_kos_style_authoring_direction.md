# Chuyển sang agent chọn nguồn và soạn AU theo legal point

Ngày chốt hướng: 2026-10-21; bổ sung ngày2026-10-24 theo [39](39_kos_authoring_improved.md). K0 v1 đã thực thi nhưng0AU; bản cải tiến mới ở thiết kế, chưa thay runtime/deploy/gọi inference trong lần cập nhật này. Không đổi reranker, candidate generation hay cách nối NN–AU.

## 1. Quyết định chính

Chọn kiến trúc **source → agent đọc/chọn → soạn AU → host materialize KB**. Không tiếp tục tối ưu một hệ “mỗi block là một TARGET bắt buộc, model trả tối đa ba AU rồi agent sửa”. Đổi model hoặc thêm NER không còn là điều kiện tiên quyết cho chuyển hướng này.

AU là một điểm pháp lý đủ nghĩa để viện dẫn, có thể gộp rule với rationale, application hoặc exception trực tiếp xác định phạm vi của rule đó. Các quyền, nghĩa vụ và phép kiểm tra độc lập vẫn tách riêng. SentenceAtom, SourceBlock và vùng đọc là địa chỉ/đơn vị vận chuyển, không quy định ranh giới hay số lượng AU.

Agent quyết định nội dung đáng viện dẫn và cần đọc thêm gì. Host quản lý nguồn, tool, ngân sách, lưu tiến độ và provenance; không tự quyết một đoạn là/no-AU bằng marker hoặc điểm số heuristic.

## 2. Học gì từ KOS, không sao chép gì

Bằng chứng trực tiếp trong bản KOS local:

- `G:/Legal-AI/kos_sample/SCHEMA.md`: AU có Claim, Evidence span, Why notice-worthy, Limits; Issue và case links tách khỏi substance.
- `_meta/extract_strategy.md`: ghi nhận Cursor Agent model=auto, rule substrate, validation và repair; tài liệu tự ghi v1 đã superseded bởi v2 ở kho khác. Nó không chứng minh model cụ thể, đọc hết án, semantic correctness hay throughput.
- AU no-danger của 011904 cho ví dụ gộp rule–ví dụ–exception hữu ích.
- `KOS_PREDICTED_WORKFLOW.md` là tái dựng có giới hạn, không phải trace runtime đã được xác minh.

Học semantic authoring và context đọc linh hoạt. Không sao chép gold-family selection, gold_noticed/matched links, marker-only selection, tên citation bị che lấy từ KOS, hoặc nhãn verified như chứng nhận ngữ nghĩa. Chưa có căn cứ khẳng định kiến trúc mới giống hệt implementation nội bộ KOS.

Bổ sung39: chuyển hướng dẫn authoring thành ví dụ JSON đầy đủ có rule/exception, mẫu âm và bất định; không nhập quota min5AU/case ghi trong tài liệu KOS lịch sử. Giữ Why notice-worthy làm tiêu chí lựa chọn, không tăng output bắt buộc. No-AU là nhận định cục bộ có lý do/provenance, không có nghĩa đã chứng minh không bỏ sót. Chỉ validate phạm vi công việc0AU một lượt/case khi control đã đạt và còn budget; không verifier toàn corpus, không ép tạo AU. Đo omission cả scope có AU, scope không AU và báo riêng unread.

## 3. Luồng được chọn

```text
Source bất biến + bản đồ địa chỉ local
  → workspace theo case + các vùng nguồn có thể mở
  → agent đọc/chọn và soạn AU trong cùng phiên làm việc
      ↔ open_region / search_source / get_drafts
  → host kiểm cấu trúc và nguồn, lưu AU nháp hoặc bất định
  → publish snapshot có trạng thái chất lượng và phạm vi đã đọc
```

### A. Chuẩn bị local, không token LLM

Giữ source/hash/offset, SourceBlock/SentenceAtom, paragraph/heading quan sát được, next/previous và marker spans. Thiếu heading giữ unknown; mọi ký tự nguồn vẫn mở được. Không tạo heading ngữ nghĩa giả, global LegalUnit partition hay semantic graph.

NER, rhetorical-role model, terminology và cue metadata **mặc định tắt**. Existing sidecar không bị xóa nhưng không gửi mặc định; chỉ thử sau khi có nhu cầu và ablation riêng.

### B. Workspace theo case

Một CaseWork chứa source version, navigation, các ReadScope, draft AU và ngân sách. ReadScope có thể gồm nhiều block liên quan; nó là vùng agent đã/định đọc, không phải ranh giới của AU.

Không có planner LLM chạy trước để lập lịch cho mọi block. Request đầu vừa đọc nguồn thật vừa soạn nội dung; những lần tool navigation cần thiết vẫn được tính là lượt model/chi phí. Có thể mở rộng liền kề hoặc tìm trong raw source cùng case khi thiếu premise, reporting voice, exception hoặc court response.

Host không dùng KOS/AU tham khảo để xếp nguồn. Không có cam kết agent tìm đủ AU mà không đọc hết văn bản: nếu dừng theo ngân sách, vùng chưa đọc giữ not_assessed, case là partial.

### C. Agent soạn theo legal point

Agent đọc toàn bộ nội dung đã mở trước khi chốt các điểm ở vùng đó; không lấy ba câu đầu hay cố lấp quota AU. Các ràng buộc nội dung:

- xác định proposition có giá trị viện dẫn, chủ thể có quyền/nghĩa vụ và người phát biểu;
- gom rationale/exception cần thiết vào cùng point; không ghép mọi nội dung cùng topic;
- giữ reported decision, party submission và current-court adoption khác nhau;
- giữ phạm vi fact-specific, modal và qualification; không biến narrative thành điều kiện;
- judicial application và rationale có thể là AU; fact thuần, tên điều luật và adoption không có substance thường là context;
- bảo toàn AU đã đúng nếu chưa có lý do nguồn để sửa; không viết lại collection sau mỗi tool call.

Đây là trách nhiệm agent authoring, không phải kết luận host suy từ feature. Không thêm một phase rhetorical-role/classification bắt buộc trước authoring.

### D. Context và ownership mới

AU luôn thuộc đúng **case/source version**, có một hoặc nhiều evidence spans đã mở; được phép chạy qua nhiều block/vùng đọc trong cùng case. Không yêu cầu claim phải là nguyên văn, không yêu cầu model tự đếm offset.

Không còn luật “phải có proposition trong TARGET gốc, context chỉ được hỗ trợ”. Khi agent phát hiện một legal point ở vùng trước đây gọi là context, agent được tạo AU cho vùng đó với evidence/anchor thật, owner là chính case đó. Không gắn một atom TARGET không liên quan để hợp thức hóa claim.

Cross-case quote vẫn được lưu dưới case đang cung cấp văn bản và phải giữ reported-authority attribution; không tự tạo AU sở hữu án được trích khi chưa có source của án đó. Không khôi phục identity từ citation chưa che/gold.

### E. Host và KB

Wire tối thiểu của một AU nháp giữ claim, kind nullable, evidence IDs và limits nullable. Host suy SpanRef, hash, case owner và producer từ catalog đã mở. Why notice-worthy là tiêu chí authoring; chỉ lưu ghi chú ngắn khi hữu ích, không ép mỗi AU sinh thêm một đoạn giải thích. Không bắt model trả speaker/condition checklist riêng nếu claim/limits đã thể hiện đủ.

Ngưỡng claim500/limits250/question200 chỉ cảnh báo, không cắt, loại hoặc repair vì dài. Giữ trần tài nguyên mỗi request và kiểm incomplete/truncation; hết output cap không được đánh dấu đã soạn đủ legal points. Số AU tối đa trong một response chỉ là transport cap, không quota theo block/case; còn nội dung thì checkpoint rồi tiếp tục trong budget.

Schema/source hợp lệ → grounded_draft, **không tự accepted về ngữ nghĩa**. draft, reviewed_supported, needs_revision, unresolved và rejected tách nhau. Chỉ reviewed_supported vào view ready-for-citation; snapshot nháp riêng dùng cho thí nghiệm có nhãn rõ. Chưa có bộ review tự động được chứng minh đủ tốt thì không tuyên bố KB sẵn dùng toàn corpus; không thêm một verifier LLM toàn corpus mặc định.

## 4. Tool và trạng thái đủ dùng

| Tool | Trách nhiệm |
|---|---|
| get_case | Metadata nguồn, navigation, tiến độ và budget; không trả toàn source mặc định |
| open_region | Mở exact SpanRefs/block ranges, gộp overlap; trả IDs chỉ cho text thực sự gửi |
| search_source | Tìm lexical trong raw source cùng case, kết quả là navigation, phải mở trước khi cite; không dùng AU/KOS/gold |
| get_drafts | Xem AU đã commit, tránh đọc/soạn lại; lấy full evidence khi cần |
| submit_aus | Ghi add/update với evidence thuộc catalog, giữ revision chain |
| finish_case | Kết thúc complete/partial/unresolved cùng phạm vi và stop reason, không chứng nhận semantic recall |

Không tạo thêm global planner, nhiều hàng đợi heuristic hoặc tool graph trong pilot đầu. Scheduler chỉ chạy độc lập giữa các case; lượt trong một case theo phụ thuộc. Concurrency và bulk hiện có chỉ tái dùng sau khi phù hợp contract mới, không tự redeploy.

ReadLedger tách available, delivered, assessed và unresolved. source_delivery không đồng nghĩa assessed; agent nói no-AU chỉ áp dụng đúng vùng nó đã xem xét, không lan sang phần chưa đọc. Full-source local coverage khác model-reading coverage và khác semantic coverage.

Tool có thể tránh gửi source trùng trong cùng request, nhưng không giả định model nhớ nguồn của request độc lập. Mọi text/tool transcript thực sự gửi lại đều tính token; cache receipt chỉ tiết kiệm rerun, không phải fresh-run speedup.

## 5. Thử theo thứ tự, không mở toàn corpus

### K0 — Cô lập cách authoring trên nguồn đã có

- Giữ union exact source mà A stage1 đã nhận: 16 vùng của 3 case, không đọc KOS vào model. Manifest union lấy từ catalog/payload request đã gửi, không lấy toàn bộ context_refs sẵn có trong workload. Gom thành nhiệm vụ theo case; bounded request vẫn phải giữ thứ tự/gap rõ ràng.
- Cho agent soạn AU theo point trong union đó; không ép gắn AU vào một TARGET cũ, không thêm cue, NER hoặc đổi model. Qwen/Qwen3.5-9B hiện tại là đối chứng đầu, không khẳng định đủ năng lực.
- Agent có thể soạn nhiều AU qua các response, commit để tiếp tục chứ không tự sinh lại cả collection. Không mở source ngoài union trong phép thử equal-exposure; thiếu nguồn giữ unresolved.
- Cùng trần input6000/output800 mỗi request để không lẫn hiệu quả với tăng output cap. Preflight kiểm payload thực tế; tối đa12 lượt model toàn run và tổng reservation/usage không quá30000 token, gồm continuation/retry/probe. Đây là ngân sách nghiên cứu dừng, không mục tiêu chi phí hoặc bằng chứng rẻ.
- Baseline A stage1 19672 token, v2 stage1 19366 token; tính cả mọi lượt planner/tool-continuation của K0. Shortening A đã thất bại3291 token là lịch sử chi phí, không bỏ khỏi báo cáo nhưng không ép nhánh mới trả lại khoản đã chi.
- Source [15] có sẵn trong context_refs của workload nhưng chưa gửi: A stage1 chỉ có INPUT.TARGET, catalog.context_refs rỗng, không có request stage2. Vì vậy cả [15]/[16] đều ngoài union thực sự đã đọc của K0; K0 không được lấy lời giải reviewer hoặc coi context có sẵn là evidence đã gửi. K1 mới được mở [15] và [16] qua tool. Đo không chỉ AU match KOS mà cả hai omission đã thấy từ source.
- Bounded-workload complete chỉ nói mọi scope trong manifest K0 đã có trạng thái; cả case vẫn partial vì còn source ngoài union chưa được đánh giá. Không dùng case partial dự kiến để báo lỗi giao thức hoặc tự mở thêm nguồn.

### K1 — Đọc chủ động trên toàn nguồn năm án calibration

Chỉ sau K0 cho thấy authoring có lợi và không tăng lỗi nghiêm trọng. Source inventory là toàn bộ năm án, không phải tập reference-guided16. Agent được mở/search nguồn cùng case, không có shortlist KOS/gold; không bắt LLM đọc mọi block. Khóa ngân sách từ preflight độ dài và số lượt đo ở K0 trước chạy, không tự mở remote hoặc toàn corpus.

Đo phần chưa được đọc, legal points bỏ sót và đường quality–cost theo budget. Pilot đọc chọn lọc cũ H bỏ nhiều positive; P tăng token do planner. Do đó chỉ có ít request hoặc mở ít source không đủ để chọn K1; phần chưa đọc không trở thành no-AU.

### K2 — Cải tiến từng thành phần sau baseline mới

Sau khi có baseline KOS-style: thử reuse context, batch/transport và một model authoring khác; worker NER/cue/rhetorical role chỉ là ablation tùy chọn. Không đưa các thành phần này vào mặc định để chữa lỗi chưa phân loại. Expansion, consolidate/review hoặc sửa chỉ chạy khi có nhu cầu; không buộc mọi AU đi qua nhiều model phase.

## 6. Cổng chọn/bỏ

- Source/offset/hash, lỗi cục bộ, cache/resume và invalidation đúng; token/retry/failure được báo đủ.
- Không còn lỗi applicant→decision-maker, narrative→condition, hoặc reported opinion→unqualified current holding trong các ca đã phân xử.
- Không bỏ operative exception [10] và finding noncompliance [21] chỉ để giữ policy slogan; không coi “tôi đã đọc hết” là đủ chứng minh omission thấp.
- Đánh giá coherence/fragmentation của từng legal point, không buộc số AU bằng KOS. Kind uncertainty không ép sửa rule đúng.
- K0 so cùng source exposure; K1 mở nguồn khác thì báo riêng gain do thêm evidence và gain do authoring/selection. Không đổi tất cả rồi quy lợi ích cho agent.
- Khi chất lượng tương đương mới so token. Nếu K0 chất lượng tốt nhưng tốn hơn, báo tradeoff; nếu vẫn không có ích thì sửa authoring/model, không thêm planner/enrichment để bảo vệ thiết kế.
- Case-held-out sau calibration trước khi kết luận toàn corpus; KOS/agent review không phải gold. Không có cam kết30% savings.

## 7. Migration và giới hạn

Giữ source/atom stores, raw index, receipt/checkpoint và transport đã dùng được. Ngừng dùng block-completion, fixed TARGET ownership và length repair làm điều kiện mặc định. AU lịch sử giữ producer/reading policy gốc; không tự relabel thành KOS-style hay reviewed_supported. Link Issue mở được giữ, không canonicalize/alias tự động và không chốt cách nối NN–AU.

Checkpoint cập nhật2026-10-24: adapter/contract/runner K0 đã chạy live5request hợp wire nhưng0AU. CPU grammar replay dương PASS, endpoint synthetic có grammar vẫn0AU; chưa qua cổng chất lượng và chưa mởK1. Bước tiếp đã chốt trong39: ví dụ JSON đầy đủ → controls dương/âm/bất định → authoring mới cùng nguồn → đo validate0AU → held-out. Không sửa checkpoint hoặc tự relabel kết quả cũ; không thêm NER. [Triển khai/lịch sử38](38_k0_implementation.md), [thiết kế cải tiến39](39_kos_authoring_improved.md).
