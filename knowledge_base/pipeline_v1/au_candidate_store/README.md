# AU candidate store — Kế hoạch 11

Module chạy offline sau AU compact, không gọi LLM. Đầu vào là `AUCompactRun`, source store và SentenceAtom map đã khóa. Đầu ra là `candidates.json` và `audit.json`.

```powershell
Set-Location G:\Git\coliee-case-retrieval
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_candidate_store build `
  --run knowledge_base\pipeline_v1\outputs\au_semantic_v4_dev3_20261011\run.json `
  --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
  --atom-root knowledge_base\pipeline_v1\outputs\plan04_sentence_atoms_v1 `
  --output-root knowledge_base\pipeline_v1\outputs\plan11_candidate_store_v4_20261011
```

Có thể lặp `--run` để đối chiếu nhiều lượt. Nguồn/atom store và input run không được dùng làm đích ghi. Cùng input tạo lại cùng candidate ID và nội dung store; không phát sinh inference.

## Hành vi đã triển khai

- Kiểm tra schema, case/source hash, atom binding, offset/quote và evidence nằm trong vùng được cấp. Quote được dựng lại từ nguồn; không tin span đã chuẩn hóa trong model output.
- AU có ID/evidence sai bị `rejected` riêng; kết quả hợp lệ khác vẫn được giữ. Target không AU vẫn có ledger để kiểm tra omission.
- `field_witnesses` ghi nhãn `MODEL_ASSERTED`, nối giá trị model với evidence đã chọn. Không tự coi atom đầu tiên là chứng minh speaker/condition.
- Ownership hiện là điểm neo cấu trúc ở phần evidence giao TARGET. Không có `primary_proposition_start` trong compact response nên `ownership_verified=false`. Evidence bắt đầu ở CONTEXT hoặc marker ngoài raw TARGET được giữ nguyên và chuyển `unresolved`, không cắt quote để làm kết quả trông hợp lệ.
- Speaker unknown, kind chưa rõ, nhu cầu context hoặc needs_split được giữ `unresolved`.
- Dedup chỉ khi cùng case/source hash, claim và các nhãn giống hệt, tập evidence giống hệt. Giữ mọi provenance; chọn canonical ID ổn định, bản lặp thành `superseded`. Claim khác nhưng evidence chồng lấn chỉ được nối để review, không tự gộp.
- Không AU nào tự thành semantic accepted. Khi chưa có review, `candidate` chỉ là đề xuất hợp cấu trúc và `accepted_count=0`. Review sidecar có thể chuyển thành `accepted_agent_reviewed`, không phải human gold hay chứng minh ngữ nghĩa bằng host.

## Nối review vào store

Contract: `contracts/au_candidate_review.v1.json`. Review khóa SHA256 exact bytes của run, SHA canonical của proposal, request ID và AU index. Reviewer chọn primary atom/quote và quote chứng minh từng field; host tìm quote duy nhất trong atom để dựng offset. Primary quote phải thuộc evidence đã chọn và nằm trong raw TARGET: marker ở ngoài atom không gây unresolved nếu proposition chính nằm bên trong TARGET. Không suy ownership từ một atom TARGET được thêm đệm.

Mọi check bắt buộc pass và witness hợp lệ mới được `accepted_agent_reviewed`. Semantic fail đơn nhất thành rejected; missing/unknown hoặc bất đồng thành unresolved. Nhu cầu context/split mà producer đã khai báo vẫn giữ chưa giải quyết. Field witness ghi `AGENT_REVIEWED`, `entailment_validated=false`; host xác minh source membership, không chứng minh entailment. Review lỗi/stale không được dùng để nâng trạng thái. Omission được review cả target không AU.

Tạo template pending (không tự gán verdict):

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_candidate_store template `
  --run knowledge_base\pipeline_v1\outputs\au_semantic_v4_dev3_20261011\run.json `
  --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
  --atom-root knowledge_base\pipeline_v1\outputs\plan04_sentence_atoms_v1 `
  --output-root knowledge_base\pipeline_v1\outputs\plan11_review_template_smoke_20261011
```

Lệnh `build` hỗ trợ `--review <sidecar.json>` lặp lại. Rebuild trên review/nguồn mới; output root mới để giữ lịch sử. Review cho các run khác nhau có cùng request ID vẫn được ràng buộc riêng bằng run hash. Cache identity của review phụ thuộc contract, implementation, run và review inputs. Không đặt human annotation làm điều kiện bắt buộc trong đợt này.

## Kết quả và giới hạn

Ngày 2026-10-11: 24/24 kiểm thử local đạt, bao gồm sai hash/ID, lỗi cục bộ, nguồn bị giả quote, lặp input, dedup độc lập thứ tự và hai case có cùng source hash. Kiểm thử không chứng minh entailment hoặc attribution.

Lượt prompt v4 trên ba target tạo 5 AU hợp giao thức. Store giữ 5 `unresolved`, chủ yếu do evidence-start/ownership mơ hồ; không accepted. Main review còn phát hiện claim lấy từ CONTEXT, TARGET bị dùng làm evidence đệm và omission của conditional duty. Xem `outputs/au_semantic_v4_dev3_20261011/semantic_review.main.json` và `outputs/plan11_candidate_store_v4_20261011/audit.json`.

Cập nhật cùng ngày: review của lượt v4 đã được formalize theo contract và nối vào output mới `outputs/plan11_candidate_store_v4_reviewed_20261011`: 1 holding accepted ở mức agent-reviewed, 4 AU bị rejected; target [41] còn omission của conditional duty. Đã có cách ghi primary span và witness riêng từng field. Đây là kết quả trên ba target phát triển, không chứng minh AU extraction toàn KOS-5 hoặc KB hoàn tất.

## Phép thử ContextHint tiếp theo

Chỉ chạy cặp P2a/P2b có cùng target, model, prompt, schema, output cap và source context cơ sở. P2b phải thực sự gửi nội dung hint có provenance; hint ID rỗng hoặc không được truyền không tạo đối chứng hữu hiệu. Tách thử metadata hint trên cùng context khỏi thử mở thêm context để không quy lợi ích source bổ sung cho hint.

Giữ lỗi baseline hiện tại để đo trước/sau: TARGET contribution, claim/evidence, omission, attribution và điều kiện. Báo cả token, retry, latency; chưa khẳng định ContextHint sửa được lỗi model. Không mở Plan 12 hoặc đổi model trong bước này.
