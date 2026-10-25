# Audit thành phần pipeline vòng 2

> Tài liệu này ghi quyết định trước khi thu hẹp phạm vi về preprocessing/KB. Các kết luận về raw retrieval, candidate generation hoặc AU-only retrieval không phải quyết định hiện hành; bảng vẫn được giữ làm bằng chứng lịch sử và nguồn ablation. Xem `03_decision_log.md` và `04_pipeline_spec.md`.

| Thành phần | Mục đích | Bằng chứng hiện có | Dữ liệu/phụ thuộc | Chi phí chính | Lỗi có thể gây ra | Phương án thay thế | Phép thử chọn/bỏ |
|---|---|---|---|---|---|---|---|
| Immutable source + hash | Nguồn kiểm chứng | Lynx document contract; code hiện có | File source | Storage/hash | Hash/version sai | Không có | Exact materialization, update invalidation |
| Document map | Định địa chỉ và mở context | LKG span/part; audit marker | Source | CPU/storage thấp | Split/heading sai | Window cố định | Coverage 100%, perturb marker/heading |
| Raw BM25 | Fallback toàn corpus | Task retrieval baseline | Document map | Index time/storage | Lexical miss | Dense arm riêng | Recall@50/100/200 |
| Heading/marker rule | Boundary signal rẻ | 1.721 án thiếu marker; heading audit lỗi | SourcePart | CPU thấp | False boundary/hard gate | Signal mềm | Boundary precision/recall theo slice |
| Citation regex | Citation candidate rẻ | Citation có pattern nhưng 242 no-marker cases vẫn có match | Source | CPU thấp | Non-standard citation miss | Citation NER local | Mention F1 + exclusive retrieval contribution |
| Citation/entity NER local | Bổ sung pattern miss | Lynx German NER | Sentence + context | GPU/CPU inference | Domain shift, nested entity | Rule hoặc LLM route | Canada holdout + throughput/OOM |
| Rhetorical-role local | Document map ngữ nghĩa | LegalSeg/RR sequence studies | Sentence sequence | Compute/model storage | Role confusion, jurisdiction shift | Rule/statistics; raw windows | Per-role F1 + context saving |
| Speaker/function candidate | Hỗ trợ attribution | Chưa có transfer evidence đủ | Role/entity/context | Annotation/verification | Party thành court voice | Query-time verification | Attribution error reduction |
| Terminology/concept | Query/context hint | Lynx Spanish work preliminary | Text + vocabulary | Build/maintenance | Concept drift | Lexical raw retrieval | Gold-exclusive cases, gained/lost |
| Candidate routing | Giới hạn xử lý sâu | V15 over-materialization | Hits/signals/budget | Queue/feature compute | Feedback bias | Raw-only | Rare/no-citation recall cùng budget |
| Evidence bundle | Giảm source lặp | V13/V15 lặp context | Document map/sidecars | Query-time chars/tokens | Mất qualifier/response xa | Whole case control | Error + unique/repeated tokens |
| LLM selective route | Ca khó và semantic verification | V13–V15 cho thấy cả ích lợi lẫn chi phí/lỗi | Candidate + bundle | Provider token/request | Retry, hallucination, schema failure | Local/unknown | Curve 0/1/5/10% |
| AU/derived record | Tái sử dụng nội dung pháp lý | Chưa có retrieval break-even | Exact evidence + verifier | Extraction/verification/update | Omission, attribution, stale record | Query workspace/raw evidence | Lifecycle break-even + semantic quality |
| Treatment | Mô tả quan hệ với authority | Evidence thường xa | Authority + court response | Context/verification cao | Loại adverse noticed case | Metadata unknown | Two-witness accuracy; không filter |
| Combined retrieval | Dùng nhiều view | Chưa đo trên pipeline mới | Raw + optional indexes | Query latency/duplication | AU-rich cases lấn raw | Raw-only/source floor | Fixed budget, lane-exclusive Recall |
| Cache/checkpoint | Tránh trả lại chi phí | Code V13–V15 có nền tảng | Fingerprints/attempts | Storage/complexity | Reuse stale, double apply | Recompute | Hit identity, fault injection, idempotence |
| Retry | Khôi phục lỗi tạm thời | Nhiều 503/timeout cũ | Error classes | Latency/token | Retry payload sai/semantic uncertainty | Fail-fast/unresolved | Mock 400/429/503/empty |
| Update/invalidation | Giữ output đúng version | Lynx contracts + current cache | Dependency graph | Rebuild | Over/under invalidation | Full rebuild control | Source/model/config mutation tests |
| V15 migration | Tận dụng utility cũ | Audit artifact/code | Raw, cache, candidates | Revalidation | Nâng triage rác thành AU | Xây lại derived data | Exact refs + acceptance audit |

## Kết luận audit

Chỉ source/hash, document map, raw retrieval, provenance và cache/failure contract thuộc core mặc định. Rule sidecar được thử trước vì rẻ. Model local, LLM và mọi derived record phải vượt phép thử độc lập; không ghép chúng thành một pipeline bắt buộc rồi mới đo tổng thể.
