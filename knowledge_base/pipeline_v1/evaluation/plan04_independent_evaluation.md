# Đánh giá độc lập Kế hoạch 04

## Verdict

**PASS — 2026-10-03 23:18 +07:00.** SentenceAtom/protected-span contract đạt gate độc lập trên KOS-5. Không có finding mở trong phạm vi Plan 04. Không bắt đầu Plan 05.

PASS này xác nhận exact address/coverage, deterministic provenance, protected-boundary contract, derived-slice planning và cache behavior. Nó không chứng minh sentence segmentation đúng ngữ nghĩa trên toàn corpus, không tạo LegalUnit và không đánh giá AU/retrieval.

## Bằng chứng chạy

```powershell
python -m knowledge_base.pipeline_v1.sentence_atoms
python -m unittest discover -s knowledge_base/pipeline_v1/tests -v
python -m unittest discover -s knowledge_base/pipeline_v1/evaluation -p "test_*.py" -v
python -m unittest knowledge_base.pipeline_v1.evaluation.test_plan04_independent -v
```

- CLI Plan 04: PASS.
- Test gốc Plan 01–04: 42/42 PASS.
- Independent Plan 01–03 trước Plan 04: 24/24 PASS.
- Independent Plan 04: 7/7 PASS.
- Rebuild/resume: 5/5 artifacts `reused`; 0 artifact hiện có đổi bytes.

## Black-box KOS-5

Đã mở source qua Plan 02 và validate đúng SourceBlock v1.3 bằng path/hash/canonical identity trước segmentation. Tái tính trực tiếp từ năm `sentence_atom_map.json`:

- 5 case, 206.853 Unicode codepoints;
- 431 parent SourceBlocks;
- 1.240 SentenceAtoms;
- 2.754 protected spans;
- 5 derived slice plans, 10 slices;
- 10 review events, 0 error events.

Các con số trên khớp implementation report nhưng được tính lại từ artifact, không dùng report làm ground truth.

Mỗi atom nằm trong đúng parent block, order liên tục, không gap/overlap và ghép theo thứ tự khôi phục chính xác từng block lẫn toàn case. `parent_block_refs` khớp chính xác block ID/order/span/content_span/marker_span/parser version/policy hash của SourceBlock map.

## Protected spans và adversarial cases

Contract phân biệt rõ:

- `boundary_forbidden`: abbreviation, initial, reporter citation, case name, decimal/section reference, citation year, paragraph marker và list marker;
- `context_only`: balanced/unbalanced quotation và newline layout.

Không atom boundary nào nằm bên trong forbidden span. Independent fixtures bao phủ `v.`, case name với `v.`, `J.`, initials, `No.`, `s.`, `para.`, `F.C.`, reporter punctuation, `[1987]` so với `[12]`, decimal/section refs, balanced multi-sentence quote, unclosed quote, list marker, heading/editorial/table, BOM, CRLF/LF, whitespace và very-long block.

Balanced/unbalanced quotes được giữ là context observations, không bị biến thành global boundary lock. Unclosed quotes tạo review event, không giả parser error.

## Rà 10 quote review events

Đã mở trực tiếp exact source preview cho đủ 10 events: 1 ở án `013948`, 9 ở `045155`. Tất cả vẫn là:

- `event_type=unbalanced_quotation`;
- `severity=review`;
- `message_code=unbalanced_quote_requires_review`.

Mutation severity, message và event ID đều bị validator từ chối; review không thể bị hạ hoặc che mà artifact vẫn PASS.

## Identity, corruption và cache

Fault injection riêng xác nhận từ chối:

- cache key, case/source identity, SourceBlock cache/parser/policy provenance;
- parent refs;
- atom ID, parent, order, span;
- protected-span ID, mode, duplicate và refs;
- plan/slice IDs, parent, order, span và first/last atom links;
- segmenter version, policy hash và artifact path;
- missing/extra/wrong-type/malformed/partial/corrupt artifacts.

Segmenter version, policy, source hoặc parent SourceBlock cache đổi tạo cache identity mới; artifact cũ không được reuse như hợp lệ. Cached artifact khác bytes bị từ chối ghi đè.

## Derived slices và ranh giới phạm vi

Slice chỉ chứa IDs, parent ID, exact span và first/last atom IDs. Không materialize text, không tạo canonical SourceBlock/candidate và `model_specific=false`. Slice boundaries trùng SentenceAtom boundaries và các slices phủ chính xác parent block.

Không thấy `LegalUnit`, semantic role, `AuthorityUnit`, Issue, NoticeNeed, retrieval, AnalysisRegion hoặc LLM trong output Plan 04.

## Kết luận

Plan 04 đạt gate độc lập trong phạm vi KOS-5. KOS-5 là calibration/contract set, không phải bằng chứng generalization hoặc sentence gold. Plan 05 cần một lượt triển khai và đánh giá riêng.
