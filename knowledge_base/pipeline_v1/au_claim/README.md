# AU claim-first pilot

Luồng thử riêng: TARGET → claim/kind/evidence/limits → context chỉ khi có câu hỏi thiếu → AU sửa lại nếu cần. Giữ model 9B và 16 TARGET của calibration KOS. Chưa thay pipeline mặc định.

Không có model-generated offset, primary/support bắt buộc, global decision hoặc reason code. Host giữ nguồn và checkpoint. Context không tự thành AU chỉ vì được đọc; mỗi AU phải có evidence TARGET, và semantic ownership vẫn cần đối chiếu nguồn.

Prompt hiện tại là `claim_first_v3_source_close` (Experiment A); wire VERSION vẫn là `au-claim-v1`. Prompt được viết lại để giữ legal proposition sát nguồn: đúng chủ thể, modality, phủ định, qualifiers và điều kiện kết hợp; không suy đoán mở rộng đại từ hay thêm quan hệ nhân quả. Khi thiếu nghĩa trọng yếu, hỏi context trung tính. Gom rule với rationale/exception trọng yếu thành một legal point; giữ các quyền/nghĩa vụ/test/áp dụng và rationale pháp lý độc lập hữu ích. Khi TARGET có quyền/nghĩa vụ/test thực chất, tránh dùng slot cho policy slogan chung hoặc vị trí statute thuần; không có bộ lọc cứng theo citation/marker. Kết luận vụ việc giữ phạm vi vụ việc; reported authority không tự thành quan điểm được tòa hiện tại chấp nhận.

Giữ claim 500, limits 250 và câu hỏi context 200 ký tự; evidence phải hỗ trợ cả claim lẫn limits. Năm ví dụ hoàn toàn hư cấu, gồm output rỗng, hai AU, rule/rationale/exception nhiều câu được gom và câu hỏi mơ hồ không dẫn dắt; không lấy đáp án KOS. Không đổi schema, grammar, model 9B, cap 800, tối đa 3 AU, budget, taxonomy, runtime hoặc cơ chế context. Không thêm quote bắt buộc, validator semantics hay lượt gọi. Prompt instructions: 3.916 UTF-8 bytes (v2: 3.979); đây không phải token usage provider. Chưa có bằng chứng cải thiện ngữ nghĩa của v3.

Các root v1 `outputs/au_claim_kos16_20261019_ready` và v2 `outputs/au_claim_v2_local_ready_20261019` là lịch sử, phải bảo toàn. Các root v1/v2 khác cũng không được resume bằng v3, đổi nhãn hay sửa workload/receipt/fingerprint. V3 phải prepare root mới: preflight từ chối prompt/code fingerprint cũ. Chỉ resume root v3 có cùng prompt/code fingerprint.

Từ PowerShell, mặc định chỉ chạy local/mock:

```powershell
G:
cd G:\Git\coliee-case-retrieval
$run = "knowledge_base\pipeline_v1\outputs\au_claim_kos16_claim_first_v3_source_close_$(Get-Date -Format yyyyMMdd_HHmmss_fff)"
& .\knowledge_base\pipeline_v1\experiments\run_au_claim.ps1 -OutputRoot $run
```

Chỉ khi được phép chạy inference thật, sau khi local đạt, dùng cùng root v3 vừa tạo và cùng `.env` đang dùng:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_au_claim.ps1 `
    -Execute -Concurrency 2 -OutputRoot $run
```

Warmup đã tích hợp. Tối đa 16 lượt chính và 16 lượt context; không gọi context cho mọi TARGET, không lặp sửa vô hạn. Giữ root khi resume. Không cần deploy lại server chỉ để đổi payload/grammar phía client.

Đầu ra:

- `input/workload.json`: nguồn/TARGET/context khóa như baseline, model và budget.
- `input/reference_checklist.json`: KOS reference riêng, không truyền model.
- `live/run.json`, receipt và ledger: draft lượt đầu, kết quả sau context, pending/invalid/needs-context, usage và latency. Local ở `mock/`, không phải kết quả AU ngữ nghĩa.
- `comparison_live_*/comparison.json`: ghép evidence để đọc KOS và baseline cũ, giữ claim/limits mới; không lấy overlap làm semantic correctness.

Trạng thái protocol complete chỉ xác nhận request đã kết thúc hợp lệ. AU là dự đoán cần đánh giá; không có human gold hoặc bằng chứng retrieval từ phép thử này. `kind=null` không tự làm claim mất tư cách; `context_request` còn tồn tại sau lượt hai phải hiện là thiếu thông tin, không được coi là AU đã hoàn chỉnh.

Thiết kế nền: `knowledge_base/design/pipeline_redesign_lynx/31_claim_first_au_pilot.md` và `32_claim_first_v2_fidelity_coverage.md` trong cùng thư mục; đánh giá v2: `outputs/au_claim_v2_local_ready_20261019/semantic_review_20261019_v2/REVIEW.md` (dưới `knowledge_base/pipeline_v1`). Experiment A chỉ thay prompt như mô tả trên; nghiệm thu ngữ nghĩa cần đọc nguồn và đối chứng riêng. Không mở sang NN/Issue matching, KOS toàn bộ hoặc corpus lớn trong pilot này.
