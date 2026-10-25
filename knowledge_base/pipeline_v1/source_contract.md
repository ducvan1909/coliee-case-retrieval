# Kế hoạch 02 — CaseSource, SpanRef và source store

## Source contract

Raw source là nguồn sự thật. KOS artifact chỉ xác nhận workload KOS-5 và cung cấp audit context; `gold_noticed`, `gold_for_queries`, AU, NN hoặc CiteSite trong KOS không được dùng làm gold.

Mỗi raw source được nhận diện bằng SHA-256 của bytes gốc. Store giữ nguyên bytes, kể cả UTF-8 BOM. Text dùng cho offset được giải mã bằng `utf-8-sig`; offset là Unicode codepoint và span là đoạn nửa mở `[start_char, end_char)`.

Layout:

```text
outputs/source_store_v1/
  source_store_manifest.json
  cases/<case_id>/index.json
  cases/<case_id>/versions/<full-sha256>/source.txt
  cases/<case_id>/versions/<full-sha256>/case_source.json
  invalidation/inv-<id>.json
```

`source.txt` và `case_source.json` trong version directory là bất biến. Nếu file đã tồn tại nhưng bytes khác, build fail thay vì ghi đè. `index.json` là con trỏ metadata có thể cập nhật atomically tới version hiện tại.

## Invalidation

`source_version` là `src-<16 ký tự đầu của source hash>`. Source bytes mới tạo hash/version directory mới; version cũ vẫn giữ nguyên. Khi current hash của case đổi, store ghi đúng một invalidation event cho cặp `(case_id, old_hash, new_hash)` và đánh dấu dependency closure của hash cũ phải xây lại.

Trong các bước sau, cache/artifact phải mang ít nhất `case_id + source_hash`; artifact không khớp hash hiện tại không được resume như hợp lệ. Worker hoặc region-policy change sẽ có invalidation hẹp riêng, chưa triển khai trong Kế hoạch 02.

## Python API

```python
from knowledge_base.pipeline_v1.source_contract import SpanRef, open_source, open_span

text = open_source(store_root, case_id, source_hash)
excerpt = open_span(
    store_root,
    SpanRef(
        case_id=case_id,
        source_hash=source_hash,
        start_char=100,
        end_char=240,
    ),
)
```

API kiểm tra identity/hash/length của source trước khi trả text. Span âm, đảo chiều, vượt cuối source hoặc trỏ sai source hash đều bị từ chối.

## Ranh giới

Kế hoạch này không tạo SourceBlock, SentenceAtom, annotation, AnalysisRegion hoặc gọi LLM. PASS chỉ chứng minh raw-byte round-trip, source hash và exact offset contract trên KOS-5.

