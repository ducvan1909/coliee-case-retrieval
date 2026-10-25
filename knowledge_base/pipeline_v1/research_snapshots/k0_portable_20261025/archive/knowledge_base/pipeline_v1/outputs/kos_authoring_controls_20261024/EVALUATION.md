# Kế hoạch39: thực thi controls — 2026-10-24

## Kết quả

- Local34test PASS, trong đó9test mới độc lập. CPU grammar cũ1job và contract cuối9job PASS; hash tokenizer/grammar/bundle và EOS được kiểm.
- Positive-only: giữ đúng grammar/source/model/caps của control cũ, chỉ thêm một JSONexample dương đầy đủ từ nguồn khác. Đã tạo1AU giữ notice/opportunity to respond trước adverse decision và exception emergency, dùng e1, không sao chép demo. Usage271input+70output=341. Main source review hỗ trợ control này, không phải chất lượng trên án thật.
- Contract cuối: 2/3 positive source có AU đúng substance, 1/3 bị bỏ. Multi-point có2AU độc lập; refund giữ điều kiệnfraud. Kind holding ở refund không có judicial provenance rõ trong nguồn giả định, chưa chứng nhận subtype.
- 3/3 negative trả rỗng phù hợp: pure facts, party-only không được tiếp nhận, citation-only.
- 3/3 uncertain nhận ra insufficient_context/needs_context nhưng đồng thời liệt kê scope trong assessed_scope_ids, trái semantic completion contract; bị host reject đúng. Không coi là3lỗi không nhận ra thiếu context, cũng không normalize để giả PASS.

## Cổng quyết định

Control cuối FAIL vì bỏ một rule rõ và lỗi kết hợp trạng thái. Dừng trước authoring bản án, ReadAssessment/validate0AU production vàK1. Module hiện triển khai controls+transport, chưa triển khai full39. K0v1 và diagnostic giữ nguyên. Không dùng quota/minItems1 để chữa omission.

## Chi phí

10POST trong cùng binding và trần12; total8173input+484output=8657token provider. Không retry, không truncation; reasoning không sinh. Tổng reserve24613 không là actualusage. Resume đọc đủ10receipt bằng opener cấm mạng:0HTTP/0POST mới. Warmup đầu Main quan sát184.687s; readiness.json được stage sau ghi đè nên không dùng file cuối để tính tổng coldstart. Runtime-info GET sau run503 nên chưa lấy được usage internal warmup; 8657 là subtotal10control request, không toàn bộ GPU/startup cost. Failed/unknown startup không được coi0chi phí.

## Điều được và chưa được chứng minh

Một exampleJSON đầy đủ giúp control cũ sinh AU hợp wire có exception. Không chứng minh hết omission: contract cuối vẫn bỏ notice. So positive-only với balanced đã đổi ví dụ, field/grammar, instruction, source rendering/wording và IDs, nên không thể quy regression cho riêng empty_reason hay thêm ví dụ âm. CPU PASS không chứng minh constrained decoding không ảnh hưởng lựa chọn. Các fixtures nhỏ không chứng minh chất lượng pháp lý/corpus.

## Hướng sửa hẹp tiếp theo, chưa thực hiện

1. Chốt lại ý nghĩa đã đọc/đã đánh giá xong: tránh yêu cầu model đếm hai trạng thái dễ mâu thuẫn; host phải giữ uncertainty nếu reason thiếu context. Cần version mới và controls lại, không sửa receipt đã sai thành đúng.
2. Đối chứng notice trên đúng source/IDs/grammar để tách một ví dụ dương với bộ ví dụ cân bằng, rồi mới thêm field; đo cả false positive chứ không chỉ tăng AUcount.
3. Chưa gọi thêm model, thêmNER, nângcap hoặc mởbảnán để bù. Hai slotPOST còn lại không tự cấp phép đổijoblist đãkhóa.
