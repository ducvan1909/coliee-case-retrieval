# Thử giới hạn độ dài tại decoder

Ngày 2026-10-20. Đợt này thử cơ chế ràng buộc, không thay phương pháp AU hoặc sửa output run A.

## Vấn đề xác nhận

Run A có 14 request hợp lệ và hai output JSON hoàn chỉnh bị host loại: limits 476 > 250 ký tự, context question 258 > 200. Grammar hiện chỉ giới hạn cấu trúc/ID, dùng chuỗi không giới hạn. Không phải lỗi 503 hay output bị cắt. Chi tiết: `outputs/au_claim_a_local_ready_20261020/live_failure_review_20261020.md`.

## Các phương án thử

| Arm | Cách làm | Diễn giải |
|---|---|---|
| host_validated | Grammar chuỗi không giới hạn như hiện tại | Đối chứng tốc độ, chủ động chấp nhận chuỗi quá dài ở decoder; host vẫn loại |
| bounded | Tách rule claim/limits/question, đếm JSON character đã giải mã với cap 500/250/200 | Ứng viên giữ đúng contract; đo hiệu năng thay vì mặc định bounded luôn chậm |
| json_schema | Native compiler với minLength/maxLength cho từng field | Đo đường chuyển đổi/tối ưu JSON Schema riêng; không suy tốc độ từ custom EBNF |
| max_chars | Rule budget nếu phiên bản XGrammar hỗ trợ | Thử tương thích; đếm ký tự văn bản JSON không mặc nhiên bằng độ dài string sau json.loads |

Không thay schema hoặc bỏ Unicode/escape chỉ để tăng tốc. Không dùng max_tokens toàn response làm cap từng field. Không tự cắt chuỗi hoặc nới host contract.

Nguồn chính thức cần đối chiếu với phiên bản thực:

- [XGrammar EBNF / rule budgets](https://xgrammar.mlc.ai/docs/latest/defining_structures/ebnf_grammar.html): giới hạn có thể nới tới điểm kết thúc hợp lệ; escape cần kiểm tra riêng.
- [Issue hiệu năng bounded strings](https://github.com/mlc-ai/xgrammar/issues/852), [tối ưu counted repetition](https://github.com/mlc-ai/xgrammar/pull/938). Không suy phiên bản có fix chỉ từ tên latest hoặc tài liệu.
- [XGrammar 0.2.8 trên PyPI](https://pypi.org/project/xgrammar/0.2.8/): một candidate có pin để đo riêng, không tự coi chứa mọi sửa lỗi hoặc tương thích SGLang hiện tại.

## Triển khai tách biệt

Module mới `knowledge_base/pipeline_v1/au_length_probe`. Không sửa `au_claim`, `.env`, endpoint/server hoặc checkpoint A. Sau khi module mới có kết quả, vẫn phải phân xử trước khi đổi production grammar.

1. Một GET cố định vào `/v1/diagnostics/json/info`, không gửi inference payload, không redirect kèm credential, không retry vô hạn. Chỉ lưu phiên bản và thông tin kỹ thuật hữu hạn. HTTP 503/không kết nối là unavailable, không suy thành phiên bản cũ.
2. Prepare local tạo grammar và tình huống, không cần XGrammar. Đây là PREPARED, không phải decoder PASS.
3. Offline thật dùng XGrammar và tokenizer đúng revision Qwen, chỉ đọc tokenizer từ model cache. Không load model weights, không gọi generate và không cần GPU. Nếu local thiếu thư viện, dùng function Modal CPU riêng với cùng image gốc và candidate pin; không deploy/thay server đang live.
4. Sau offline đúng mới chạy endpoint probe nhỏ có giới hạn để kiểm tích hợp SGLang/EOS và throughput. Chưa dùng run AU đầy đủ làm phép thử grammar đầu tiên.

## Tình huống và phép đo

- Mỗi field: sát trần, đúng trần, vượt trần, null đúng chỗ, empty không đúng chỗ.
- ASCII, Unicode non-BMP, dấu kết hợp, JSON escape, escaped quote/backslash, surrogate pair và lone surrogate.
- So nhận/chặn bằng decoder với host sau json.loads. Whitespace-only có thể qua grammar nhưng host loại; báo đúng ranh giới, không coi là bảo đảm semantic.
- Replay token thực của tokenizer và kiểm token mask, không chỉ gọi accept_string. EOS chặn trước root hoàn tất và được phép sau root, giữ cả EOS token của model/tokenizer.
- Compile time, cold/warm mask fill p50/p95, số token replay, runtime/tokenizer identity, phiên bản và trạng thái unsupported/unavailable. CPU benchmark không phải tốc độ inference trên GPU.
- Bounded phải chặn vượt cap mà vẫn nhận chuỗi hợp lệ có escape; max_chars nếu hạn chế quá mức hoặc nới vượt contract thì không chọn làm phương án tương đương.

Ngưỡng sàng lọc hiệu năng dự kiến: xem p95 mask theo token có quanh hoặc dưới 1 ms và có token bất thường trên 5 ms không. Đây là chỉ báo, không chứng minh end-to-end nhanh. Trước khi promote cần so trên endpoint cùng workload, báo compile lạnh riêng và mọi request lỗi; không chấp nhận ràng buộc đúng nhưng giảm throughput đáng kể mà chưa nêu tradeoff.

## Bàn giao và giới hạn

CLI/benchmark, bộ kiểm thử độc lập, cấu hình CPU đo riêng và báo cáo local. Không có dependency hoặc tokenizer thì phải báo unavailable; không thay bằng mock rồi gọi decoder PASS. Thư viện mới chưa qua SGLang/EOS hook thì chưa được deploy thay thế. Không tự retry/sửa hai output invalid của A trong đợt này.
