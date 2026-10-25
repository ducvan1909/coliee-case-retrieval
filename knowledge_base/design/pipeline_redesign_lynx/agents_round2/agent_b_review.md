# Agent B vòng 2 — Quy mô và chi phí

## Kết luận

Kiến trúc đã chọn có lõi hợp lý: raw source luôn khả dụng, enrichment mặc định tắt, worker có fingerprint, và LLM chỉ chạy sau retrieval. Tôi steelman rằng đây là thiết kế kiểm soát rủi ro tốt hơn V13–V15: nó có thể dừng ở R0/R1 nếu các lớp đắt không tạo giá trị. Tuy nhiên, hiện chưa thể kết luận pipeline chạy được ở quy mô corpus hoặc các arm so sánh công bằng, vì năm hợp đồng dưới đây chưa được khóa.

### 1. Cap LLM không có mẫu số ổn định

**Claim →** R3 dùng 0/1/5/10% `candidate chars`, đồng thời cap case, ký tự, token và request. **Counterexample →** Candidate pool, thứ tự ưu tiên và context mở có thể khác giữa arm; cùng 5% không còn là cùng workload. Retry còn tiêu token nhưng không tăng candidate chars. **Consequence →** Đường routing có thể phản ánh thay đổi mẫu thay vì lợi ích biên của LLM. **Exact fix →** Tạo một route manifest bất biến từ R3-0; xếp hạng ổn định và tạo các tập lồng nhau 1% ⊂ 5% ⊂ 10%. Khóa bốn hard cap; dừng khi cap đầu tiên chạm và ghi phần chưa xử lý. **Deciding test →** Replay mọi arm trên cùng manifest; checksum candidate/order phải giống nhau, rồi so paired quality và tổng usage.

### 2. Local compute chưa có gate định lượng

**Claim →** Model local chỉ chạy toàn corpus sau throughput gate. **Counterexample →** Kế hoạch yêu cầu đo án/giờ, VRAM và OOM nhưng không nêu ngưỡng pass; RAM máy còn chưa biết. **Consequence →** Bất kỳ benchmark nào cũng có thể được diễn giải là “đủ”. **Exact fix →** Trước run, khóa tối đa GPU/CPU giờ, peak RAM/VRAM, OOM/fallback rate, p95 latency, dung lượng index và thời gian full/incremental rebuild. **Deciding test →** Benchmark ba dải độ dài trên development; bootstrap dự toán 9.556 án và bác R2 nếu upper bound vượt bất kỳ gate nào.

### 3. Candidate budget cố định chưa bảo đảm compute tương đương

**Claim →** Mọi arm giữ tổng candidate budget cố định. **Counterexample →** Một case có thể tạo nhiều hit/annotation hơn; dedup, fusion và context expansion làm số span, ký tự và model calls khác nhau dù số case bằng nhau. **Consequence →** Recall gain có thể được mua bằng compute ẩn. **Exact fix →** Khóa đồng thời case-K, hit-K trước dedup, unique source chars, context chars, calls và wall-clock; báo chất lượng theo từng frontier ngân sách. **Deciding test →** So R0–R3 tại các frontier giống hệt nhau; arm chỉ thắng nếu Pareto-improve hoặc đạt non-inferiority đã đăng ký.

### 4. Cache/retry làm sai cold–warm comparability

**Claim →** Fingerprint, retry và cold/warm reporting đủ cho cost accounting. **Counterexample →** Chưa quy định cache hit gánh build cost thế nào, failed attempt không có usage được tính ra sao, hoặc retry chạm cap có được dispatch. **Consequence →** Warm arm và arm nhiều lỗi có thể trông rẻ giả. **Exact fix →** Ledger tách actual usage, logical request, transport attempt, cache provenance và amortized originating cost; pre-dispatch reserve phải nằm trong cap, rồi reconcile bằng usage thực. **Deciding test →** Fault-injection 429/503/timeout/empty và chạy lại cold/warm/resume; tổng charged cost phải bảo toàn và không double-apply.

### 5. Update cost chưa mô hình hóa dependency closure

**Claim →** Đo update 1%/10% và chỉ rebuild output phụ thuộc. **Counterexample →** Source, segmentation, model, prompt và fusion thay đổi có fan-out rất khác; tỷ lệ file đổi không cho biết số index/record bị invalid. **Consequence →** Dự toán lifecycle có thể thấp hơn nhiều so với vận hành thật. **Exact fix →** Lập mutation matrix và ghi dirty closure theo artifact; báo touched cases, records, bytes, compute và downtime. **Deciding test →** Với từng mutation 1%/10%, so incremental với full rebuild: output không bẩn phải giữ checksum, output bẩn phải khớp full rebuild.

## Tự phê bình

Review này ưu tiên khả năng bác bỏ và có thể làm pilot chậm hơn; một số gate ban đầu sẽ là quyết định vận hành chứ chưa có dữ liệu. Vì vậy gate phải đăng ký trước nhưng được phép sửa sau một pilot riêng, không hồi tố kết luận holdout.
