# Sửa chọn AU và evidence — Plan 10

Phạm vi: sửa prompt/few-shot, định danh cache và chuẩn bị hồ sơ kiểm tra từ nguồn. Không sửa server, transport, schema, model hoặc nguồn/gold. Đã thử endpoint trên ba target phát triển; có một target đối chứng suy ra từ nguồn, lưu manifest riêng.

## Cập nhật 2026-10-11: chốt baseline v4

Prompt `au-compact-semantic-v4` kiểm tra legal proposition trước khi gán `fact_only`, giữ conditional duty và holding áp dụng cho vụ án, yêu cầu TARGET đóng góp thực sự vào claim. Bốn ví dụ tổng hợp gồm positive, fact-only có authority trong CONTEXT và unresolved. Nội dung prompt cố định giảm từ 5.543 xuống 5.136 byte; đây không phải số token provider.

Manifest mới `manifests/au_compact_semantic_balanced_dev3.v1.json` giữ hai target cũ (011904, 013948) và thêm đối chứng đoạn [44] của 013948. Nguồn/hash/atom không đổi; đối chứng không phải gold. Lượt thực tế lưu tại `outputs/au_semantic_v4_dev3_20261011`:

- 3/3 request hoàn tất giao thức, sinh 5 AU. Không có lỗi cắt output trong lượt này.
- Holding ở TARGET [34] của 011904 được nguồn hỗ trợ, nhưng còn tham chiếu ngược “abovementioned documents”.
- 013948 vẫn lấy quy tắc từ CONTEXT [40]/[43], gắn TARGET làm evidence đệm; duty có điều kiện ở [41] chưa được thể hiện đúng. Đối chứng fact-only [44] vẫn bị positive.
- 7.669 token extraction; tổng usage provider biết được là 7.785 token, gồm warmup thành công và schema probe. Warmup có 9 HTTP 503 không báo usage; không suy chi phí bằng tiền hay coi các lỗi này bằng 0 tài nguyên.

Kết luận: **cổng ngữ nghĩa chưa đạt**. Không tiếp tục tối ưu riêng 9B trong đợt này; khóa kết quả để so model sau. Main review và review packet chứa evidence nguồn, không phải human gold. Cùng target 013948 dùng v3 là hard-negative bỏ sót; v4 positive nhưng sai ownership, vì vậy chưa có bằng chứng chất lượng tương đương hoặc tiết kiệm token.

Đã bắt đầu Kế hoạch 11 bằng `au_candidate_store`: xác minh nguồn/evidence, ownership cấu trúc, dedup và audit. Ưu tiên tiếp theo là phép thử ContextHint theo lựa chọn người dùng, sau khi xác minh hint thực sự đi vào request. Manifest baseline lịch sử thiếu hint payload; build hiện tại có hint thật nhưng compact chưa truyền nội dung. Readiness report đã chọn bốn target thật; chưa chạy phép thử tác dụng hint.

## Quyết định

- AU là legal proposition hoặc holding có giá trị làm authority. Không ép mọi AU phải là quy tắc phổ quát: holding áp dụng luật cho tình tiết có thể hợp lệ nếu là kết luận pháp lý thực sự của tòa. Việc kể lại tình tiết, lịch sử tố tụng hoặc lời đương sự đơn thuần không đủ.
- TARGET phải đóng góp thực sự vào legal proposition. CONTEXT được dùng để giữ điều kiện, speaker hoặc phản hồi; không lấy AU hoàn toàn từ CONTEXT rồi gắn TARGET không liên quan.
- Mỗi claim phải được evidence đã chọn chứng minh; không thêm ID chỉ để thỏa grammar. Nhãn speaker/attribution không được suy từ danh tính party hoặc giả định người kể luôn là tòa.
- Không ép ba AU: trả các proposition khác nhau, tối đa ba theo contract hiện có. Không lặp cùng claim hoặc chia tình tiết thành nhiều AU để đạt số lượng.
- Thiếu điều kiện/evidence hoặc không rõ attribution thì giữ uncertainty/unresolved theo contract. Không khẳng định complete khi không đủ evidence trong giới hạn ba atom.
- Few-shot là tình huống tổng hợp độc lập, không lấy câu trả lời từ KOS/gold hoặc target pilot. Schema/EBNF chỉ kiểm tra cấu trúc, không chứng minh các quy tắc ngữ nghĩa này được tuân thủ.

## Kiểm tra ngữ nghĩa

`review_packet.py` tạo JSON offline chứa toàn bộ atom đã gửi, TARGET/CONTEXT, quote và offset từ source/hash đã kiểm tra, từng AU cùng evidence được chọn. Verdict ban đầu luôn `pending`; không tự chuyển protocol_verified thành semantic accepted. Kiểm tra cả target không có AU để phát hiện bỏ sót.

Reviewer (agent hoặc người kiểm tra) cần ghi verdict cho từng AU, chỉ rõ atom chứng minh/phản chứng và lý do: đủ điều kiện authority; claim được evidence hỗ trợ; TARGET đóng góp đúng; attribution đúng; không mất điều kiện/ngoại lệ; không trùng. Output agent là review, không phải human gold. Việc claim dùng từ giống nguồn không tự chứng minh entailment.

Lỗi hồi quy đã quan sát ở 013948: claim về đoạn `[45]` lại dẫn atom `[41]/[42]/[44]`; claim mô tả không nộp chứng cứ bị gắn nhãn authority mà chưa giải thích proposition pháp lý. Phải kiểm tra lại sau chạy, không cố định câu trả lời cho target này trong prompt.

## Lệnh thử v3 trước đây — giữ để truy vết

Không cần deploy lại vì server không đổi. Dùng output root mới để không tái sử dụng response prompt cũ. Run tự warmup/probe. Chỉ thử target 013948 trước, giữ chế độ grammar nhẹ để không đổi nhiều biến.

```powershell
Set-Location G:\Git\coliee-case-retrieval
$run = "knowledge_base\pipeline_v1\outputs\au_semantic_$(Get-Date -Format yyyyMMdd_HHmmss)"

.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact run `
  --execute --transport jobs --string-decoder host_validated `
  --manifest knowledge_base\pipeline_v1\manifests\au_compact_pilot_r5_model_silver.v1.json `
  --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
  --request-id auo-885151f935ef8056f35cf5bc --output-root $run

if (Test-Path "$run\run.json") {
  .\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact.review_packet `
    --run "$run\run.json" --output "$run\semantic_review_packet.json"
}
```

Sau protocol complete, đánh giá AU và omission từ packet trước khi mở rộng sang các target còn lại. Không tự coi hard_negative là thành công tiết kiệm nếu đã bỏ sót legal proposition.

Prompt/few-shot làm tăng input; phải đo provider usage, token output, latency và AU đúng/sai/bỏ sót so với cùng target dùng prompt cũ. Không giả định prompt tốt hơn sẽ tự giảm token. Preflight nguồn không thay thế runtime reservation của prompt đầy đủ. Chỉ đánh giá hiệu quả khi chất lượng ngữ nghĩa tương ứng, không dùng số AU nhiều hơn làm thước đo tốt hơn.
