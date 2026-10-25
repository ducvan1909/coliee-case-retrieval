# Tối ưu vận chuyển và điều phối: bulk → queue → corpus

Phạm vi: ba thay đổi vận hành trên app thử riêng, giữ một target/request, AU contract hiện tại, model 9B không thinking, L40S và C4. Không đổi AU definition, retrieval hay reranker.

| Bước | Triển khai | Phép thử trước khi mở rộng |
|---|---|---|
| 1 | Bulk submit và tiến độ nhóm theo cursor; host lưu receipt trước cursor | Mất ACK, completion lệch thứ tự, replay/resume, digest sai, cursor sai |
| 2 | Pending queue tách archive; manifest/receipt/checkpoint bền vững trước dispatch | C4, probe exclusive, restart running→unknown, commit failure không dispatch, không quét archive khi claim |
| 3 | Corpus manifest một lần; server điều phối cửa sổ chờ và receipt | Manifest idempotent, giới hạn payload, client ngắt, receipt khôi phục, unknown chặn admission mới |

Local implement/test trước. Sau đó chạy 30 target benchmark: bulk nhóm16 rồi corpus cùng30; không chạy lại Mốc1 436 target trong bước này. Mỗi arm dùng ID mới, không tính cache-result làm inference mới. Warmup/probe tách khỏi wall workload nhưng vẫn báo setup/usage.

Điều kiện vận hành: hoàn tất30/30, không giảm protocol/coverage, checkpoint đúng, không dispatch thêm khi outcome unknown. So HTTP overhead, throughput, tổng token kể cả run lỗi, thời gian/chi phí endpoint nếu có billing. Các thay đổi AU giữa arm cần review nguồn; hình thức PASS không chứng minh ngữ nghĩa.

Chưa có kết quả remote cho bản này. Chưa khẳng định nhanh hơn. Nếu bulk/corpus không có lợi, giữ C4 cũ; không tăng target/request để che kết quả. Chỉ mở client sang manifest436 sau kiểm tra đúng và đo lợi ích trên30.

Mã và lệnh chạy: `knowledge_base/pipeline_v1/bulk_execution/README.md`. Server và Volume tách khỏi baseline; artifact lịch sử giữ nguyên.
