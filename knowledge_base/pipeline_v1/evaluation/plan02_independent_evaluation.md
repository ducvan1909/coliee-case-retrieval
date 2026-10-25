# Đánh giá độc lập Kế hoạch 02

## Verdict retest

**PASS — 2026-10-03 16:26 +07:00.** P02-F01 đã được sửa và được tái hiện độc lập: read API hiện từ chối `case_source.json` sai schema, identity hoặc provenance. Không còn finding mở trong phạm vi Plan 02.

PASS này chỉ xác nhận contract kỹ thuật `CaseSource`, `SpanRef`, immutable source store, exact-span API và source-hash invalidation trên KOS-5. Nó không xác nhận parser, SourceBlock, annotation, AU semantics hoặc retrieval quality. Không kiểm thử hay bắt đầu Plan 03.

## Bằng chứng chạy lại

```powershell
python -m knowledge_base.pipeline_v1.source_contract --repo-root . --manifest knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json --plan01-report knowledge_base/pipeline_v1/evaluation/runtime/plan01_gate_retest2.json --store knowledge_base/pipeline_v1/evaluation/runtime/source_store_plan02 --report knowledge_base/pipeline_v1/evaluation/runtime/plan02_gate_retest.json
python -m unittest discover -s knowledge_base/pipeline_v1/tests -v
python -m unittest discover -s knowledge_base/pipeline_v1/evaluation -p "test_*.py" -v
python -m unittest knowledge_base.pipeline_v1.evaluation.test_plan02_independent -v
```

Kết quả:

- Plan 02 CLI: PASS; 5 case; round-trip/hash/offset rate 100%; report `evaluation/runtime/plan02_gate_retest.json`.
- Toàn bộ test gốc Plan 01–02: 20/20 PASS.
- Toàn bộ test độc lập Plan 01–02 trước khi mở rộng: 12/12 PASS.
- Bộ test độc lập Plan 02 sau khi mở rộng: 7/7 PASS.

## Fault injection độc lập

- Từng mutation riêng của `record_type`, `contract_version`, `source_version`, `case_id`, `source_hash`, `text_ref`, `encoding`, `offset_unit`: đều bị read API từ chối.
- Missing required fields, missing metadata member, wrong-type lengths/metadata, extra field, invalid JSON, JSON array và JSON null: đều bị chuyển thành `SourceContractError`; không có record lỗi được trả cho consumer.
- Source bytes bị đổi cùng độ dài, cắt ngắn hoặc nối thêm: đều bị hash/length check phát hiện; rebuild không ghi đè artifact hỏng.
- Span `[0,0)`, `[0,1)` và zero-length tại EOF hợp lệ; negative, reversed, vượt EOF, sai case/hash đều bị từ chối.
- Đổi raw source có cập nhật manifest tạo source hash/version mới, đúng một invalidation event, giữ version cũ đọc được, cập nhật current identity và không nhân đôi event khi rebuild không đổi.

## P02-F01 retest

Nguyên nhân cũ đã được đóng bằng ba lớp kiểm tra trên read path:

1. validate toàn bộ record bằng Draft 2020-12 schema;
2. parse đầy đủ required fields và chuẩn hóa lỗi JSON/schema/type thành `SourceContractError`;
3. kiểm tra `case_id`, full `source_hash`, `source_version == src-<hash prefix>` và canonical `text_ref` trước khi mở bytes.

Test tái hiện cũ `test_case_source_contract_tamper_is_rejected_by_read_api` PASS. Test mở rộng theo từng field cũng PASS, nên kết luận không dựa riêng vào regression test do agent triển khai thêm.

## Kết luận

Plan 02 đạt gate độc lập. Verdict FAIL cũ được thay bằng retest PASS; P02-F01 đóng. Có thể chuyển sang Plan 03 theo quy trình riêng, nhưng Plan 03 không nằm trong lượt đánh giá này.
