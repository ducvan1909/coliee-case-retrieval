# Đánh giá độc lập Kế hoạch 07

## Verdict

**PASS — 2026-10-04.** Coverage, slicing, batching, region rendering, read validation và cache/immutable-history contracts đạt trên KOS-5. Không có finding chặn; không bắt đầu Plan 08.

PASS này không chứng minh P2b tốt hơn P2a hoặc ContextHint cải thiện semantic omission.

## Bằng chứng chạy

- CLI Plan 07: `PLAN07 PASS`.
- Test gốc Plan 01–07: 83/83 PASS.
- Independent Plan 01–07: 51/51 PASS.
- Independent Plan 07: 6/6 PASS.
- Cache rerun: 5/5 current artifacts `reused`.
- Immutable audit: 18 artifacts trước/sau, 0 đổi hoặc mất; 13 historical artifacts được giữ nhưng không bị reader chọn làm current.
- Không sửa implementation; không bắt đầu Plan 08.

## Coverage và classification

Tái tính trực tiếp từ năm workload maps:

- 431 SourceBlocks;
- 369 eligible content blocks và đúng 369 parent primary targets;
- 62 non-target blocks: 22 audit-only editorial, 39 structural-context candidates, 1 structural-only empty content span;
- 5 long parent blocks tạo 10 slices; slices phủ exact parent `content_span` liên tục, không gap/overlap;
- 374 work items, 96 deterministic batches;
- mỗi arm P2a/P2b có 96 regions và cùng target workload;
- context refs không được tính lại thành target; cap competition không làm mất target.

Ba regions có `context_cap_exhausted`: một drop do `max_context_chars`, hai drop do `max_context_spans`. Targets vẫn được giữ và mọi violation có stop reason.

## Renderer, metrics và API boundary

Renderer mở immutable source theo case/hash và SpanRef khi được gọi, đánh dấu TARGET/CONTEXT, giữ deterministic render order và không lưu canonical source text trong manifest. Mutation source, render order, span/dependency/policy identity, fingerprint hoặc stored metrics bị từ chối.

Metrics tái tính:

| Arm | Regions | Unique source chars | Proposed | Repeated | Rendered | Estimated tokens |
|---|---:|---:|---:|---:|---:|---:|
| P2a | 96 | 201.599 | 295.519 | 93.920 | 342.095 | 85.559 |
| P2b | 96 | 201.599 | 295.519 | 93.920 | 342.186 | 85.581 |

Token count là `ceil(rendered_chars/4)` theo policy, chỉ là estimator; không phải provider tokenization hoặc bằng chứng token saving.

## ContextHint reconciliation

Đủ 28 hints được reconcile đúng một lần:

- target eligibility: 16 eligible, 12 target-ineligible structural-only;
- disposition: 7 `included_provenance_only_already_baseline_context`, 9 `related_is_primary`, 12 `target_ineligible_structural_only`;
- 0 new P2b source spans, 0 new P2b source chars, 0 displaced P2a spans.

P2b tăng 91 rendered chars và 22 estimated tokens chỉ do provenance/metadata labels. Đây không phải semantic gain hoặc context gain. Trên KOS-5, P2b là no-op về source context; giá trị ContextHint vẫn cần P2a/P2b held-out semantic evaluation.

## Fault injection và cache

Reader/build validation từ chối missing/duplicate target, slice gap/overlap, count/metric drift, render-order/fingerprint changes, unsafe/missing refs, source/dependency/policy mismatch, hint disposition missing/duplicate/wrong outcome, cap/stop-reason tamper, corrupt current artifact và candidate structural relation bị dùng như accepted context. Cache preflight không tự chữa artifact hỏng.

Current namespace được xác định bằng scheduler version + policy hash và đối chiếu đúng năm canonical manifest refs. Mười ba artifacts của policy/scheduler cũ vẫn tồn tại nhưng không được load làm current.

## Kết luận

Plan 07 đạt **PASS trong phạm vi offline deterministic P2a/P2b workload construction trên KOS-5**. Không có finding mở. Quan sát quan trọng là P2b không mở thêm source span; metadata tăng không được trình bày như semantic/token gain.
