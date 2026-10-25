# Compact AU extraction contract v1 — đã chốt

## 1. Mục đích và phạm vi

Contract này thay thế **payload model** quá đầy đủ ở bước AU extraction. Nó không thay đổi SourceContract, SentenceAtom, AnalysisRegion, lựa chọn Issue, ContextHint hay retrieval/reranking.

Mỗi request có đúng một target. Model chỉ trả những nhận định ngữ nghĩa host không thể tự suy ra. Host dựng full `plan10-au-model-output-v1` sau khi kiểm tra evidence.

Lý do: run strict-schema ngày 09-10-2026 kết thúc `length` ở cả 10 request với trần 1.600 output token. Endpoint đã xác nhận hỗ trợ full `json_schema`; lỗi là payload extraction quá dài, không phải lỗi endpoint hay source offset.

## 2. Compact model response

```json
{
  "request_id": "auo-...",
  "target_id": "at-...",
  "decision": "positive",
  "unresolved_reason": null,
  "au": {
    "kind": "holding",
    "other_kind": null,
    "claim": "A concise legal proposition.",
    "evidence_ref_ids": ["sa-..."],
    "speaker": "current_court",
    "attribution_role": "proposition",
    "needs_context": []
  }
}
```

Quy tắc bắt buộc:

- `request_id` và `target_id` phải đúng request đã khóa.
- `decision` chỉ là `positive` hoặc `unresolved`.
- `positive` có đúng một `au`; `unresolved` có `au: null` và một `unresolved_reason` hợp lệ.
- Một `au` có đúng một `kind`, `other_kind`, một `claim` tối đa 300 ký tự, từ một đến ba `evidence_ref_ids`, `speaker`, `attribution_role` và `needs_context`.
- `other_kind` là `null` trừ khi `kind=other`; khi đó nó là nhãn ngắn tối đa 160 ký tự.
- Model không trả `start_char`, `end_char`, `quote`, `local_au_id`, condition/exception/limit spans, warning hay context request.
- `evidence_ref_ids` chỉ được phép trỏ tới SentenceAtom đã được host đưa vào vùng request. Không được tạo ID mới.
- `needs_context` là danh sách nhỏ từ: `attribution`, `condition`, `exception`, `limit`, `current_court_response`, `cross_block_context`.
- Prompt yêu cầu đúng một result, tối đa một AU và `unresolved` khi evidence không đủ. Không yêu cầu model giải thích ngoài JSON.

`kind` giữ tập nhãn AU hiện có: `holding`, `standard_of_review`, `statutory_hook`, `procedural_rule`, `fact_pattern_rule`, `foreign_law`, `other`, `unresolved_kind`.

## 3. Evidence reference và provenance

Mỗi `evidence_ref_id` ánh xạ bất biến qua SentenceAtom/SourceBlock map:

```text
evidence_ref_id
  -> case_id, source_hash, start_char, end_char
  -> CaseSource[start_char:end_char] = quote
```

Host, không phải model, tạo offset và quote. Vì vậy quote luôn là lát cắt chính xác của source đã hash. Nếu một ID không thuộc region, source hash không khớp, hoặc span rỗng/không hợp lệ, result là `unresolved`/host-validation failure; không thay ID bằng suy đoán.

## 4. Host normalizer sang full contract

Sau compact-schema validation và evidence resolution, host dựng full record:

| Full field | Nguồn |
|---|---|
| `schema_version`, `request_id`, `processed_target_ids` | request đã khóa |
| `target_id`, `decision` | compact response, kiểm ownership |
| `local_au_id` | hash xác định từ request + AU ordinal |
| `kind`, `claim_text` | compact `au` |
| `evidence_spans` | resolved `evidence_ref_ids` |
| `attributions` | `speaker`, `attribution_role`, cùng evidence span |
| `candidate_status` | `needs_context` rỗng: `complete`; ngược lại: `needs_context` |
| `condition_spans`, `exception_spans`, `limit_spans` | mảng rỗng ở bước extraction |
| `uncertainty_reasons` | chuyển đổi có kiểm soát từ `needs_context`; không suy diễn span |
| `other_kind` | `null`, trừ `kind=other` khi compact payload có `other_kind` hợp lệ |
| `context_requests`, `warnings` | mảng rỗng ở bước extraction |

Host không được bịa condition, exception, limit, court response hoặc citation treatment từ các trường mặc định. Những điều chưa đọc là `unknown`/uncertainty, không phải kết luận âm tính.

## 5. Validation và failure contract

Thứ tự xử lý:

1. Validate strict compact JSON Schema.
2. Kiểm `request_id`, `target_id`, enum và cardinality.
3. Resolve mọi `evidence_ref_id` vào source map, kiểm `case_id` và `source_hash`.
4. Tự tạo offsets/quotes; validate full output sau normalizer.
5. Chỉ khi tất cả bước trên pass mới có `protocol_verified`.

`length`, malformed JSON, ID không hợp lệ, evidence ngoài region hoặc full-normalization failure tạo result `unresolved`; raw diagnostic được lưu có giới hạn để debug. Không retry schema/semantic failure tự động. Retry chỉ áp dụng cho transport và HTTP retryable.

## 6. Ngân sách và kiểm thử trước pilot

- Output cap khởi đầu: 800 token/request; đây là giả thuyết cần đo, không phải cam kết.
- Không tăng output cap toàn bộ chỉ để chữa `length` của full payload.
- Chạy một target đại diện trước, sau đó mới chạy 10 target.
- So sánh với run strict cũ: tỷ lệ `length`, JSON/schema-valid, evidence-ref valid, full-normalized, host-verified, output token thực và latency.
- Kiểm thử bắt buộc: unknown/unresolved; evidence ID ngoài region; source hash đổi; ID hợp lệ nhưng span không thuộc target context; kind `other`; `needs_context`; cache/resume không replay cache của prompt/schema cũ.

## 7. Không suy ra từ contract này

Compact output không xác nhận AU đúng về ngữ nghĩa, không xác nhận treatment, và không giải quyết AU--Issue--NN matching. Đây chỉ là contract tiết kiệm token và giảm lỗi protocol cho extraction một target.
