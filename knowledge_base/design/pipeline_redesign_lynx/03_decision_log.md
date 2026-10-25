# Quyết định hiện hành — KOS-style agent authoring, 2026-10-21

Các quyết định dưới đây thay thế phần P2 lịch sử ở cuối file. [Đặc tả04](04_pipeline_spec.md), [thử nghiệm05](05_experiment_plan.md), [xâyKB09](09_kb_build_plan.md), [phân xử37](37_kos_style_authoring_direction.md) và [bổ sung39](39_kos_authoring_improved.md) là bộ hiện hành. Cập nhật2026-10-24 chỉ sửa thiết kế; K0 v1 đã chạy0AU, không sửa runtime/artifact trong lần này.

| Thành phần | Quyết định | Lý do và giới hạn |
|---|---|---|
| Agent authoring theo case/legal point | Chọn làm hướng chính | Học semantic packaging KOS, không khẳng định cùng implementation hoặc tốt hơn đã đo |
| SourceBlock/atom/raw index | Tái dùng làm địa chỉ | Không dựng semantic partition hoặc ép mọi block thành extraction TARGET |
| Fixed TARGET ownership | Bỏ khỏi mặc định mới | AU thuộc case/source và các evidence spans đã mở, có thể qua nhiều block/context cũ |
| Rule–rationale–exception | Gom khi cùng legal point | Tách rights/duties/tests độc lập; không sao câu hoặc gộp chỉ vì cùng topic |
| Quota KOS min5AU/case | Không tiếp nhận | Tài liệu lịch sử có quota nhưng không chứng minh recall; không ép AU rỗng thành dương |
| Ví dụ JSON KOS-style | Chọn thử trước khi sửa kiến trúc khác | Nguồn tổng hợp độc lập, controls dương/âm/bất định/multi-point trước source thật; chưa chứng minh lợi ích |
| No-AU và uncertainty | Lưu assessment gọn, không classifier mọi block | Thêm lý do rỗng theo39; self-report âm không là semantic truth và không lan sang unread |
| Validate kết quả rỗng | Tối đa1lượt/case trong budget, chỉ sau control đạt | Trigger là phạm vi CaseWork0AU, không phải toànsource; được giữ rỗng, không retry tới khi có AU |
| Planner LLM trước mọi extraction | Không dùng mặc định | PilotP từng tăng token; firstrequest đọc/soạn, navigationturn vẫn tính chi phí |
| NER/cue/role enrichment | Tắt mặc định | Không phải điều kiện để chuyển hướng; ablation sau baseline mới |
| Block coverage bắt mọi block gọi LLM | Thay bằng ReadLedger | Source inventory đầy đủ, reading/assessment/residual tách riêng; chưa đọc không no-AU |
| Field length repair | Ngừng | Ngưỡng chỉ warning theo36, giữ cap tài nguyên và incomplete detection |
| Host source/schema gates | Giữ tối thiểu | Hash/offset/type/ID không chứng minh semantic correctness |
| Agent-review/verifier toàn corpus | Không thêm mặc định | Grounded draft và ready-for-citation tách trạng thái, không có human-gold claim |
| Issue/NN | Giữ preprocessing metadata | Chưa quyết định AU–NNmatching, alias/hierarchy matching, candidate/reranker |
| K0→K1→K2 | Chốt thứ tự thử | Equal-exposure authoring trước, rồi đọc chủ động toàn5án, rồi tối ưu từng biến |

Không sao chép gold-family selection của KOS sample. Đọc thêm nguồn/đổi model không tự chữa authoring đã sai trên TARGET đủ thông tin. Các lợi ích chất lượng/chi phí vẫn là giả thuyết; không gọi tiết kiệm do dừng thiếu nguồn.

## Lịch sử P2 và các checkpoint trước chuyển hướng

Phần sau giữ nguyên để truy quyết định cũ, không còn ưu tiên khi xung đột với bảng hiện hành.

# Bảng quyết định preprocessing và xây KB

## Phạm vi đã chốt

Giai đoạn hiện tại xây source/context map, SourceBlock, AnalysisRegion tạm, AU, Issue metadata, CiteSite và NN. Chưa chốt phương pháp nối NN với AU, candidate retrieval, ranking hoặc chọn case cuối.

## Quyết định hiện hành

