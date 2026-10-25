# AnalysisTarget, scheduler và AnalysisRegion contract v1

Plan 07 tạo workload P2 offline; không gọi model và không tạo semantic output.

## Coverage và eligibility

Policy versioned quyết định block type nào là content. Mỗi content SourceBlock tạo đúng một `AnalysisTarget`. Heading candidate, editorial và structural-only blocks vẫn có `block_role` cùng lý do audit, không bị biến mất. Citation, marker, AU cue, NER, role hoặc topic không được dùng để skip target.

Block có `content_span` dài hơn pilot cap được chia thành `AnalysisTargetSlice` theo SentenceAtom. Các slice cùng parent phải phủ exact `content_span` không gap/overlap. Atom đơn vượt cap được giữ nguyên với `oversized_atom_preserved`; coverage ưu tiên hơn cap.

## Batching và region arms

Batching theo source proximity và caps deterministic. P2a và P2b dùng cùng workload target; P2b chỉ thêm ContextHint. Context priority là accepted structural relation, ContextHint, rồi local neighbor. Candidate structural relation không được nâng thành accepted fact. Target/context được trừ overlap và deduplicate trước render.

Hai arm dùng cùng fixed caps. P2b thêm hint vào candidate pool trước bước chọn context,
vì vậy selected context không mặc định là superset của P2a khi cap cạnh tranh. Report
phải tách retained/displaced P2a context và new P2b context; không gọi chênh lệch
đó là additive gain.

Mỗi ContextHint Plan 06 có đúng một disposition record. Target eligibility được
ghi riêng khỏi outcome của related span. Các disposition loại trừ nhau gồm:
`included_new_span`, `included_provenance_only_already_baseline_context`,
`related_is_primary`, `target_ineligible_structural_only`, `cap_dropped`,
`invalid_or_unresolved` và `no_eligible_related_context`. Reader tái tính ledger
từ hint artifacts và regions; không tin summary.

Mỗi region chứa refs, reasons, deterministic render order, unique/proposed/repeated chars, rendered chars, overlap ratio, estimator/version, caps, stop reasons, dependency hashes và fingerprint. Region vượt cap chỉ hợp lệ nếu target được giữ và có stop reason; target không bao giờ bị trim/drop để đạt cap.

## Render và token estimate

Mock renderer mở immutable source on demand, xác minh source hash/offset và đánh dấu `<TARGET>`/`<CONTEXT>`. Rendered text không được ghi vào canonical workload artifact. `utf8-char-ceil-v1` chỉ là ước lượng pilot `ceil(rendered_chars / 4)`, không phải provider tokenizer và không chứng minh token saving.

## Read/cache contract

Artifact path phụ thuộc source, SourceBlock, SentenceAtom, sidecar, ContextHint và region policy identities. Reader resolve safe refs, mở parent artifacts, dựng lại workload/metrics/fingerprint và đối chiếu manifest per-case/global. Cache hiện hành hỏng phải fail trước reuse; source/policy/dependency đổi tạo namespace mới.

## Ngoài phạm vi

Không có P0/P1, ContextObligation, CoverageLedger, AU, Issue, NN, retrieval, model hay LLM. PASS chỉ xác nhận workload/coverage contract, không xác nhận semantic quality hoặc P2 tốt hơn arm khác.
