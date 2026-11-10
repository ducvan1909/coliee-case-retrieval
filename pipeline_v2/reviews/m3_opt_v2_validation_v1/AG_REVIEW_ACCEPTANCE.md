# Main nghiệm thu kết quả AG — M3 optimization V2

Ngày 08/11/2026. Đọc artifacts/reports/ledgers local, không gọi Modal hoặc chạy lại inference. Code aggregate hiện tại vẫn là `e2e554dd44bbd99ab93b61ca893094fe9dd47e0cd8604e5898e8b169bf931cf3`.

Chấp nhận kết quả pilot: compatibility thật PASS, GPU benchmark completed_with_limits, search components/walltime đã đo. AG ghi nhận full DB verify PASS sau khi khởi động lại Docker; lỗi ConnectionError trước đó được giữ trong commands_and_results.json. Kết quả test local trước của Main và test/audit độc lập bổ sung của AG không phải bằng chứng chất lượng pháp lý.

Main đọc trực tiếp SQLite ledgers bằng readonly URI: preflight 9 requests / 1.856 tokens; GPU 89 / 412.295; query runtime 6 / 223. Tổng 104 requests / 414.374 input tokens, 0 failed, 0 unknown token attempts. Không tính lỗi chat API/khởi động Docker thành inference tokens.

Main tính lại throughput từ warm_calls: batch16/32/64 lần lượt 17,1696 / 21,8514 / 23,0018 docs/s, mỗi size đủ768 encodings. Batch64 hơn32 khoảng5,26%; throughput từng vòng của64 là22,587 /23,326 /23,105, cao hơn32 trong cả ba vòng. Chấp nhận64 là fastest observed trên mẫu này, chưa phải tối ưu toàn corpus hoặc chứng minh ý nghĩa thống kê. Max cosine deviation0,000885 vẫn trong ngưỡng0,001.

Main tính lại 9 lượt retrieval local: mean0,20801s, min0,17367s, max0,26435s. Đây là vector-reuse retrieval, không bao gồm query RPC. Standalone CLI được AG đo6,34–6,59s; không kết luận toàn pipeline nhanh5,2x hoặc tốt hơn mọi CLI V1 từ số local này. Trước khi tối ưu thêm, giữ riêng chi phí RPC/SDK khởi tạo/session và retrieval.

Lưu ý diễn giải finding memory: reserved20,56GB sau stress128 là trạng thái allocator thật của container tại thời điểm đo. Stress16/32/64 trước đó cho số đo trước stress128, không phải phép đo từng size trong process/container cô lập. Không sửa production để empty_cache mỗi request chỉ nhằm làm bảng số đẹp hơn; việc đó có thể đổi throughput. Nếu cần so reserved riêng từng size, thiết kế phép đo riêng ở giai đoạn sau.

Không yêu cầu chạy lại pilot hoặc sửa production lúc này. Giữ nguyên artifacts đã chốt. Bước kế tiếp là thiết kế/triển khai full-corpus runner có token-length batching, checkpoint/resume/cache và DB verification trước khi giao AG chạy; giữ pilot làm regression. Chưa có runner full hoặc COLIEE F1, nên chưa nghiệm thu toàn M3/full readiness.
