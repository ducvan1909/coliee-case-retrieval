# AU-compact runner

## Ràng buộc theo request bằng EBNF

Extraction hiện dùng grammar EBNF riêng cho từng request (`ebnf` của SGLang Chat Completions), không gửi đồng thời `response_format`. Contract JSON và schema đầy đủ ở host giữ nguyên. Grammar chọn nhánh positive/hard_negative/unresolved và kind=other; đóng cố định request_id/target_id; chỉ cho phép atom trong catalog, mỗi AU có ít nhất một TARGET atom. Evidence theo thứ tự ID tăng dần; needs_context theo thứ tự enum, không trùng. JSON dùng thứ tự key cố định, không có khoảng trắng định dạng ngoài chuỗi; khoảng trắng trong claim vẫn hợp lệ.

Host chỉ loại chuỗi trùng hoàn toàn trong needs_context/evidence_ref_ids trên bản sao trước khi validate. Lưu compact_response gốc và danh sách cleanup trong receipt. Host không sửa decision, kind hoặc thay atom sai. Output chưa hoàn tất (finish_reason khác stop) giữ unresolved, không nối/sửa JSON bị cắt. Grammar ngăn vòng lặp khoảng trắng định dạng; không bảo đảm output luôn đủ trong cap.

Đã sửa character class gây lỗi ASCII trên XGrammar 0.2.1: raw character dùng positive Unicode scalar ranges, tránh negated class chứa surrogate endpoints. Kiểm tra CPU bằng tokenizer Qwen đã cho phép lại văn bản thường; chưa đo inference/tốc độ endpoint của bản sửa. Chạy 5 control đầu trước, dùng thư mục mới để tách checkpoint cũ:

```powershell
$out = "knowledge_base\pipeline_v1\outputs\constraint_ebnf_$(Get-Date -Format yyyyMMdd_HHmmss)"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact constraint-suite-probe --decoder ebnf --output-root $out
if ($LASTEXITCODE -eq 0) {
    .\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_only warmup --execute --output-root "$out\warmup"
    if ($LASTEXITCODE -eq 0) {
        .\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact constraint-suite-probe --decoder ebnf --execute --max-requests 5 --output-root $out
    }
}
```

Sau 5 ca, status tổng `INCOMPLETE` là dự kiến vì chưa chạy đủ 226 ca. Kiểm tra từng result: phải đúng fixture, không truncated và latency không bất thường trước khi chạy tiếp. Nếu endpoint từ chối EBNF hoặc vẫn trả sai contract, không tự quay về decoder cũ. Sau khi control đạt có thể dùng --max-requests 30 để chạy theo đợt, tiếp tục cùng $out. Sau khi toàn bộ probe đạt, extraction dùng thư mục run mới vì decoder/cache identity đã đổi. EBNF được gửi theo request, không cần deploy lại chỉ để truyền grammar; khả năng hỗ trợ endpoint phải xác nhận bằng probe.

AU-compact builds a locked compact manifest, performs offline preflight, and only makes remote calls after an explicit `run --execute`. It does not alter the independent AU-only runner.

```powershell
python -m knowledge_base.pipeline_v1.au_compact build --manifest .\au_only_locked.json
python -m knowledge_base.pipeline_v1.au_compact preflight --manifest .\au_compact_pilot_r5_model_silver.v1.json --source-store knowledge_base\pipeline_v1\outputs\source_store_v1
python -m knowledge_base.pipeline_v1.au_compact run --execute --manifest .\au_compact_pilot_r5_model_silver.v1.json --source-store knowledge_base\pipeline_v1\outputs\source_store_v1
python -m knowledge_base.pipeline_v1.au_compact adversarial-schema-probe --execute --output-root .\outputs\au_compact
python -m knowledge_base.pipeline_v1.au_compact structured-output-probe --execute --output-root .\outputs\au_compact
python -m knowledge_base.pipeline_v1.au_compact constraint-matrix-probe --execute --output-root .\outputs\au_compact
python -m knowledge_base.pipeline_v1.au_compact schema-ablation-probe --execute --output-root .\outputs\au_compact
```

Remote execution requires the shared `AU_URL`, `AU_TOKEN`, and `AU_MODEL` settings and uses the shared request, token, and warmup caps from `knowledge_base/.env.example`. Keep real values only in the ignored `knowledge_base/.env`; neither CLI prints tokens. Canonical `AU_*` values win field-by-field. `AU_COMPACT_*` is supported only as a deprecated compatibility fallback for existing local configuration and must not be used for new configuration.

