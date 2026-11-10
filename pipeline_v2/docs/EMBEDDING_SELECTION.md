# Lựa chọn embedding đã chốt

Người dùng chốt **`Qwen/Qwen3-Embedding-4B`, tự host trên Modal**. M2 đã pin revision model/tokenizer `5cf2132abc99cad020ac570b19d031efec650f2b`; chỉ tải sáu file tokenizer/config/model card công khai, chưa tải weights. Quyết định máy đọc được nằm tại `pipeline_v2/configs/embedding_selection.json`; hash/bytes và phiên bản backend ở `configs/qwen3_embedding_4b_tokenizer.lock.json`.

Nguồn chính thức: [Qwen3-Embedding-4B model card](https://huggingface.co/Qwen/Qwen3-Embedding-4B). Model card công bố context 32K và vector tối đa 2.560 chiều; ví dụ retrieval dùng instruction cho query, document không cần instruction, last-token pooling và L2 normalization. Đây là thông tin tham chiếu, chưa phải toàn bộ runtime profile đã khóa. Context tối đa của model không phải kích thước passage cần dùng; effective endpoint limit và full-input token counts vẫn phải kiểm riêng, không sao chép `truncation=True` từ ví dụ vào pipeline vốn cấm silent truncation.

## Phạm vi đã chốt và phần còn lại

- Đã chốt model family/size, tokenizer repository và nền tảng host.
- Đã pin revision và tokenizer assets; document template local là exact raw body, không instruction/prefix/chat template, có một token cuối do postprocessor chính thức thêm.
- Chưa khóa query instruction, dimensions, pooling, normalization/similarity, precision, serving engine, GPU, batch và endpoint input cap. Những lựa chọn này sẽ thành profile cụ thể khi triển khai, không tự coi là quyết định của người dùng. Serving phải tương thích tokenizer/template M2 hoặc rebuild version mới.
- Tokenizer của agent/controller chưa được chọn; khác với tokenizer embedding vừa xác định repository.
- Chưa deploy Modal, tải weights, chạy inference hoặc embedding corpus trong bước ghi nhận lựa chọn này. Lựa chọn nền tảng không thay thế việc khóa workload và cấu hình thực thi cụ thể.

## Nối vào M2 hiện có

Giữ nguyên `configs/m2.json` và các bundle navigation đã seal; bản navigation hiện hành là `artifacts/m2_navigation_20261106_v3/`. Các trạng thái tokenizer null của stage navigation được giữ nguyên, không sửa profile cũ để giả rằng artifact đã có token counts.

Phần token/chunk dùng profile riêng, tiêu thụ navigation/M1 đã khóa; xem [M2 passages](M2_PASSAGES.md) để biết cấu hình thử và kết quả kiểm thực tế. Giữ quy tắc hit child trả full parent + paragraph trước/sau. Local token-valid và endpoint/runtime-ready là hai gate khác nhau. Chưa mở M3 hoặc triển khai remote.
