# Kế hoạch: KB cấu trúc, truy hồi hybrid và agent truy nguồn citation

[Tiến độ M0–M7 hiện hành ngày 10/11/2026](../PROGRESS.md). Full ingestion và hybrid đã có kết quả thực tế. Phạm vi M3 còn phrase/identity, hoàn thiện context delivery và review cuối. Các checkpoint cũ bên dưới giữ để truy vết quyết định.

Kế hoạch chi tiết mới chờ review: [M3 full search](M3_FULL_SEARCH.md). [Prompt AG review thiết kế](../AG_REVIEW_M3_FULL_SEARCH_PLAN_PROMPT.md). Chưa chốt các giá trị đề xuất hoặc triển khai từ draft này.

Ngày: 05/11/2026. Checkout: `E:/Git/coliee-case-retrieval`.
Namespace triển khai đã chốt theo yêu cầu người dùng: **`pipeline_v2/` tại root repo**. Bản kế hoạch trong thư mục này là bản dùng cho triển khai. Khi dọn repo ngày 10/11/2026, các căn cứ nghiên cứu được chuyển vào `docs/research/`.

**Cập nhật 08/11/2026:** M3 optimization V2 pilot đã được AG chạy và Main nghiệm thu. Runner full corpus mới đã triển khai,30/30tests và audit plan thật415.693passages/7.708cases PASS;6.496batches64, BM25/schedule local đã có. Chưa chạy full inference/ingestion, chưa có fullhybridsearch hoặc COLIEE F1/M4. Xem [M3 full](../M3_FULL.md), [tests](../M3_FULL_TEST_REPORT.md), [lệnh giao AG](../AG_M3_FULL_TEST_PROMPT.md). Các trạng thái cũ bên dưới là checkpoint lịch sử.