| Thành phần | Quyết định | Lý do | Điều kiện xem lại |
|---|---|---|---|
| Source bất biến, hash, exact offsets | Bắt buộc | Provenance và kiểm chứng | Không bỏ |
| SourceBlock leaf có thứ tự, không chồng lấn | Kiến trúc chính P2 | Giữ cấu trúc nguồn mà không ép semantic partition | Source round-trip và block error audit |
| SentenceAtom | Chỉ là địa chỉ trong block | Cần exact span nhỏ; không đồng nhất sentence với legal meaning | Sentence tests |
| Block tree toàn corpus | Bỏ | Heading có thể thiếu/sai; tree tạo dependency giả | Chỉ thêm relation quan sát được |
| Phân loại heading ngữ nghĩa | Bỏ | Không cần cho AU extraction và khó tin cậy | Heading candidate hình thức là đủ |
| Boundary scorer + global LegalUnit partition | Bỏ khỏi đường chính; giữ P1 đối chứng | Một partition duy nhất chưa chứng minh phù hợp cho AU, speaker và condition | Chỉ phục hồi nếu P1 thắng held-out về AU/context và chi phí |
| Structural parser | Giữ rule baseline | Tạo block/address rẻ và tái lập | Parser ablation |
| Structural relation | Chỉ next/previous, containment, continuation và heading dependency có evidence | Hỗ trợ context mà không dựng semantic graph | Audit false relation |
| Marker làm anchor CiteSite | Giữ ưu tiên cao | Phù hợp artifact KOS và query bị che | Không suy marker thành authority identity |
| Không marker đồng nghĩa không có NN | Bỏ | Citation cue và fallback vẫn có thể tạo CiteSite | Ghi origin riêng |
| Citation/reference rules | Giữ baseline | Bảo vệ span và hỗ trợ context | Sequence model phải thắng ablation |
| NER/term/role/speaker model | Tùy chọn, mặc định tắt | Transfer và compute chưa đo | Bật riêng sau held-out gate |
| ContextHint | Giữ rule local tối thiểu | Đề nghị context rẻ, có evidence | Bỏ từng hint nếu chỉ tăng token |
| AnalysisRegion | Kiến trúc chính P2 | Context tạm có thể chồng lấn, không làm biến dạng source | So P0/P1/P2 |
| Materialize region text toàn corpus | Bỏ | Lặp text và invalidation tốn kém | Chỉ lưu manifest/SpanRef |
| Mỗi content block được phủ bởi primary target | Bắt buộc; block dài được chia thành derived slices | Không bỏ AU chỉ vì thiếu cue/citation, không biến slice thành cấu trúc canonical | CoverageLedger |
| Auto-skip block theo AU cue | Bỏ | Dễ tạo omission có hệ thống | Chỉ ưu tiên lịch, không bỏ target |
| ContextObligation | Giữ ở run ledger | Phân biệt thiếu context với no-AU | Cap expansion và unresolved rõ ràng |
| AU detector ưu tiên recall | Giữ | Omission AU giới hạn KB | Đo span/semantic recall và cost |
| Model AU few-shot | Giữ, không train ở giai đoạn này | Có tập kind nhưng chưa có dữ liệu train đủ | So model/prompt trên cùng regions |
| Dùng cùng model cho extraction, repair và retrieval | Bỏ | Mục tiêu chất lượng/chi phí khác nhau | Chọn và version độc lập |
| Repair agent đọc toàn corpus | Bỏ | Không phù hợp quy mô/token | Chỉ repair target có trigger |
| AU accepted có field-level witness | Bắt buộc | Exact span chưa đủ cho attribution/condition | Acceptance profile theo AU kind |
| Issue | Giữ như nhãn mở | Cần chủ đề/doctrine nhưng chưa có taxonomy đóng | Không dùng enum cố định |
| Alias là chuỗi trần hoặc parent/child | Bỏ | Tương đương tên khác quan hệ phân cấp | Record riêng có status/provenance |
| Issue là hard gate NN–AU | Chưa quyết định | Thuộc retrieval sau, dễ làm mất recall | Đánh giá riêng |
| Full KG/RDF hoặc microservice | Bỏ khỏi pilot | Chưa có lợi ích đủ bù độ phức tạp | Chỉ xem lại khi có nhu cầu liên thông |
| Cache/resume/invalidation | Bắt buộc | Tránh trả lại compute và dùng artifact cũ | Fault-injection tests |

## Vai trò của marker theo KOS

Marker dạng FRAGMENT_SUPPRESSED, REFERENCE_SUPPRESSED và CITATION_SUPPRESSED là dấu hiệu mạnh để neo CiteSite/NN. Nó không chứng minh đoạn cạnh marker là AU, không xác định authority identity và không thay evidence. Không có marker không đồng nghĩa không có citation need.

## Phương án đối chứng

| Arm | Cách dựng context | Vai trò |
|---|---|---|
| P0 | Paragraph/source block với số neighbor cố định | Baseline tối thiểu |
| P1 | Sentence → boundary scorer → global LegalUnit | Đối chứng kiến trúc cũ |
| P2a | SourceBlock + bounded local context | Kiểm tra lợi ích của bỏ global partition |
| P2b | P2a + ContextHint local | Kiểm tra hint |
| P2c | P2b + một vòng ContextObligation có cap | Kiểm tra expansion có điều kiện |