`adversarial-schema-probe` sends no manifest or corpus text. It asks for the deliberately invalid JSON `{"status":"positive","AUs":["sa-invalid"]}` while supplying the exact compact schema. It passes only if the returned content parses and the host Draft 2020-12 validator accepts it; invalid or malformed content is recorded with a content digest/length/preview and nonzero exit status. HTTP and transport failures are recorded separately.

`structured-output-probe` is also source-free, but exercises the endpoint's `structured_outputs: {"json": <compact schema>}` dialect instead of `response_format`. It supplies no `response_format` field. It distinguishes a schema-invalid HTTP 200 (`constraint_not_enforced`), rejected request (`request_rejected`), provider error, malformed result, and transport failure; only a host-valid Draft 2020-12 result is `supported`.

`complete` reports protocol completion, not semantic-quality validation or human gold.

Decoder JSON Schema cũ gửi `compact_au_transport.v1.json`, bỏ các điều kiện `allOf` / `if` / `then` / `else`. Các probe cũ vẫn giữ cách này để đối chiếu lịch sử; extraction hiện dùng EBNF theo request như mô tả phía trên. Host tiếp tục kiểm tra schema đầy đủ và evidence nguồn.

The source-free matrix and ablation probes are diagnostics, not corpus runs. On the managed Qwen/Qwen3.5-9B endpoint tested on 2026-10-10, a simple schema worked with `enable_thinking=false`; the compact schema worked after removing conditional keywords. This rules out disabled thinking as the cause for that endpoint/configuration. Provider 503 responses during scale-up must be separated from schema failures by completing warmup before interpreting an ablation result.

## Bộ kiểm tra từng ràng buộc endpoint

`constraint-suite-probe` kiểm tra contract hiện tại bằng ca hợp lệ và ca cố tình vi phạm từng ràng buộc. Không đổi schema, không đọc corpus và không chạy extraction. Mặc định `--decoder json_schema` giữ decoder cũ để đối chiếu; thêm `--decoder ebnf` để kiểm tra decoder extraction mới. Kết quả được kiểm tra bằng schema đầy đủ, contract ID/evidence và, với EBNF, quy tắc định dạng/thứ tự.

Chạy lập danh mục offline trước để xem số request và giới hạn output dự kiến:

```powershell
$out = "knowledge_base\pipeline_v1\outputs\constraint_suite_$(Get-Date -Format yyyyMMdd_HHmmss)"
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact constraint-suite-probe --output-root $out
```

Warmup rồi chạy bộ kiểm tra endpoint trên cùng thư mục:

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_only warmup --execute --output-root "$out\warmup"
if ($LASTEXITCODE -eq 0) {
    .\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact constraint-suite-probe --execute --output-root $out
}
```

`--max-requests N` giới hạn số request mới của lần chạy; nếu chưa kiểm tra hết danh mục, kết quả là chưa hoàn tất. Giữ nguyên `$out` để tiếp tục từ checkpoint có cùng endpoint/model/schema/cấu hình. Không retry âm thầm. Báo cáo `constraint_suite_probe.json` phân biệt lỗi provider, JSON/schema, output bị cắt và ràng buộc do host kiểm tra. Các response lỗi cũng được tính usage khi provider cung cấp.

Danh mục hiện tại có 226 ca. Mỗi ca tối đa 800 output token; dự phòng output toàn bộ là 180.800 token, không phải usage thực tế. Báo cáo offline tách ước lượng token prompt khỏi kích thước payload chứa grammar/schema; không coi toàn bộ payload HTTP là token model đọc. Usage provider sau khi chạy mới là số thực. Các ca biên của ID/evidence được đánh dấu `schema_only` để kiểm tra độ dài/kiểu mà không giả vờ đây là evidence thực của corpus. Một ca hợp lệ phải trả đúng fixture; ca bất hợp lệ không được né kiểm tra AU bằng cách chuyển sang `hard_negative` hoặc bỏ AU.

Checkpoint giữ cả kết quả fail để tránh tự phát sinh thêm request. Muốn thử lại một bộ đã fail sau khi sửa endpoint, dùng thư mục `$out` mới. Chạy theo đợt, ví dụ `--max-requests 30`, rồi lặp lại cùng lệnh và `$out` để xử lý các ca chưa chạy. Kết quả tổng chưa được PASS cho đến khi hoàn tất toàn bộ danh mục.

PASS chỉ chứng minh những ca đã chạy với endpoint/cấu hình này. Không bảo đảm model luôn đúng trong tương lai, không chứng minh AU đúng ngữ nghĩa và không cho phép bỏ validator host. Các kiểm tra hash/offset/quote/source binding vẫn thuộc bộ kiểm thử local và bước chuẩn hóa từ atom ID của pipeline.