Trạng thái: **M0 đã khóa; M1 Revision 2 được chấp nhận về nguồn và ranh giới marker để chuyển M2 với giới hạn đã ghi** ([M0](../M0.md), [M1 R2](../M1_REVISION2.md), [kết quả kiểm thử](../M1_REVISION2_TEST_REPORT.md), [contract chuyển giao Section 3.3](SOURCE_CHUNK_INDEX.md#33-contract-chuyển-giao-m1-revision-2--m2)). AG đã review R2; không coi đó là chứng nhận ownership/language accuracy toàn corpus. Theo yêu cầu người dùng, xử lý riêng tiếng Pháp tạm hoãn; giữ nguyên văn, không dùng language metadata làm bộ lọc. Bundle M1 v1 giữ làm lịch sử. Model/tokenizer/runtime profiles chưa chọn và được giữ `not_ready`. Phần M2 phụ thuộc tokenizer và M3–M7 chưa triển khai; chưa xây index, embedding, gọi model hoặc deploy. Không sửa artifact lịch sử.

Cập nhật M2: phần độc lập tokenizer ở Section 3.5 đã triển khai và kiểm trên corpus thật ([M2](../M2.md), [48/48 tests và audit](../M2_TEST_REPORT.md)). Bundle `artifacts/m2_navigation_20261105_v1/` sẵn sàng cho review rộng navigation/preview theo [prompt AG](../AG_REVIEW_M2_NAVIGATION_PROMPT.md). Chưa hoàn thành toàn M2: core chunks theo token, embedding-input preflight và agent payload token budget chờ người dùng chốt profile; không tự mở M3 hoặc inference.

**Quyết định mới:** người dùng đã chốt `Qwen/Qwen3-Embedding-4B` tự host trên Modal, tokenizer từ cùng repository. Xem [lựa chọn embedding](../EMBEDDING_SELECTION.md) và `pipeline_v2/configs/embedding_selection.json`. Các dòng/profile chưa chọn model ở M0 và bundle navigation phản ánh checkpoint trước quyết định này, được giữ nguyên. Revision/assets/token preflight và runtime Modal chưa ready; tokenizer agent vẫn chưa chọn.

**Navigation hiện hành sau review preview:** dùng `artifacts/m2_navigation_20261106_v3/`, không dùng v1 hoặc checkpoint v2 thay bản cuối. [Bản sửa preview](../M2_PREVIEW_REVISION2.md) đạt 55/55 tests, validator và audit raw/M1 cũ–mới trên 7.708 nguồn PASS; source/unit IDs/mapping/anchors không đổi. Xem [kiểm thử](../M2_PREVIEW_REVISION2_TEST_REPORT.md) và [prompt AG review lại](../AG_REVIEW_M2_PREVIEW_REVISION2_PROMPT.md). Chưa triển khai token chunking hoặc mở rộng runtime; các bản cũ giữ để truy vết.

## 1. Đích đến và phạm vi

**Phân công M3 đã sửa theo user:** Codex triển khai/sửa production; AG chỉ review, viết tests độc lập và chạy thử nếu cần trên bản đã freeze. Code pilot/CLI và manifest 1.024 inputs đã được chuẩn bị local; không coi đó là remote pilot hay toàn M3 đã PASS. Xem [M3](../M3.md), [local tests](../M3_LOCAL_TEST_REPORT.md) và [prompt AG test-only](../AG_M3_TEST_PROMPT.md). Không dùng prompt cũ để giao AG viết production.

**Cập nhật cuối M2:** phần token passages đã hoàn tất local, không còn chờ tokenizer embedding. Dùng `artifacts/m2_passages_20261106_v1/`:415.693passages từ382.343parents/7.708nguồn;65tests, validator tái dựng và audit raw/token độc lập PASS. Xem [M2 passages](../M2_PASSAGES.md), [kiểm thử](../M2_PASSAGES_TEST_REPORT.md), [prompt AG review](../AG_REVIEW_M2_PASSAGES_PROMPT.md). Các đoạn "chưa chọn/token not_ready" phía trên mô tả checkpoint lịch sử. Tokenizer agent/budget M4 và runtime endpoint vẫn chưa ready. Chưa tự mở M3/inference/deploy.

Đầu vào là query A và candidate universe được khóa; đầu ra là tập case IDs dự đoán noticed theo labels chuẩn COLIEE. Agent tìm án A thực sự sử dụng, không chỉ các án tương đồng chủ đề. Đo chất lượng cuối bằng micro-P/R/F1 ở cấp unique `(query, candidate)`.

Trước query xây **kho nguồn + cấu trúc + metadata quan sát được + BM25/dense indices + công cụ đọc**. Khi query đến agent mới phân tích nhu cầu nguồn, truy tìm, đọc và đối chiếu các nguồn cạnh tranh. Không bắt xây AU/doctrine/citation graph toàn corpus trước.

Tài liệu chi tiết:

- [Nguồn, chunking và chỉ mục](SOURCE_CHUNK_INDEX.md).
- [Agent, trạng thái và đánh giá](AGENT_AND_EVALUATION.md).
- Căn cứ: [rubric noticed](../research/NOTICED_CASE_CRITERIA.md), [thiết kế đã review](../research/citation_source_agentic_design_20261105.md), [trial retrieval cũ](../research/bounded_agentic_retrieval_trial_20261104.md).

## 2. Quyết định đã chốt

1. Marker `[số]` đầu dòng là ranh giới unit độc lập. Role `current_case/quoted/unknown` cần evidence, không dùng thứ tự số để gộp hoặc reset. Số đoạn trong quotation/bản song ngữ không được coi là ID duy nhất.
2. Nguồn canonical giữ toàn bộ raw bytes. Passage tìm kiếm là view ghép/tách có mapping về nguồn, không thay source partition.
3. BM25 và dense ban đầu dùng cùng `core passage IDs` và body. Khác biệt tokenizer/analyzer hoặc prefix được khai báo; thử thêm ngữ cảnh dense ở thí nghiệm riêng.
4. Có cả case-level BM25 và **global passage retrieval** cho BM25/dense; không chỉ search trong case đã biết.
5. Một controller/query, tự chọn search/open/expand trong ngân sách. Reader/searcher/verifier là trách nhiệm logic, chưa cần nhiều agent thường trực.
6. Final selector phải sử dụng evidence. Không dùng nguyên RRF top5 cũ làm output cuối, không coi passage_verified là điều kiện bắt buộc để positive.
7. Gold, V3 dossiers, citation index ngoài corpus chỉ thuộc vùng nghiên cứu/evaluator; runtime nghiên cứu corpus-only không được nhận chúng.
8. Passage nhỏ dùng cho embedding/search; khi hit `12b`, context đọc mặc định là full paragraph cha `[12]` cùng paragraph trước `[11]` và sau `[13]` theo source order. M2 lưu mapping, M3–M4 mở raw và giao payload; giữ rõ hit/context, dedup và phần pending nếu vượt cap. Chi tiết ở Section 3.4 của contract nguồn.
9. Query vừa ngân sách đọc có thể giao toàn văn; query dài dùng bản đồ + context ưu tiên và mở thêm theo nhu cầu. M2 chuẩn bị navigation/preview/anchors có raw provenance; M4 quyết định payload và quản lý coverage. Người dùng đã hoãn chọn embedding model/tokenizer: triển khai phần độc lập trước, phần chunk/token preflight phụ thuộc để `not_ready`. Chi tiết ở Section 3.5 của contract nguồn.

## 3. Phần tái dùng và khoảng thiếu

| Có thể tái dùng qua adapter | Cần bổ sung, không tuyên bố đã sẵn sàng |
|---|---|
| Source/hash/handle và journal của `bounded_retrieval_trial` | Global passage indices, metadata search view và hybrid adapter |
| Navigation search/open/expand của `case_agent_c` | Contract source hypothesis và live multi-turn runner |
| Basket/pending/delivery/resume principles | Final scorer/selector thực đọc evidence; calibration policy |
| SourceBlock/atom contracts | Char↔UTF-8 byte mapping và parser áp cho corpus mới |

Không bê nguyên chunker 1800 ký tự hoặc tokenizer `[a-z]+` của prototype: chúng chưa đủ cho paragraph lồng, citation số và tiếng Pháp. C Session chỉ nhận FakeTransport, bounded trial không có model client; CLI chạy được không chứng minh live agent ready. Không sửa ngầm các runner C/D hoặc V13–V15.

## 4. Các mốc triển khai và gate

Chỉ triển khai mốc kế tiếp khi mốc phụ thuộc đạt hoặc giới hạn được ghi cụ thể. Đây không tự cấp quyền chạy paid inference/full-corpus embedding. Khi có yêu cầu thực thi, phần local reversible được tiến hành trong scope; API/deploy/quy mô trả phí phải thuộc authorization thực tế, không xin lại quyền đã có.

| Mốc | Công việc và đầu ra | Tiêu chí đạt |
|---|---|---|
| **M0 — Khóa profile** | Inventory read-only; candidate manifest; exposure ledger; source/chunk/analyzer profile; chọn embedding model/tokenizer và runtime model profiles | Paths/splits/versions/budgets rõ; không trộn test. Chưa chọn model thì dense=`not_ready`, các mốc nguồn vẫn làm được |
| **M1 — Kho nguồn/cấu trúc** | Source registry, byte↔char map, paragraphs/sidecars, metadata evidence | Full-byte coverage và round-trip; quotation/bilingual/unknown không mất; không gán speaker semantics bằng regex |
| **M2 — Passage chung** | Chunk manifest, core/context refs, tokenizer counts, coverage report | Đúng paragraph cha; input embedding không overflow/truncate; short/long/fallback rõ; BM25/dense cùng body/version |
| **M3 — Chỉ mục hybrid** | Case BM25, passage BM25, vector cache/index, identity/phrase search và fusion | Tìm toàn corpus khi chưa biết case ID; không lấy overlap thành phiếu; so ba kênh với cùng unique-case budget |
| **M4 — Công cụ/harness** | Search/open/expand, delivery ledger, immutable events, resume/fallback | Tool result vào model ở lượt sau; caps không reset; source drift invalidates assessment; fake/replay không bị gọi là live |
| **M5 — Baseline nguồn cố định** | Query source needs, fixed search/read schedule, pair evidence và variable-count selector | End-to-end chạy được trên scope được phép; evidence thật ảnh hưởng selection; mọi candidate có trạng thái và provenance; không gold vào model |
| **M6 — Agent thích ứng** | Controller chọn search/open/expand/assess/stop; targeted review | So được với fixed trên cùng toolbox/profile/caps/selector; partial/budget-stop không giả completion |
| **M7 — Đánh giá khóa** | Frozen bundles, scores, error analysis và cost report | Micro-P/R/F1 đủ denominator; discovery/reading tách biến; không tune bằng holdout; quyết định giữ/loại thành phần dựa kết quả |

M1–M4 là nền tảng trước query; M5–M7 kiểm hành vi xử lý query. Có thể build fixtures trước khi model được chọn. Không coi mock PASS là mốc M5 đã hoàn tất.

## 5. Profile khởi đầu và quyết định còn mở

| Thành phần | Profile đề xuất | Cách chốt |
|---|---|---|
| Core chunk hiện tại | Giữ whole parent <=448 full tokens; parent dài target mềm320; không ép ghép parent ngắn | Tokenizer Qwen đã pin; không coi các số này là ngưỡng khoa học; xem M2_PASSAGES.md |
| Overlap hiện tại | Variant trong parent, mong muốn128 content tokens, thực đo; thay đề xuất baseline không overlap/variant64 ban đầu | Chưa tối ưu retrieval; biên whitespace/fallback không nhận là câu; không đếm overlap thành phiếu độc lập |
| BM25 | Bắt đầu k1=1.5, b=0.75, Unicode legal text + exact identifiers | Giữ config rõ, kiểm analyzer; không lấy stopwords cũ làm chuẩn ngữ nghĩa |
| Dense | Qwen3-Embedding-4B tự host Modal; tokenizer/revision đã pin cho M2, runtime chưa triển khai | Trước inference kiểm endpoint/template/caps; chưa khóa pooling/dimensions/normalization/engine/GPU; không tự deploy |
| Fusion | Case-rank RRF khởi đầu equal weight, k=60, missing rank=0 contribution | Tối đa một policy cơ sở rồi ablation discovery; không dùng công thức baseline+mean-search cũ |
| Final selector | Contract chung, số output biến thiên; ngưỡng ở discovery | Không confidence tự thuật thành xác suất calibrated; không top5 mặc định |
| Agent budget | Chốt sau payload/token preflight | Ghi token/call/search/open/review/retry; không tự copy caps 6-action/800-output-token |

Nếu tokenizer quyết định chunk boundaries thì thay tokenizer phải version chunk và rebuild các index phụ thuộc. Đổi embedding view/model chỉ được reuse vectors nếu exact fingerprint tương thích, không đổi metadata rồi dùng cache cũ.

## 6. Workstream và ownership khi bắt đầu triển khai

Không tạo runtime code trong công việc lập kế hoạch này. Namespace implementation là `pipeline_v2/`: source/chunking/retrieval/agent/selection/evaluation/contracts nằm tại đây; cấu hình ở `pipeline_v2/configs/`, tests ở `pipeline_v2/tests/`, tài liệu ở `pipeline_v2/docs/`, indices/cache/vectors/runs ở `pipeline_v2/artifacts/`. Mỗi run write-once. Đọc corpus từ `data/` hiện có, không sao chép hoặc sửa raw corpus. Không sinh artifact mới vào pipeline_v1 hoặc research_bundle cũ. Việc tái dùng V1 là tham khảo/port có kiểm tra vào V2; không mặc định import runtime V1 hoặc sửa V1 để V2 chạy.

- Main: quyết định interface, thứ tự mốc, scope/budget và nghiệm thu; không tự mở mốc workload chưa được giao.
- Implementer: một mốc/một scope file được giao rõ. M1–M3 có dependency; không cho hai worker sửa chung schema/source adapter.
- Tester hoặc tester_advanced: test invariants độc lập, review semantic diagnostics/selection và kiểm bản code cuối. Không tự sửa production code.
- Chỉ parallel các phần độc lập, tối đa hai subagent theo AGENTS.md; agent runtime của sản phẩm không đồng nghĩa subagent phát triển.

## 7. Quy mô phát triển và dừng

- Structural fixtures: tận dụng các lỗi biết trước từ V1–V3 và KOS, ghi `exposed_diagnostic`, không coi chúng là holdout.
- Feasibility cohort: đề xuất **20 train queries mới theo exposure ledger**, 10 discovery + 10 holdout; lọc chỉ theo eligibility/exposure, không theo BM25 hardness hoặc gold count. Lưu seed, toàn bộ exclusion reasons và sampled IDs trước tuning.
- Không dùng reserved holdout cũ của `split_registry.v1.json` làm discovery. Loại các query đã dùng trong rule study/pilot, `043625` và nhóm calibration đã biết; rà lịch sử exposed trước chọn. Nếu lịch sử không đầy đủ, gọi đúng là fresh-by-ledger, không chứng nhận blind tuyệt đối.
- Tối đa một embedding model chính và một variant chunking trong vòng đầu. Không đồng thời tune model/chunk/fusion/scorer/agent tùy ý trên 10 query. Freeze theo từng mốc; holdout dùng một lần cho bộ policy đã chốt.
- Mẫu này chỉ kiểm feasibility, không bảo đảm statistical power. Không thắng fixed policy thì giữ fixed; không đủ evidence thì kết luận chưa phân xử, không mở rộng vô hạn.

## 8. Hoàn thành kế hoạch khác với hoàn thành hệ thống

Mốc đạt phải có artifact, lệnh tái hiện và kết quả kiểm thật. Chỉ đánh dấu `ready` cho scope đã kiểm; missing file, source unknown, pending embedding hoặc provider failure phải giữ trạng thái riêng.

Khi bàn giao từng mốc, báo ngắn: file thay đổi, kiểm tra đã chạy, kết quả, lỗi/retry, usage biết/không biết và việc còn lại. Không sửa labels hoặc báo cáo lịch sử để kết quả mới trông tốt hơn.

## 9. Review kế hoạch

Nội dung thiết kế gốc đã qua hai lượt review chuyên trách độc lập: source/chunk/index và agent/runtime/evaluation. Kết luận: approved-as-plan, không còn blocker thiết kế; không có nghĩa hệ thống đã chạy hoặc đạt chất lượng.

Đã bổ sung sau review: decoder/BOM policy trong char↔byte mapping và yêu cầu raw evidence có mặt trong payload hiện tại khi assess/chốt; read history không thay nguồn. Kiểm tra đường dẫn nội bộ của cả ba tài liệu: không có link thiếu. Không chạy production tests hoặc inference vì lượt này chỉ tạo kế hoạch.

Namespace được cập nhật theo chỉ thị người dùng ngày 05/11/2026. Việc tạo thư mục/tài liệu không đồng nghĩa đã triển khai M0–M7.
