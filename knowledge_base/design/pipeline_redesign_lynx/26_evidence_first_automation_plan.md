# Evidence-first và lộ trình tự động hóa AU

## Điểm xuất phát

Đọc cùng kế hoạch24, kế hoạch25, README `knowledge_base/pipeline_v1/au_target_context/` và `outputs/incremental_step1_20261014_223122/INSPECTION.md`. Hai TARGET smoke đã chạy đủ giao thức nhưng còn sai nguồn phát biểu, điều kiện OR/AND và tách factual rationale thành holding. Không promote attribution_v1; token giảm không chứng minh hiệu quả khi chất lượng khác nhau.

Mục tiêu: pipeline tự xử lý nguồn, chọn AU, mở context có giới hạn và lưu bất định; không cần duyệt từng AU trong luồng vận hành. Tự động chạy không đồng nghĩa tự chứng minh đúng pháp lý. KOS/model-silver là tham khảo. Đợt triển khai này chỉ local, không inference/deploy, không mở corpus hoặc thay model.

## Bước1 — Tách lựa chọn evidence khỏi diễn giải (triển khai hiện tại)

Thêm profile opt-in `evidence_first_v1`, giữ default và ba profile cũ. Dùng cùng TARGET, catalog, model9B, cap800, giới hạn tối đa3 AU và8 refs/AU. Đối chứng baseline_v2 so với evidence-first là thay đổi phương pháp, không phải ablation một câu prompt.

- Host gửi TARGET-only với các ref có sẵn; model chọn anchor ID, kind, target_ref_ids, needs_context, decision và reason hữu hạn. Model không viết primary_claim trong wire stage1 mới.
- Host xác minh ID, giữ mỗi evidence span nguyên văn với source/hash/offset, sắp theo nguồn. Nhiều span không liền nhau phải thể hiện khoảng bị bỏ; không nối thành một câu giả nguyên văn.
- Biểu diễn chính là evidence trích xuất; nếu downstream còn dùng tên primary_claim thì gắn nguồn tạo host và kiểu extractive, không gọi đó là claim pháp lý đã kiểm chứng. Không cắt nguồn cho vừa giới hạn300 ký tự vốn dành cho model viết claim.
- Giữ nhiều AU/TARGET; rationale thuộc cùng legal point thì cùng evidence của AU, nhưng không ép một AU/TARGET hoặc loại holding cụ thể vì thiếu abstract rule.
- Stage2 vẫn tối đa một request/TARGET, khóa các neo/evidence đã chọn. Context chỉ bổ sung/kiểm tra; không tạo proposition chính mới. Không thêm request diễn giải hoặc verifier toàn bộ.
- Với evidence-first, payload stage2 gửi các quote evidence một lần; không lặp nguyên văn dài lần nữa trong trường compatibility primary_claim. Output host vẫn lưu biểu diễn đầy đủ. Phải đo input stage2 thật; bỏ claim sinh ra không mặc nhiên giảm tổng token.
- Version wire stage1 mới, profile/prompt/code/payload hash riêng; không reuse nhầm receipt. Giữ cache/resume, budget và checkpoint hiện có.

Đây là giảm bề mặt sinh diễn giải, chưa giải quyết chắc chắn việc chọn sai evidence, attribution ngầm hoặc omission. Atom quá rộng và quotation trải qua nhiều atom vẫn cần đo.

Local gate: profile cũ giữ nguyên; từ chối claim do model tự thêm, context/foreign IDs, ref trùng; giữ nguyên văn dài hơn300 ký tự; nhiều AU, negative, unresolved, gap, stage2 và resume không gọi lại. Prepare/preflight/mock32 TARGET, inference0. Mock không chứng minh decoder endpoint hoặc ngữ nghĩa.

## Bước2 — Đối chứng thật trước khi thêm logic (chưa chạy)

Người vận hành chạy hai TARGET `act-fa670aae74f627868ebb33f6` và `act-4cdccae84ddffa61cb7bb573`, baseline và evidence-first ở root mới, cùng giới hạn/model/context. Không chép ví dụ calibration vào prompt. Sau smoke kiểm source/evidence và lỗi ngữ nghĩa nghiêm trọng trước khi mở32 TARGET; protocol PASS riêng không mở khóa. Dùng32 để tìm lỗi phương pháp, không tuyên bố tổng quát.

Đánh giá toàn TARGET, kể cả negative/unresolved: proposition được chọn có đủ; lời trích/lời đương sự có bị nhận nhầm; điều kiện/ngoại lệ/phủ định có nguyên vẹn; fact-only và duplicate AU; AU hợp lệ bị bỏ. Evidence exact không tự chứng minh eligibility. So sánh theo evidence/legal point, không yêu cầu claim text của hai arm giống nhau.

