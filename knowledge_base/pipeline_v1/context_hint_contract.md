# ContextHint contract v1

`ContextHint` là sidecar đề nghị mở thêm context. Nó không tạo semantic edge, không xác nhận speaker, attribution, condition, coreference, topic hay legal fact, và không được loại primary target.

## Identity và span

- `hint_id` là hash canonical của target, type, direction, related/evidence spans, rule/version và dependency identities.
- Target, related và evidence refs phải cùng `case_id`/`source_hash`, nằm trong source, dùng offset nửa mở `[start,end)`.
- `previous`/`next` phải khớp thứ tự SourceBlock. Không cho self-link hoặc duplicate canonical key.
- Artifact không chứa source text; text chỉ được mở từ immutable source store.

## Status

- `candidate`: cue local đề nghị context nhưng không xác nhận nghĩa.
- `accepted_by_contract`: rule structural có exact evidence đã thỏa contract; không có nghĩa là đúng ngữ nghĩa.
- `unresolved`: có cue nhưng không có related span hợp lệ trong biên case.

## Invalidation và partial runs

Cache key phụ thuộc source hash, SourceBlock, SentenceAtom, sidecar map, rule bundle và policy hash. Bất kỳ parent/source/policy đổi đều tạo path mới. Rule lỗi được ghi riêng; output partial giữ output hợp lệ từ rule khác nhưng reader mặc định từ chối coi partial là complete.

Build manifest không phải metadata đáng tin độc lập. Reader phải resolve
`artifact_ref` trong đúng output root, mở và validate lại đúng năm complete maps,
đối chiếu parent/cache/policy identities rồi tái tính per-case và global counts,
type/status/direction, cap/dedup totals và unique/repeated chars. Manifest hoặc
artifact hiện hành hỏng làm cache resume thất bại; build không được âm thầm ghi
đè rồi báo `reused`.

`cap_dedup_ledger.jsonl` và `rule_event_ledger.jsonl` có JSON Schema, canonical
event identity, provenance, severity/message code và phải reconcile đúng từng
record với immutable maps. Dòng malformed, thiếu, thừa, sai type hoặc truncated
đều là lỗi contract có cấu trúc.

## Scope

Chỉ gồm bảy type đã khóa. Không có topic embedding, coreference, condition inference, ContextObligation, AnalysisRegion, LegalUnit, AU, Issue, NN, retrieval hay LLM.
