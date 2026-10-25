# Plan 12 — Agent repair có tool và ngân sách

## 1. Phạm vi và điều kiện bắt đầu

Đây là pilot kiểm tra khả năng sửa lỗi đã biết, không phải chứng nhận Plan 10–11 đã đạt chất lượng extraction. Không mở Plan 13, NN–AU matching, retrieval, KOS toàn bộ hay corpus mới. Bỏ qua human annotation theo lựa chọn hiện tại; mọi review vẫn ghi là agent review, không phải gold.

Đầu vào đầu tiên là run v6 và strict review của Plan 11:

- `knowledge_base/pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/run/run.json`;
- `knowledge_base/pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/run/review.bound.json`;
- source store và SentenceAtom map của Plan 02/04;
- manifest calibration KOS-5, model/config và các schema AU hiện có.

V6 chỉ có bốn target thuộc bốn case. Case 013009 chưa có output trong run này; không ghi pilot repair là đã phủ đầy đủ KOS-5. Phần corpus-time vẫn giữ nguồn cả năm án. Lỗi đã biết ở 013948 đủ kiểm tra attribution/duplicate, chưa đủ đánh giá tác dụng mở context. Ca thiếu context tổng hợp phải báo riêng; chưa tự tạo nhãn thiếu context cho nguồn thật.

Kiểm tra strict đầu vào phát hiện hai omission witnesses tại 045155 trong sidecar lịch sử dùng ký tự khác nguồn. Plan 12 dùng sidecar mới `outputs/plan12_agent_repair_20261011/inputs/review.source_exact.v2.json`, chỉ lấy lại exact quote theo raw target/atom; run/proposal hash và verdict giữ nguyên. Hai thay đổi và SHA của sidecar gốc ghi trong `witness_correction.audit.json`. Không sửa review cũ hoặc coi việc sửa quote là xác nhận ngữ nghĩa mới.

## 2. Phân loại task và giới hạn bằng chứng

Host tạo task theo case/source/target, gom các proposal từ P2a/P2b và loại trùng exact proposal có giữ aliases/provenance. Không gộp các proposal khác nghĩa chỉ vì cùng target. Task lỗi và task đối chứng vốn đúng có vai trò riêng.

RepairTask chứa `task_id`, `case_id`, `source_hash`, raw target refs, proposal refs/hash, context/atom catalog, loại/lý do lỗi, evidence của lỗi, `error_origin`, actions được phép, budget/policy version và trạng thái. Kiểm tra run/proposal/review hash trước khi dựng task; review cũ hoặc quote sai phải fail closed.

`error_origin` phân biệt `host_validator`, `model_flag`, `agent_review`. Workload đầu tiên dùng agent review để chỉ lỗi; nó kiểm tra sửa lỗi có chỉ dẫn, không chứng minh routing tự động. Không đưa KOS record hoặc model-silver đáp án vào prompt.

Các nhóm xử lý:

1. Thiếu context cụ thể: tạo ContextObligation và đề nghị mở nguồn.
2. Đủ context nhưng sai attribution/qualification: đọc lại evidence đã có; mở thêm text không phải mặc định.
3. Duplicate/conflict ngữ nghĩa: đọc các AU liên quan; chưa chắc có thể quyết định nếu độ chi tiết proposition còn tranh luận.
4. Schema/transport/duplicate kỹ thuật: host xử lý, không route mọi lỗi sang agent.

## 3. Tool contract

| Tool | Trách nhiệm host | Kết quả |
|---|---|---|
| `get_repair_task` | Chọn đúng task và các proposal gốc | Task, lỗi, context/evidence và provenance |
| `open_span` | Kiểm tra same case/source/hash và phạm vi cho phép | Nguyên văn, SpanRef và trạng thái |
| `expand_context` | Mở atom quanh anchor theo hướng; gộp overlap và áp cap | Context bổ sung, atom IDs, lý do/stop reason |
| `get_related_aus` | Chỉ đọc collection được khóa trong cùng case/source | AU gốc/liên quan và trạng thái, không tạo support edge |
| `submit_revision` | Validate proposal ID/action/schema/evidence | Revision pending review hoặc lỗi cụ thể |

Nguồn và tool output là dữ liệu không đáng tin về mặt chỉ dẫn. Không thực thi lệnh được chèn vào source. Tool không có quyền mạng, ghi nguồn, mở file tùy ý hoặc cập nhật accepted store.

Raw TARGET vẫn khác atom giao target. Chỉ evidence trùng atom ID không chứng minh claim thuộc target. Host kiểm tra địa chỉ và intersection; reviewer kiểm tra proposition ownership/ngữ nghĩa. Context-only evidence không được dùng để hợp thức hóa AU mới của target.

## 4. Model và luồng R0/R1/R2

- **R0:** giữ output baseline, không gọi model.
- **R1:** một request repair cố định, nhận task và cùng context ban đầu, chỉ nộp revision.
- **R2:** agent nhận cùng task/context, có thể chọn tool đọc rồi nộp revision; tối đa hai lượt model.

