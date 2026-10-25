# Primary và supporting evidence — thử nghiệm AU tự động

## Mục tiêu và bằng chứng

Đọc kế hoạch24–27, README au_target_context và `knowledge_base/pipeline_v1/outputs/evidence_first_20261016_165521_647/INSPECTION.md` (đường dẫn từ repo root). Smoke hai TARGET đạt protocol nhưng evidence-first chọn cả tập quote chưa xác định legal point; còn trộn lời đương sự, nhãn kind chưa đúng và lấy heading phần sau. Tổng workload6024 so baseline5938 token: chưa có tiết kiệm tương đương chất lượng.

Thử thay việc chọn tập quote không phân vai bằng một neo proposition chính và evidence hỗ trợ. Không mặc định một câu là toàn bộ proposition; primary chỉ là neo nhận diện, điều kiện/ngoại lệ/attribution cần thiết có thể nằm trong supporting hoặc context. Không thêm classifier, NER, verifier toàn bộ, model hoặc training. Đợt triển khai hiện tại chỉ code/local; inference/deploy và mở full32 live không tự thực hiện.

## Contract opt-in

Profile `primary_support_v1`; stage1 wire `au-target-primary-support-v1`. Bốn profile lịch sử và default baseline_v2 giữ nguyên. Top-level keys/decision/reason/needs giữ contract cũ. Anchor model trả:

```json
{
  "anchor_id": "host-slot-id",
  "kind": "holding",
  "primary_ref_id": "one-target-ref",
  "supporting_ref_ids": ["other-target-ref"],
  "needs_context": []
}
```

Model chỉ chọn ID hữu hạn, không viết claim/quote/offset. Primary bắt buộc thuộc TARGET. Supporting0–7 refs TARGET, không lặp nhau hoặc trùng primary; tổng tối đa8refs/AU. Tối đa3AU/TARGET theo fixed slot1→2→3; không ép đủ3. Không hard-filter primary dùng lại giữa các AU vì một atom có thể chứa nhiều legal point; việc có thực sự độc lập phải đánh giá ngữ nghĩa. Không silent truncate.

Grammar mã hóa slot và từng lựa chọn primary; danh sách supporting loại primary đã chọn khỏi enum. Host tiếp tục kiểm ID, trùng refs, cap và sự nhất quán; không coi grammar là kiểm chứng ngữ nghĩa. Giữ unknown/unresolved nếu không xác định được proposition hoặc thiếu điều kiện, không ép negative.

## Host và stage2

Host dựng riêng primary_evidence (một span) và supporting_evidence theo thứ tự source, đầy đủ case/hash/offset/quote. Compatibility primary_claim chỉ là nguyên văn primary, có nhãn host_extracted và representation riêng; không phải kết luận độc lập đã kiểm chứng. Compatibility target_ref_ids là union primary/supporting sắp theo nguồn, không làm mất hai vai trò. Không cap300 ký tự nguồn host dựng hoặc tự ghép thành câu liên tục giả.

Stage2 giữ wire đầu ra hiện tại, tối đa một request/TARGET khi có nhu cầu. Khóa primary và supporting, gửi mỗi quote một lần với vai trò rõ; không lặp primary_claim trong input. Context chỉ qualify/attribute primary đã khóa; không tạo primary mới, biến party argument thành holding hoặc rewrite primary. Build stage2 revalidate cả raw selection và normalized output: không tin evidence/supporting caller truyền vào. Lỗi candidate không làm mất kết quả khác; không tăng retry/budget, giữ checkpoint/resume và code/profile/payload/wire hash riêng. Source/old output không migrate thành kết quả mới.

## Thứ tự kiểm tra

