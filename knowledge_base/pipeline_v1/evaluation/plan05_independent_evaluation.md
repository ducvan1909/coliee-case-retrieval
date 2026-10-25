# Đánh giá độc lập Kế hoạch 05

## Verdict

**PASS — 2026-10-04 07:30 +07:00.** P05-F01 đã được retest độc lập và xác nhận `fixed_verified`. CLI, bộ test gốc và toàn bộ bộ test độc lập Plan 01–05 đều PASS. Không bắt đầu Plan 06.

Không có annotation/relation gold được phân xử, nên PASS này chỉ xác nhận contract, tính xác định và các ranh giới semantic đã khai báo; không chứng minh precision, recall, F1 hoặc chất lượng pháp lý.

## Bằng chứng chạy

```powershell
python -m knowledge_base.pipeline_v1.sidecars
python -m unittest discover -s knowledge_base/pipeline_v1/tests -v
python -m unittest discover -s knowledge_base/pipeline_v1/evaluation -p "test_*.py" -v
```

- CLI Plan 05: `PLAN05 PASS`.
- Test gốc Plan 01–05: 55/55 PASS.
- Independent Plan 01–05: 38/38 PASS, gồm 7/7 method Plan 05.
- Rebuild/resume: 5/5 complete artifact được báo `reused`.
- Hash audit: 10 `sidecar_map.json` hiện có trước/sau rerun, 0 file đổi hoặc mất.
- Không sửa implementation; không bắt đầu Plan 06.

## P05-F01 — Medium — fixed_verified

Lỗi cũ: annotation `[1,22)` bị trả về cho query rỗng `[11,11)`, trái với half-open semantics.

Retest `test_api_filters_and_adjacency_are_exact_half_open` xác nhận contract chung hiện áp dụng nhất quán:

- query `[x,x)` trả `[]` ở đầu, giữa và EOF;
- hai span chỉ chạm biên không overlap;
- annotation, persisted relation evidence và derived adjacency evidence cho cùng kết quả half-open;
- thiếu một offset, `bool`, non-integer, âm, đảo chiều, vượt source, sai case hoặc sai source đều bị từ chối bằng `SidecarQueryError`;
- query non-empty và các filter case/block/atom/worker/status vẫn hoạt động.

Không phát hiện regression mới liên quan đến bản sửa.

## Black-box artifact audit

Tái tính trực tiếp từ năm complete `sidecar_map.json`, không dùng report làm ground truth:

- 1.036 annotations: 904 observed, 112 candidate, 20 review;
- 419 persisted relations: 209 containment, 10 continuation, 200 governed-by-heading;
- relation status: 209 observed, 210 candidate;
- 0 worker events/errors ở complete run.

Exact source spans, refs, provenance, status, evidence và dependency identities được kiểm tra lại. Mutation độc lập trên annotation, relation và map bị validator từ chối; malformed, missing, extra, partial hoặc corrupt data tạo controlled error.

## Structural relation và semantic boundary

- 200 `governed_by_heading` edges đều là `candidate`, theo formal-heading contiguous-range policy; không self-edge hoặc duplicate pair.
- 209 containment edges giữ đúng parent; 10 continuation candidates chỉ theo cue cấu trúc đã khai báo; không self-edge, duplicate hoặc cross-parent defect.
- Adjacency `next`/`previous` được dựng từ SourceBlock order, mang `status=derived`, không được persist.
- Không có semantic graph relation bị cấm như `qualifies`, `responds_to`, `condition_for` hoặc `same_legal_point`.
- Citation, speaker và heading outputs vẫn chỉ là observed/candidate/review sidecars; chúng không chứng minh authority identity, attribution, relevance, support hay legal conclusion.

## Worker isolation và cache

Fault injection vào `marker_rule` tạo `run_status=partial`, worker event/error và namespace partial riêng; output worker còn lại vẫn tồn tại, complete namespace không bị ghi đè. Dependency/addressed-cache mutation và artifact corruption bị phát hiện. Rerun complete giữ nguyên bytes của toàn bộ sidecar maps hiện hữu.

## Kết luận

Plan 05 đạt **PASS trong phạm vi contract KOS-5 deterministic sidecars**. P05-F01 được đóng ở trạng thái `fixed_verified`; không có finding mở mới. Kết quả này không phải bằng chứng về semantic correctness hoặc khả năng tổng quát hóa ngoài KOS-5.