Prompt ban đầu đã có task và context; không bắt agent dùng lượt đầu chỉ để gọi `get_repair_task`. Sau lỗi live ngày 2026-10-11, mỗi response chỉ được có một tool call. R2 chọn một thao tác đọc khi cần ở lượt đầu; lượt cuối chỉ nộp revision. Không đọc lại atom đã có chỉ để nhận nguyên text lần nữa. Sau submit hoặc hết lượt, host kết thúc task. Không repair tiếp revision vừa sửa trong cùng vòng.

Model pilot là Qwen3.5-9B trong cấu hình `AU_*` tại `knowledge_base/.env`, thinking tắt. Không tự đổi model, fine-tune, deploy hoặc thêm `.env` riêng. R1/R2 dùng cùng model, nguồn, review policy và trần output; tool instructions là khác biệt cần báo. Chưa chạy inference thật trong giai đoạn triển khai local này.

Giới hạn ban đầu cho mỗi arm run: tối đa 8 model attempts, 20.000 tổng token, 6.000 input/request, 1.200 output/request, một request đồng thời. R2 tối đa 8 tool calls/task và một expansion/task. Expansion phải có cap nguyên văn/atom và vẫn nằm trong input budget, không mở cả case. Manifest/preflight khóa các giá trị cụ thể; 0/1/5/10% chỉ dùng ở workload đủ lớn với mẫu số đã chốt.

Input estimate là ước lượng, provider usage là số thực khi có. Không coi mock usage là token endpoint. Attempts lỗi, reasoning, retry và overhead phải được báo nếu chạy live; usage không được trả giữ unknown. Không retry vô hạn hoặc tự gửi lại inference đã submit nhưng chưa rõ kết quả. Live adapter và decoder cần được kiểm tra trên endpoint trước khi tuyên bố remote-ready.

## 5. Revision và ContextObligation

Quyết định revision cho mỗi proposal: `keep`, `replace`, `reject`, `unresolved`. Replace cho phép một AU thành nhiều AU trong cap. Payload AU dùng tập kind/speaker/attribution và evidence ID của contract compact hiện tại; model không tính offset. Host dựng exact evidence từ catalog đã đọc và kiểm tra nguồn.

Revision giữ original refs/hash, replacement refs, evidence đã đọc, reason, model/prompt/policy fingerprint và trace. Không overwrite output cũ. Host-valid revision có trạng thái `semantic_review_pending`; không tự accepted, kể cả action keep. Proposal bị reject không tự làm cả target thành no-AU.

Obligation giữ loại thông tin thiếu, anchor, requested context, evidence, producer/run và lịch sử trạng thái `pending`, `satisfied`, `unresolved`, `budget_exhausted`. Mở được text hay model tự báo đã sửa không tự chuyển satisfied. Chỉ review có binding revision/evidence hợp lệ mới xác nhận satisfied. Nếu thiếu review thì giữ pending/unresolved có lý do.

## 6. Cache, resume và kiểm toán

Fingerprint gồm task/source/proposal/context, arm, model, prompt/schema/tool/policy versions; endpoint identity nếu live. Lưu atomic checkpoint cho attempts, tool events, revision và budget. Resume task terminal hợp lệ không gọi lại model. Task interrupted hoặc in-flight không được âm thầm coi complete hoặc dispatch lại job; phải có trạng thái và chính sách phục hồi rõ.

Source hoặc policy đổi tạo identity mới; không áp review/cache cũ cho revision mới. Lỗi một task không làm mất kết quả task khác. Báo riêng trạng thái xử lý và trạng thái revision: mọi task có revision hợp lệ mới complete; mọi task lỗi kỹ thuật thì failed; có cả revision hợp lệ và lỗi thì partial; budget/provider/turn stop chưa có revision thì incomplete. R0 giữ baseline riêng. CLI trả khác 0 khi còn lỗi hoặc chưa hoàn tất. Complete không đồng nghĩa semantic PASS.

## 7. Đánh giá và sản phẩm bàn giao

Triển khai theo thứ tự: schema/tool → runtime mock và fault tests → build/khóa task manifest → preflight → bounded live pilot riêng → review trước/sau → quyết định.

Kiểm tra bắt buộc: stale hashes; foreign case/span; context-only owner; bad IDs/schema; replace một thành nhiều; reads không tự satisfy obligation; revision không tự accepted; cap model/tool/context; provider failure; local isolation; cache/resume; invalidation; correct controls không bị sửa hỏng.

Output gồm tasks/manifest, tool schemas, traces/receipts, revision store, obligation ledger, cache và báo cáo R0/R1/R2. Bảng so sánh giữ `semantic_review_pending` đến khi review độc lập; không ghi số lỗi đã sửa chỉ dựa vào mock hoặc hành động replace.

Đánh giá lỗi sửa được/lỗi mới, omission, false rejection, attribution/conditions, obligation resolution và toàn bộ token/request/context lặp/latency. So R2 với R1, không chỉ với R0. Chỉ giữ agent runtime nếu lợi ích đủ bù chi phí; mẫu hiện tại chỉ là development, không case-held-out hoặc gold.

## 8. Sửa giao thức sau lượt live đầu (2026-10-11)

