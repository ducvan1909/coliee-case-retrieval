# Kế hoạch xây KB theo agent authoring gần KOS

Thiết kế cập nhật2026-10-24; đồng bộ04/05/37 và [cải tiến39](39_kos_authoring_improved.md). K0 v1 đã implement/live nhưng0AU; bổ sung39 chưa code. Giữ nguồn và artifact trước làm lịch sử, không relabel thành kết quả của bản sửa.

## 1. Sản phẩm cần xây

| Kho | Trách nhiệm |
|---|---|
| source_store | Text bất biến, case/source version/hash và exact offsets |
| address_store | SourceBlock/SentenceAtom, structural metadata quan sát được |
| case_work_store | Navigation, ReadScope/ReadLedger, budget, request/receipt và draft pointers |
| assessment_store | ReadAssessment gọn theo phạm vi thực sự được xem; result/reason/basis và parent receipt, không human gold |
| au_store | Claim, kind, evidence, limits, owner case/source, revision và quality status |
| issue_store | Nhãn mở, proposal/alias/link có version/provenance |
| query_workspace | CiteSite/NN/evidence và Issue metadata tùy chọn |

Không tạo semantic partition toàn source. Source text chỉ lưu một lần. Agent có thể xem/tạo AU qua nhiều block cùng case; host không lấy vị trí start làm ranh giới semantic.

## 2. Tái dùng và bỏ khỏi mặc định

Tái dùng source/atom contracts, raw index, open_span, receipts/checkpoints và code transport sau khi adapter đúng contract. Không bắt mỗi SourceBlock gọi LLM, không dùng strict TARGET ownership để chặn AU phát hiện ở context đã mở. Ngừng shortening vì độ dài. Giữ các worker/AnalysisRegion P2 theo version lịch sử, không tự xóa dữ liệu.

Không NER/cue/rhetorical-role model, planner toàn cục, verifier toàn corpus hoặc full KG mặc định. Chỉ bổ sung sau khi baseline authoring mới có kết quả và ablation đủ lợi ích.

## 3. Các phần triển khai nối tiếp

### Phần1 — Workspace và source tools local

Input: source_store/atom maps, manifest source và adapter hiện có. Host tạo CaseWork, ReadLedger và catalog evidence thực sự đã mở. Tools get_case/open_region/search_source/get_drafts, tất cả cùng case/source binding; preview không evidence.

Đầu ra: mock case work có source available/delivered/assessed/residual tách biệt. Đạt khi cross-block/context-owned evidence, lỗi cục bộ, cap, resume và invalidation đúng. Không inference/deploy.

### Phần2 — Agent authoring và lưu AU

Input:04/37 và failure set của review A. Wire substance claim/kind/evidence_ids/limits; owner/hash/offset do host. Cho submit add/update nhiều AU theo legal point, không quota theo block. Why notice-worthy là tiêu chí, note tùy chọn.

Đầu ra: grounded_draft/revision store và warning policy. Không đổi draft thành reviewed_supported do host-valid; không tự gọi repair vì độ dài/kind uncertain. Case finish có residual, không hứa semantic completeness.

Trước bản authoring mới phải kiểm ví dụ JSON đầy đủ bằng controls tổng hợp dương/âm/bất định khác input minh họa. Giữ wire AU, không nhập quota KOS; chỉ thêm `empty_reason` nullable vào envelope sau khi control đạt. Host suy ReadAssessment/no_au_candidate/uncertain từ scope và receipt, không gọi model gán nhãn từng block. [39, mục4–5](39_kos_authoring_improved.md).

### Phần3 — K0 cùng nguồn với A

Khóa union16scopes/3case từ payload đã gửi, không đưa KOSClaim hoặc lời giải review vào input. Nhiệm vụ theo case, không block-owner; currentQwen9B để cô lậpworkflow. Input6000/output800, cap12modelturn; tổng token reservation và usage thực mỗi chỉ số không vượt30000, không cộng hai chỉ số vào nhau. Preflight exactpayload/estimates và chặn admission trước dispatch nếu không còn đủ reserve.

Đầu ra: authoring outputs có source provenance, chi phí kể cả continuation/tool-turn và failures; report so với A/v2 cùng source exposure. Chỉ chạy live sau local và lệnh cho phép riêng, không gọi model trong đợt thiết kế.

Sau authoring, CaseWork0AU trong union có thể nhận tối đa1validate/case, gồm cả resume và nằm trong cap chung; không bắt có AU, không mở ngoài union. Đầu ra validate là giữ kết quả, bổ sung draft có nguồn hoặc uncertain, có parent receipt/revision. Không đủ reserve/nguồn không vừa cap thì ghi chưa chạy, không tự chia thành vòng đọc toàncase. Chưa thêm nhánh này vào runtime; đo R0/R1 theo05/39 trước bật. K0 v1 live0AU hiện chưa đạt control, nên không mởK1.

### Phần4 — K1 đọc chủ động năm án

Sau quality gate K0, dùng toàn nguồn5casecalibration; raw source search/open và navigation không KOS-guided. Khóa budget sau inventory/preflight; dừng partial với not_assessed/unresolved. So chất lượng/coverage theo token với baseline cùng universe, không tính nguồn chưa đọc là negative.

Đầu ra: reading/semantic/cost tradeoff, chưa coi là kết quả toàn corpus. Không viết generic ranking model hoặc nhiều queue trước khi có nhu cầu đo được.

### Phần5 — Issue, NN và snapshot

Giữ IssueProposal/IssueLink nullable, không ép alias/hierarchy resolution và không chốt matching. Query source dùng marker và non-marker origins tạo CiteSite/NN có nguồn. Snapshot draft tách snapshot ready-for-citation; AU reviewed_supported phải có review provenance.

Đầu ra kết thúc preprocessing: source/address, AU có trạng thái, Issue metadata, CiteSite/NN và reading residual. Retrieval agent planning, AU–NN matching, reranker và finalset chưa nằm trong phần này.

## 4. Thông tin/config cần trước khi code/live

- source/hash và full-text address inventory; schema/tool/message versions;
- model/runtime identity từ knowledge_base/.env hiện có, không in credential; K0 giữ Qwen/Qwen3.5-9B, không tự fallback/deploy;
- bounded initial scope, input/output/turn và aggregate budget; token count/estimate method;
- wire action/submit và durable job/revision IDs; receipt-before-commit, unknown outcome recovery;
- acceptance profile soft length, grounded_draft/reviewed_supported, sampling/review limits;
- frozenK0sourceunion và failurecontrols; KOS dùng saugeneration, không chọn nguồn;
- workload update/resume tests và metric accounting gồm lỗi, tool turns và nguồn lặp.

Chưa khóa runtime wire hoặc endpoint capabilities mới thì triển khai adapter/mock trước; không tự thay constrained decoding/grammar đã chạy chỉ từ tài liệu hướng này. Không coi topology mới là bằng chứng model9B sẽ hết lỗi semantic.


### Checkpoint triển khai K0 — 2026-10-23

K0 case-level authoring đã triển khai riêng tại `knowledge_base/pipeline_v1/k0_authoring/`, không thay runtime lịch sử. Chỉ dùng16scope/3case của A; live5request đúng wire nhưng0AU, diagnostic chưa qua positive control. K1 chưa triển khai. [Lịch sử38](38_k0_implementation.md); [bản cải tiến39](39_kos_authoring_improved.md) mới ở thiết kế, không tự migrate `assessed=true` cũ thành no-AU đã xác minh.