P2 là kiến trúc hiện hành ở mức thiết kế. P2b hay P2c chỉ được chọn làm cấu hình chạy sau pilot; không mặc định expansion luôn có lợi.

## Những gì chưa được chứng minh

- SourceBlock parser chưa được kiểm chứng trên toàn bộ format án.
- ContextHint chưa được chứng minh giảm omission.
- P2 chưa được chứng minh rẻ hoặc tốt hơn P0/P1.
- Model AU, caps, batch size và repair budget chưa chốt.
- Issue/alias chưa được chứng minh hữu ích cho retrieval.
- Không có tuyên bố retrieval quality từ schema PASS hoặc CoverageLedger complete.

Mọi lợi ích trên là giả thuyết phải phân xử bằng kế hoạch ở 05_experiment_plan.md.

## Checkpoint Kế hoạch 11 — 2026-10-11

- **Giữ:** primary proposition trong raw TARGET, review sidecar khóa nguồn/run/proposal và witness riêng từng field. Protocol/offset PASS vẫn tách khỏi review ngữ nghĩa. Review thiếu/bất đồng giữ unresolved; không lấy atom TARGET phụ làm bằng chứng ownership.
- **Đã đo:** bốn cặp metadata-only hoàn tất 8 request; P2b tăng 1.027 token (+9,69%), tổng usage biết được 22.345 gồm warmup/probe. Resume có 0 lần gọi mạng.
- **Cần đo thêm (`needs_measure`):** review độc lập và phân xử thấy P2b thêm một AU được hỗ trợ tại 013948 với condition witnesses giữ scope 112(3)/section97. Token tăng và cả hai arm còn lỗi qualification; chưa có so sánh chất lượng tương đương. Chưa bật mặc định, không kết luận hint vô ích; giữ worker/arm để thử lặp, context expansion hoặc tập giữ riêng.
- **Chưa đạt cổng chất lượng extraction tổng quát:** sau review độc lập che arm của tester_advanced và phân xử, 3 accepted_agent_reviewed, 4 rejected, 0 unresolved. Cả 8 target không thấy proposition riêng biệt bị bỏ; omission pass không chữa qualification. Checkpoint unknown ban đầu được giữ nguyên. Đây là review phát triển, không phải gold; không mở Plan 12.

Nguồn quyết định: `pipeline_v1/outputs/plan11_hint_pairs_run_20261011/decision.json` và các review được lưu riêng, không sửa artifact lịch sử.


### Checkpoint Plan 11 — vòng v5/v6 ngày 2026-10-11

Đã sửa renderer để phân biệt chính xác `TARGET_BODY` với `CONTEXT_PADDING`, giữ nguyên atom/source/offset; render và prompt version tham gia cache identity. V6 bổ sung ví dụ âm party argument/citation list bằng dữ liệu tổng hợp. Không đổi model Qwen3.5-9B, schema, endpoint hoặc giới hạn output.

Local Main 43 test PASS, tester độc lập 24 PASS. V6 chạy đủ 8 request trên bốn cặp development; resume 8 cache/0 lời gọi mạng. Review che arm có 4 supported/4 rejected trước dedup, mỗi arm 2 supported/2 rejected; negative controls đúng. Store lọc sau dedup có 3 accepted_agent_reviewed, 3 rejected, 2 superseded; review đầy đủ không đồng nghĩa extraction đạt chất lượng.

Lỗi còn lại: court interpretation bị gán statute và lặp hệ quả tại 013948. Không khẳng định mọi proposal bị loại đều context-only: TARGET có cơ sở liên quan, còn độ chi tiết của interpretation chưa chốt. Qualification từng contested ở v5 được reviewer v6 chấp nhận dạng tóm lược; không coi thay đổi verdict là bằng chứng model sửa nghĩa. Agent review không phải gold.

P2a 12.536 token, P2b 13.514 (+978, +7,80%); tổng v6 biết được 26.166 gồm warmup/probe. Tổng hai vòng v5/v6 50.190 token provider báo; usage warmup lỗi, review Codex và GPU/billing chưa đo. P2b bổ sung evidence cho referent holding, không thêm AU đúng được review hỗ trợ; tác dụng downstream chưa đo. ContextHint vẫn needs_measure, chưa bật mặc định; metadata-only arm là disable_candidate trên workload này, chưa suy rộng toàn corpus.

Dừng vòng tuning này; chưa chạy 20 target-holdback và chưa mở Plan12. Tập target khóa trong cùng KOS-5 không phải case-held-out. Bước riêng tiếp theo cần cô lập quoted statute/court interpretation/duplicate hoặc so model trên input khóa; chưa chạy thêm model/remote. Báo cáo, manifest, review, costs, cache và checkpoint: `knowledge_base/pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/decision.md`. V5 vẫn giữ lịch sử tại `outputs/plan11_semantic_v5_gate_20261011`; code/artifact hiện local, chưa nằm trong Git HEAD.
