# Sửa các giới hạn M3 optimization sau review AG

Đây là revision mới dưới `optimization_v2/`, `m3_opt_v2.py`, `configs/m3_opt_v2.json`, `deployments/modal_opt_v2/`. Giữ nguyên code/config/run baseline và optimization v1 để truy vết benchmark đã hoàn thành. Codex triển khai và kiểm local; AG chỉ review/test và thực thi các lệnh người dùng chủ động giao. Codex không gọi Modal ở bước sửa này.

## Phạm vi sửa

- SQLite metadata chỉ giữ ID/hash/offset/refs, không lưu raw text. Postings tạo theo từng tài liệu/batch thay vì gom mọi frequencies trong RAM. Metadata top hits được lấy gộp, không một truy vấn/JSON toàn văn cho từng hit. Đường dẫn tương đối được resolve trước readonly URI.
- Session không nạp toàn bộ passage metadata hoặc scan norm/finite của mọi vector khi khởi tạo. Vector mmap tra theo hàng cần thiết; metadata tra theo hit IDs. Full norm/finite/completeness audit thuộc verify.
- Full content hash/index/source/provenance kiểm ở mở session và explicit verify; query tiếp theo dùng snapshot bất biến đã được kiểm, không hash lại nhiều GB. Khi mở evidence, raw case phải khớp hash đã khóa. Nếu nguồn/index có thể thay đổi giữa session, phải invalidate/reopen hoặc verify; không coi timestamp là chứng nhận toàn vẹn, cũng không hứa tự phát hiện mọi concurrent mutation ngay tại ranking. File vectors/index vẫn cần đọc toàn bộ để hash một lần khi mở session; mmap không làm mất chi phí đó.
- Một app mới cho documents và queries, vẫn cùng Qwen/revision/tokenizer/BF16/2560/L2, L4. App cũ trước đây là lựa chọn có chủ đích để giữ đúng fingerprint vector baseline, không phải dùng nhầm model. App mới chỉ được search trên vectors baseline sau compatibility preflight thật kiểm cả document và query vectors, token/input hashes/code/package fingerprints; simulated tests không mở khóa thực.
- Benchmark mới dùng4nhóm độ dài, mỗi nhóm64passages liền nhau trong phần sorted tương ứng, tổng256IDs duy nhất. So sizes16/32/64 trên cùng nhóm/inputs,3warmrepeats với thứ tự crossover seeded. Stress longest448token có16/32/64/128 riêng; stress128 không được coi là throughput measurement hoặc làm mất kết quả sizes nhỏ hơn hợp lệ. Báo token ranges/padding theo từng nhóm; chưa nhận một mẫu256 là đại diện tuyệt đối cho full distribution.
- Tốc độ báo riêng session open, local retrieval, query RPC và full CLI; cold scheduling/model load tách khỏi warm throughput. Winner là fastest observed trong phép đo đã kiểm parity/VRAM, không khẳng định tối ưu full.

## Chưa làm theo kế hoạch

Chưa triển khai/chạy full-corpus runner, chưa đánh giá gold COLIEE hoặc M4 agent. Đây là scope chủ ý sau pilot, không sửa bằng cách bỏ guard `pilot_only`. Batch32 chỉ là mốc tham chiếu từ benchmarkv1; không đổi số này thành kết quả benchmarkv2 khi chưa chạy.

## Nghiệm thu và lệnh

Code đã freeze tại aggregate `e2e554dd44bbd99ab93b61ca893094fe9dd47e0cd8604e5898e8b169bf931cf3`. Index mới: `pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1/`, dựng local 63,43 giây theo timer CLI sau argument parse, không inference. Không dùng CLI v1 với profile/index v2 hoặc sửa seals artifact cũ.

- 18/18 kiểm thử độc lập synthetic/mock PASS. Audit thực tế: 916 case metadata, 1.024 passages, source hashes/offsets/seal và vector finite/norm PASS; vectors bằng chính xác từng shard baseline. Sáu phép kiểm BM25 hai kênh so oracle riêng đều PASS.
- SQLite từ 138.936.320 xuống 93.270.016 bytes, giảm 32,87%. Metadata không giữ raw text; không suy mức giảm này thành mức giảm RAM hoặc latency chưa đo.
- Mẫu benchmark mới có 33.801 input tokens mỗi lượt. Padding ratio 16/32/64 lần lượt 1,028/1,056/1,121. Bias padding đã giảm nhưng vẫn phải báo từng batch size; chưa có GPU benchmark V2 để chốt winner.
- Hash code/profile baseline và optimization V1 không đổi. Evidence: `reviews/m3_opt_v2_validation_v1/local_acceptance.json` và `real_index_audit.json`.
- Đã thử `verify --full-db` local một lần nhưng nhận `ConnectionError`; chưa chứng nhận DB hiện tại. AG cần đảm bảo Docker Qdrant đang chạy rồi kiểm lại, không reset collection.
- Chưa gọi Modal, chưa deploy app V2, chưa chạy real compatibility/GPU/search. Index local PASS không mở khóa real search: cần compatibility PASS thật trước.

Lệnh chạy và phạm vi review trong [AG_M3_OPT_V2_TEST_PROMPT.md](AG_M3_OPT_V2_TEST_PROMPT.md). App mới là `coliee-pipeline-v2-embed-m3-opt-v2`. Preflight gọi app baseline để đối chiếu query một lần; sau đó query/document dùng app V2. Giữ nguyên app/index/benchmarks V1.

## Cập nhật sau AG chạy thực tế

Các trạng thái chưa chạy ở trên là checkpoint trước bàn giao. AG đã hoàn tất verify full DB, deploy, real preflight, GPU benchmark và search measurements; Main đã đối chiếu artifact và SQLite ledgers local. [Nghiệm thu của Main](../reviews/m3_opt_v2_validation_v1/AG_REVIEW_ACCEPTANCE.md), [báo cáo AG](../reviews/m3_opt_v2_ag_review_v1/REPORT.md).

Pilot được chấp nhận:104 requests thành công /414.374 input tokens, không lỗi inference hoặc unknown usage. Batch64 đạt23,00 docs/s, hơn32 khoảng5,26% và đứng đầu cả3vòng; chỉ là fastest observed trên mẫu pilot. Retrieval local mean0,208s; standalone CLI6,34–6,59s, không gộp hai ranh giới này để tuyên bố tăng tốc toàn trình. Reserved VRAM warm chịu ảnh hưởng cache pool sau stress128, không phải phép đo bộ nhớ cô lập cho từng size.

Không cần sửa production hoặc chạy lại pilot vì finding memory này. Giữ kết quả làm regression; full runner và đánh giá COLIEE vẫn chưa triển khai theo scope.