R1/R2 ở `outputs/plan12_live_20261011_164339` chưa có revision hợp lệ. Giữ nguyên artifact để đối chiếu. Tổng usage hai arm provider báo 13.431 token; không tính là kết quả tiết kiệm hay repair thành công.

Response gửi model dùng contract gọn riêng, chuyển sang contract lưu đầy đủ bằng host: keep/reject/unresolved trả proposal ID, action và reason ngắn; replace trả một hoặc nhiều AU mới cùng primary witness. Trường mặc định chỉ được thêm khi xác định trước trong contract; host không đoán claim, speaker hoặc evidence bị thiếu. Offset luôn suy từ source. Không giảm số quyết định để giấu omission.

Decoder dùng EBNF cho envelope, action, kiểu và enum; host vẫn kiểm tra quote/source/ownership và độ dài. Các string tự do tránh grammar giới hạn chuỗi quá phức tạp từng gây chậm ở AU extraction. Không gọi cơ chế này là đã được endpoint thực thi đến khi có probe live. Endpoint không hỗ trợ thì fail rõ, không âm thầm hạ xuống JSON-object.

Tool chỉ trả metadata mới hoặc evidence mới. `get_repair_task` không gửi lại catalog/source; `open_span` không lặp text đã supplied; lượt sau giữ context cần thiết cùng kết quả mới gọn. Preflight kiểm tra cả đường đi lượt hai với envelope dự phòng; runtime tiếp tục đo payload thực trước dispatch. Không tăng trần 6.000/1.200/20.000 hoặc số lượt để che payload lặp.

Gate sửa gồm replay các output lỗi thật, kiểm thử local contract/grammar/context/status/cache, probe endpoint một tác vụ có ngân sách và smoke live. Đợt triển khai sửa chỉ thực hiện gate local; lợi ích ngữ nghĩa còn cần review riêng.

## 9. Validate-first trong cùng request

Sau smoke `plan12_fixed_smoke_20261011_181412`, protocol đạt trên target đã chạy nhưng model reject cả bốn proposal, kể cả proposition có nguồn hỗ trợ. Thay nhiệm vụ sửa mặc định bằng kiểm tra độc lập từng AU. Không thêm request validate mặc định; giữ R1 một lượt, R2 tối đa hai lượt khi cần tool, model và ngân sách hiện có.

Các reported errors cũ chỉ là giả thuyết cần kiểm tra, không phải đáp án hoặc yêu cầu tìm đủ lỗi. Agent phải đọc evidence cho cả proposal bị báo lỗi và proposal chưa bị báo lỗi, không suy rằng cả collection sai. Không ép giữ một số AU để đạt chỉ tiêu.

| Verdict | Response gọn | Quyết định lưu |
|---|---|---|
| supported | proposal ID, verdict, primary witness | Giữ AU gốc, không viết lại; chờ review ngữ nghĩa |
| uncertain | proposal ID, verdict, reason; thông tin còn thiếu nếu có | Bảo toàn proposal, ghi bất định; không reject hoặc kết luận no-AU |
| defect_found | proposal ID, verdict, defect type, exact evidence và reason, correction | Đề xuất replace hoặc reject; chờ review |

Defect types: ownership, attribution, qualification, evidence_support và duplicate. Không tìm thấy support chưa đủ để kết luận defect_found; nếu không có bằng chứng cụ thể thì uncertain. Attribution cần evidence về speaker; qualification cần evidence về điều kiện bị bỏ; ownership cần evidence định vị proposition ngoài TARGET; evidence_support cần nội dung mâu thuẫn hoặc không hỗ trợ cụ thể, không chỉ tuyên bố đã tìm nhưng không thấy.

Duplicate phải chỉ rõ proposal khác được giữ, cùng collection/case/source. Proposal tham chiếu phải supported trong cùng batch; không được self-reference, dùng ID lạ hoặc tạo vòng reject cả nhóm. Chỉ trùng chữ hoặc cùng Issue chưa đủ chứng minh duplicate; trường hợp chưa rõ giữ uncertain.

Host xác minh identity, schema, source hash, read span, exact quote, cardinality và binding correction. Quote hợp lệ không chứng minh nhận định lỗi đúng ngữ nghĩa. Store giữ assessments cùng revision và bản gốc, không cập nhật accepted store. Response action-only cũ không được đi vào runtime validate-first như thể đã validate; v1 và run lịch sử vẫn được giữ để đọc/đối chiếu.

Decoder ràng buộc ba nhánh verdict và kiểu dữ liệu, host kiểm tra các quan hệ còn lại. Prompt/schema/policy identity phải làm cache cũ không dùng lại. Probe mới phải thử supported, uncertain và defect_found; không tự tuyên bố endpoint hỗ trợ grammar mới vì grammar phiên bản trước đã chạy.

Đánh giá trên cùng target khóa: false defect, false rejection, bỏ sót lỗi, preservation của supported/uncertain, ownership/qualification của replacement và tổng token/request. Không tính hành động reject hoặc số AU giữ làm chất lượng. R2 chỉ giữ nếu lợi ích đọc thêm đủ bù chi phí. Chưa mở Plan13 hay toàn corpus.