Giữ khi giảm lỗi diễn giải mà không tăng omission hoặc sai tư cách AU đáng kể; báo số lỗi từng loại và bất đồng thay vì một điểm tự động duy nhất. Nếu chỉ giữ được nguyên văn nhưng chọn sai, không gọi là đạt. Báo total input/output/provider tokens, retry, stage2, unknown usage, latency và unresolved; phần source host dựng không tính là model output nhưng nếu gửi stage2 phải tính lại vào input. Không khẳng định tiết kiệm trước đo.

## Bước3 — Chuyển tuyến tự động theo rủi ro (sau bước2)

Chỉ bổ sung nếu còn lỗi attribution/context đáng kể. Thử riêng tín hiệu literal có offsets: reporting phrase, quotation seam hoặc dependency thiếu. Host có thể yêu cầu context dù model không tự báo; cue là cảnh báo, không tự suy speaker hoặc loại AU. Giữ trần một stage2/TARGET và ngân sách tổng; không thêm vòng vô hạn. So với cùng evidence-first không có routing, không đồng thời thay TARGET/model.

Kết quả provisional/rejected/unresolved; unresolved là trạng thái vận hành hợp lệ, không âm thầm negative hoặc accepted. Khi thiếu context ngoài catalog, ghi nhu cầu và dừng; tự tìm xa cần đặc tả/đối chứng riêng. Kiểm tra cả no-anchor và negative để tránh bỏ sót bị che khỏi thống kê.

## Bước4 — Kiểm tra tự động và mở rộng

Host kiểm cấu trúc/provenance mọi kết quả. Kiểm tra ngữ nghĩa bằng model chỉ lấy mẫu phân tầng positive/negative/unresolved và ca rủi ro, trong ngân sách riêng; không biến model đồng thuận thành gold, không verifier toàn corpus mặc định. Báo tỷ lệ chuyển tuyến/unresolved và lỗi kiểm được trên mẫu; giữ disputed. Chưa có đánh giá độc lập thì kết luận giới hạn ở calibration/model-assisted.

Sau khi chốt cấu hình mới chạy phủ năm án, đối chiếu KOS cùng nguồn/evidence và chi phí, rồi mới thiết kế mở rộng. Không thay reranker, Issue joining hoặc triển khai NN trong kế hoạch này.

## Bàn giao và điểm dừng

Profile selection-only chạy qua CLI hiện có; wire/version và host representation rõ; test độc lập; workload/preflight/mock/resume và packet evidence để kiểm nguồn; lệnh live riêng. Mỗi bước phải có quyết định giữ/sửa/bỏ dựa trên metric. Bước1 triển khai local không tự mở khóa tuyên bố ngữ nghĩa hoặc toàn corpus.

Script `knowledge_base/pipeline_v1/experiments/run_evidence_first.ps1` mặc định prepare/preflight/mock32 TARGET cho cả baseline_v2 và evidence_first_v1, xuất comparison.json chỉ về giao thức/chi phí. Thêm `-Execute` mới gọi endpoint, chỉ hai TARGET smoke mỗi arm. Script dừng nếu arm lỗi, không tự retry bằng root mới hoặc tự mở full32. Readiness/checkpoint do runner hiện có xử lý. Resume bằng CLI với workload/run root đã lưu, giữ đúng concurrency và selection.

## Nghiệm thu bước1 — 2026-10-15

Smoke live sau nghiệm thu local gặp lỗi anchor slot order: grammar cũ cho phép đảo ID trong khi validator cấm. Xem [kế hoạch27](27_anchor_slot_grammar_fix_plan.md) để sửa giao thức và probe endpoint trước khi tiếp tục đối chứng. Không coi test local trước đó là xác nhận decoder live.

- Đã có profile/wire selection-only riêng, host extraction có gaps/provenance và stage2 không lặp quote trong compatibility field. Default/historical prompts giữ nguyên; .env và deployment không đổi.
- Tester độc lập:61/61 test PASS (52 hồi quy +9 mới). Report `outputs/au_evidence_first_test_report.md`.
- Main prepare/preflight/mock32 TARGET mỗi arm:39/39 verified, provider0; resume ledger không đổi, primary refs kiểm khớp source, cả7 EF stage2 payload không lặp primary_claim. Artifact `knowledge_base/pipeline_v1/outputs/evidence_first_local_20261015_v1/RESULT.md`.
- Chưa live decoder/semantic validation, chưa triển khai bước3/4. Bước tiếp theo là đối chứng hai TARGET theo bước2, không promote dựa vào test PASS.