1. Implementer code profile/grammar/host normalization/prompt/mock/probe adapter; Main viết kế hoạch/script; tester độc lập kiểm code cuối.
2. Local: primary/supporting foreign/context refs, duplicate, primary-in-support, cap8, empty support/catalog1ref, fixed slot, nhiềuAU, nguồn dài, condition/OR/AND nguyên văn, raw/normalized tampering, stage2 không đổi vai hoặc nhân quote, no-anchor queue và resume0request. Giữ hồi quy mọi profile cũ. Compile/decode chỉ báo đã kiểm khi có engine; kiểm chuỗi grammar/mock không thay thế endpoint.
3. Main prepare/preflight/mock32 TARGET cho evidence_first_v1 và primary_support_v1, kiểm nguồn/hash/offset, vai trò và resume. Không gọi mạng.
4. Khi người vận hành chủ động chạy: probe6ca với profile mới, rồi paired hai TARGET act-fa670aae74f627868ebb33f6/act-4cdccae84ddffa61cb7bb573 trên cùng model/packet/caps/context/concurrency. Mọi root mới; không resume workload đổi code.
5. Kiểm nguồn và semantic gate trước full32. 099980 cần giữ holding notice insufficient, tránh tách rationale hoặc heading thành rule; 013009 phân biệt current finding, reported proposition và party assertion, không mất điều kiện. Nếu cùng atom vẫn trộn nhiều nội dung thì ghi giới hạn, không coi primary_ref giải quyết chắc chắn.

## Metric và quyết định

Kiểm toàn TARGET kể cả negative/unresolved: proposition đúng/tồn tại, attribution, qualification/negation, omission, fact-only/heading, duplicate, kind và primary-support relation. KOS/model-silver là tham khảo, không human gold. Model đồng thuận không tự là gold. Giữ khi giảm nhập nhằng legal point mà không bỏ nội dung hợp lệ; nếu chỉ thêm field/tokens mà selection không tốt hơn thì bỏ/sửa, không bảo vệ thiết kế.

Đo input/output/provider tokens, requests/retry/unknown usage, stage2 và wall/server latency; tách cached results với mới, probe/setup với extraction. Probe có6 logical request riêng, phải tính vào chi phí vận hành dù không gán cho một arm; không gọi giảm token do thiếu AU hoặc dừng sớm là tiết kiệm. Byte/grammar size local không phải token thực. Chưa có dữ liệu live mới thì chưa kết luận phương pháp tốt hơn.

Script live chỉ hai TARGET mỗi arm: tối đa4 logical request/arm (2 stage1+2 stage2), cộng6 probe là tối đa14 logical request. Retry vẫn theo chính sách hiện có; không tự mở full32, không tăng concurrency/replica. Ngân sách mỗi run và riêng probe giữ giới hạn hiện hành; không dùng USD/request giả định. Chi phí setup/probe báo riêng trong comparison.json thay vì giấu khỏi dự toán.

Probe profile mới có ít nhất hai ref TARGET tổng hợp và yêu cầu support không rỗng để đi qua nhánh grammar primary/support; không chỉ test schema có một primary với support=[]. Sáu ca không chứng minh mọi invariant hoặc ngữ nghĩa; trường hợp duplicate support vẫn phải bị host chặn dù finite grammar cho phép lặp enum.

Probe báo nonempty_support_observed riêng với constraint status: support=[] là hợp schema, không tự gọi là grammar lỗi. Script paired yêu cầu ít nhất một case positive đã quan sát support không rỗng trước extraction để bảo đảm có thử nhánh mới; nếu chưa thấy thì dừng với lý do chưa đủ bằng chứng, không tự retry hoặc sửa schema.

## Bàn giao

Profile opt-in và wire rõ; tool/CLI hiện có; local tests/report; source/workload/receipts/run/cache; script `knowledge_base/pipeline_v1/experiments/run_primary_support.ps1` so evidence-first với primary-support. Default script chỉ local; -Execute mới probe/paired hai TARGET. Chưa đổi segmenter, Issue/NN, reranker hoặc mở toàn corpus. Không tự thêm vòng model khác để chữa kết quả khó.

Script prepare/preflight cả hai arm trước mọi probe/generation; preflight lỗi thì không phát sinh inference. Root input/preflight/probe/run ngang hàng đúng guard. Probe và từng arm dừng ngay khi không đạt, giữ artifact để kiểm tra, không tự tạo root mới hoặc chuyển model.

## Nghiệm thu local — 2026-10-16

Đã triển khai profile/wire riêng, grammar finite primary/support với fixed slots, host role evidence và stage2 catalog dùng chung, mock/probe và script. Tester độc lập86/86 PASS; Main local32 hai arm39/39 và6probe complete, provider0; resume/provenance/role checks đạt. Artifact `knowledge_base/pipeline_v1/outputs/primary_support_local_20261016_v1/RESULT.md`. Chưa compile XGrammar/decoder live, semantic hoặc token-efficiency claim; chưa promote hoặc mở rộng workload live.
