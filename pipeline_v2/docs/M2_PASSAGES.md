# M2 — Passage theo token và mapping đọc nguồn

Phần này bổ sung cho navigation v3, không sửa bundle navigation/M1 hoặc dữ liệu gốc. Chỉ xử lý local corpus train đã khóa; không đọc nhãn để tạo passage, không tạo vector, index, gọi inference hoặc deploy Modal.

## Profile và tokenizer

- Model/tokenizer: `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`.
- Lock: `pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json`; có hash/bytes sáu file công khai, version `tokenizers==0.22.2`. Không có trọng số hay remote code.
- Backend tokenizer chính thức có postprocessor thêm **một `<|endoftext|>` (151643)** sau tài liệu. Đếm full input với `add_special_tokens=True`, không padding/truncation. Không tự thay bằng `eos_token` trong metadata hoặc áp chat template.
- Document là exact raw body; không instruction/heading prefix. [Model card chính thức](https://huggingface.co/Qwen/Qwen3-Embedding-4B/blob/5cf2132abc99cad020ac570b19d031efec650f2b/README.md) dùng document không instruction. Query instruction và serving profile thuộc bước sau.
- Profile thử: target mềm320, overlap mong muốn128, trần448 **tính cả special token**. Giữ nguyên parent <=448; chỉ tách parent quá dài. Không ép ghép parent ngắn, không loại unknown/quoted/French/placeholder-only.
- Đây là variant overlap trong cùng parent; không phải baseline không overlap của đề xuất ban đầu. Chưa có bằng chứng overlap128 cải thiện retrieval. Không đếm overlap thành phiếu hoặc evidence độc lập.

Token offsets chỉ đề xuất điểm cắt. Mỗi raw substring phải encode lại độc lập để xác minh cap; không lấy decode token IDs làm văn bản nguồn. Ưu tiên whitespace; fallback theo Unicode codepoint cho chuỗi dài, ghi rõ biên chưa xác minh câu/ngữ nghĩa. Source spans hợp nhau phải phủ toàn parent, kể cả whitespace. Overlap thực tế được đo riêng, không tuyên bố luôn đúng128.

## Mapping và phạm vi coverage

Mỗi passage có source hash, byte/char spans, raw text/hash, tokenizer/profile fingerprint, parent/handle, split order, sibling refs và reading expansion. Hit ở một child mở toàn parent + paragraph trước/sau theo source order; không tính số marker cộng/trừ1. Không dùng quotation/language chưa xác minh làm bộ lọc.

Coverage passage lấy toàn bộ navigation units (paragraph và unnumbered), kể cả unit không preview. Heading và whitespace riêng của partition vẫn nằm trong nguồn/M1/navigation refs, không thành embeddings độc lập trong profile này. Không gọi coverage navigation là toàn bộ raw bytes đã được embedding. Full raw context vẫn mở được; `open` là diagnostic local, không ghi nhận agent đã nhận/đọc payload.

## Readiness và giới hạn

`token_validated_chunks` chỉ ready sau kiểm bundle thực tế. `embedding_input` là view local đã đo token, không phải endpoint-ready. Model card công bố32K; config kiến trúc40960, tokenizer metadata131072 là các trường khác nhau, không tự dùng giá trị lớn nhất. Endpoint Modal chưa có; trước inference phải kiểm lại model revision, tokenizer, special tokens/template và effective endpoint cap. Không truncate ngầm nếu serving khác profile.

Tokenizer agent, budget phân trang/giao context và ledger requested/delivered/pending còn thuộc M4. Không dùng tokenizer embedding để khẳng định payload vừa context của agent. Ownership, speaker và noticed relation chưa được xác minh bởi kiểm token/provenance.

## Tái hiện

Chạy `.venv/Scripts/python.exe -m pipeline_v2.m2_passages --help` để xem CLI build/validate/inspect/open. Mỗi build vào thư mục mới dưới `pipeline_v2/artifacts/`; không ghi đè bundle đã seal. Đầu vào navigation hiện hành: `pipeline_v2/artifacts/m2_navigation_20261106_v3/`.

Các receipts tải tokenizer: `pipeline_v2/reviews/m2_tokenizer_acquisition_v1.json` giữ lần gate dừng vì postprocessor chưa được review; sáu HTTP download đều thành công. `m2_tokenizer_acquisition_v2.json` xác minh hash local và hoàn tất lock sau khi review processor. Trước đó có một lần metadata request bị proxy sandbox từ chối, một lần metadata request được phép thành công. Không có inference requests/tokens; token của chat phát triển không đo được.

## Build và mapping thực tế

Bundle mới: `pipeline_v2/artifacts/m2_passages_20261106_v1/`. Build exit0,921,598s local (wrapper921,792s), receipt `artifacts/m2_passages_20261106_v1.build-receipt.json`. Có **7.708 nguồn,382.343 parents,415.693 passages**,9.856parents bị tách. Tổng full-input token đếm local55.346.360, trong đó token overlap content thực đo4.244.972; đây không phải inference tokens đã tiêu thụ. Maximum448,37passages đúng448; không có end boundary bị cắt giữa từ trong corpus này theo flag cơ học, không suy đó là biên câu đúng ngữ nghĩa.

Kiểm mở middle child đã PASS sau seal: parent `041666/p000417` dài84.205bytes được tách110children; child giữa mở toàn parent + `p000416`, ghi đúng không có next vì cuối nguồn. Một child giữa của parent `p000153` mở `p000151 → p000153 → p000155`, minh họa hàng xóm theo nguồn thay vì số cộng/trừ. Raw envelope khớp bytes, hit tách khỏi context; không ghi M4 delivery. Evidence: `reviews/m2_passages_validation_v1/middle_child_result.json`.

Audit độc lập raw/token toàn corpus **PASS,0lỗi,450,474s**; xác nhận lại counts/tokens phía trên, không gaps/orphan passage hay lệch raw/hash/mapping. Heading riêng48.990units/481.721bytes và whitespace514.659units/1.540.929bytes được báo đúng là không embedded standalone, vẫn giữ source access. Kết quả: `reviews/m2_passages_validation_v1/full_corpus_audit.json`.

**Nghiệm thu cuối: M2 passages local hoàn tất với giới hạn đã ghi.** Validator tái dựng **PASS trên7.708nguồn,947,305s local** (wrapper947,560s), counts khớp build/audit. Receipt: `reviews/m2_passages_validation_v1/validator_receipt.json`; không đổi code/profile sau freeze. Bộ kiểm thử65/65PASS, targeted độc lập9/9PASS; chi tiết trong báo cáo kiểm thử. Bundle cuối duy nhất của bước này: `artifacts/m2_passages_20261106_v1/` (7.711sealed entries + seal=7.712files,938.891.921bytes).

Chunk/embedding-input manifests được lưu theo case trong `sources/*.json` (passage ID, raw body/hash, exact input hash, full token count, tokenizer/profile fingerprint, parent/sibling/context refs), với `source_registry.json` và root `manifest.json`; không cần thêm một JSON khổng lồ lặp toàn bộ records. Embedding input local vẫn cần đối chiếu endpoint trước khi gọi model. Xem [kiểm thử](M2_PASSAGES_TEST_REPORT.md) và [prompt AG review](AG_REVIEW_M2_PASSAGES_PROMPT.md).
