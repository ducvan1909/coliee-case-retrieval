# So AU KOS và pipeline trên cùng vùng nguồn

## Mục tiêu

Khóa đầu vào chứa evidence AU KOS rồi chạy pipeline hiện tại trên chính những vùng đó. So cách tách legal point, chọn evidence, giữ điều kiện và attribution. Chưa thay prompt, model, schema hoặc chính sách uncertainty trong phép thử này.

Đây là calibration chọn vùng theo reference, **không phải** kiểm thử khả năng tìm mọi AU trên toàn bản án. KOS là artifact tham khảo, không phải human gold hoặc danh sách AU đầy đủ.

## Phạm vi đã kiểm kê

| Case | AU KOS có sẵn | Vai trò trong phép thử |
|---|---:|---|
| 011904 | 8 | So trên vùng nguồn chứa evidence |
| 045155 | 5 | So trên vùng nguồn chứa evidence |
| 099980 | 5 | So trên vùng nguồn chứa evidence |
| 013009 | 0 | Không có AU reference; không suy thành negative |
| 013948 | 0 | Không có AU reference; không suy thành negative |

Nguồn: `G:/Legal-AI/kos_sample`; khóa cây file bằng `selected_kos_manifest.v1.json`. Source bất biến và SentenceAtom của pipeline giữ nguyên. Evidence 18 AU được căn theo nguyên văn hoặc chỉ chuẩn hóa whitespace; không suy offset từ `para_idxs`, không fuzzy-match. Evidence mơ hồ phải báo lỗi thay vì tự chọn.

Kiểm tra local ngày 2026-10-18: selector tạo 16 TARGET (8 + 5 + 3), dài 365–1.201 ký tự. Toàn bộ dùng `bound_atom_parent_blocks`, chưa dùng fallback. Hai TARGET trong `099980` mỗi vùng có hai AU reference; các vùng còn lại một AU reference. Số reference không chứng minh số AU thực tế; trần ba anchor vẫn phải theo dõi saturation. Chạy thật cần 16 request stage 1 và tối đa 16 request context, chưa tính provider retry/readiness; không phải 18 request cho 18 AU.

## Đầu vào cùng nguồn

1. Lấy toàn bộ SourceBlock chứa evidence, không cắt TARGET đúng bằng quote KOS. Evidence qua nhiều block thì TARGET bao phủ các block đó. Gộp TARGET cùng/chồng vùng, giữ địa chỉ nguồn.
2. Context cố định: một block liền trước và một block liền sau. Đây là cửa sổ kiểm soát, không bảo đảm mọi attribution/điều kiện xa đã đủ. Thiếu context được ghi nhận khi đánh giá, không tự thêm đáp án từ KOS.
3. Model chỉ nhận nguyên văn TARGET/CONTEXT và địa chỉ ref theo contract hiện tại. Không nhận claim, kind, limits, Issue, NN match, citation gold hoặc ID AU KOS.
4. `reference_checklist.json` giữ riêng claim/evidence/limits KOS, mapping tới TARGET và hash nguồn. Không dùng checklist để ép model sinh đúng số AU KOS.
5. Giữ `primary_support_v1`, model và cấu hình endpoint trong `.env` hiện tại; không đổi mặc định profile khác. Trần ba anchor/TARGET và output 800 giữ nguyên. Nếu TARGET chứa nhiều legal point hơn trần, phải ghi nguy cơ thiếu coverage, không coi ít AU là thành công tiết kiệm.

## Thực hiện

- Chuẩn bị workload mới có artifact type riêng; verifier tái dựng TARGET/ref từ source và selector đã khóa. Không nới điều kiện đúng 32 TARGET của workload cũ.
- Chạy preflight và mock trước, kiểm tra source/hash/offset, tách reference khỏi payload, cache/resume và so sánh nguồn. Toàn bộ bước này không inference.
- Sau khi local đạt, người dùng chạy live trên workload đã khóa. Runner hiện tại giữ readiness, grammar, host validation, checkpoint và resume; không thêm vòng model chỉ để so KOS.
- So kết quả stage 1 với trạng thái cuối riêng. AU được model chọn nhưng thành unresolved sau context phải hiện trong báo cáo, tránh nhầm với không tìm được AU.

## Báo cáo cần đọc

Tạo cặp khả dĩ bằng overlap evidence để hỗ trợ đọc, **không** dùng overlap làm chứng cứ hai AU tương đương. Cho phép nhiều AU pipeline ứng với một AU KOS và ngược lại; giữ kết quả không ghép được.

Với từng legal point, đối chiếu từ nguyên văn:

- Proposition tương đương, một phần, khác hoặc chưa đủ evidence để kết luận.
- Phạm vi rộng/hẹp; giữ hay mất điều kiện, ngoại lệ, phủ định.
- Lời tòa hiện tại, lời án được trích, lời đương sự; không khôi phục tên/citation bị che.
- Kind phù hợp với legal function, không chỉ cùng từ khóa.
- Evidence primary/support/context; heading hoặc rationale có bị nhầm thành AU độc lập không.
- Trùng legal point, AU KOS không được trích, AU bổ sung có thể hợp lệ và unresolved.

AU KOS `right-to-make-submissions` có quote kết thúc giữa từ; phải đánh giá theo nguồn đầy đủ, không bắt pipeline lặp lại lỗi artifact. Không dùng nhãn `curated/active` thay xác minh.

Các ca phân biệt cần kiểm tra sau generation:

- `011904`: presumption, yêu cầu evidence clear/convincing, hiệu quả bảo vệ, ngoại lệ không phải tự đặt mình vào nguy hiểm và nghĩa vụ giải thích evidence mâu thuẫn là các legal point khác nhau. Cùng chủ đề state protection không đồng nghĩa cùng AU.
- `045155`: nguyên tắc dùng hết grievance, ngoại lệ thẩm quyền Commissioner, lý do chính sách, quyền nhận reasons và unfairness do không được phản hồi allegation cần được đối chiếu riêng. Có AU KOS mô tả rationale; không mặc định mọi rationale đều phải loại hoặc đều phải giữ.
- `099980`: correctness là standard of review; fairness xét từng vụ là nguyên tắc về phạm vi áp dụng; quyền trình bày ý kiến là quyền thủ tục. Cùng nói procedural fairness không đủ để gộp ba ý này. Vai trò supervisory của investigation cần kiểm tra có phải legal proposition đủ độc lập hay chỉ background.

Báo token provider, request/attempt, context đọc lại, cache, latency và run lỗi. Mock không chứng minh decoder hoặc ngữ nghĩa. Chưa có đánh giá độc lập thì không báo F1/recall chất lượng tuyệt đối, không tuyên bố pipeline tốt hơn KOS.

## Tiêu chí bàn giao

- Cả 18 AU reference có mapping nguồn không mơ hồ và TARGET chứa toàn evidence; hai case không reference ghi riêng.
- Payload không chứa annotation KOS; source và atom binding được xác minh trước chạy.
- Có lệnh prepare/preflight/mock/live/compare; resume giữ output root và không gọi lại receipt hợp lệ.
- Báo cáo đặt KOS và pipeline cạnh nhau, không bỏ các trường hợp unresolved/không overlap.
- Kết luận ngữ nghĩa chỉ chốt sau live và đọc nguyên văn; việc chuẩn bị workload không được báo là chất lượng extraction đã đạt.

## Cách chạy

PowerShell, từ repo chính. Script mặc định chỉ prepare/preflight/mock/compare, không gọi endpoint:

```powershell
G:
cd G:\Git\coliee-case-retrieval
$run = "knowledge_base\pipeline_v1\outputs\kos_same_source_$(Get-Date -Format yyyyMMdd_HHmmss)"
& .\knowledge_base\pipeline_v1\experiments\run_kos_same_source.ps1 -OutputRoot $run
```

Sau khi kiểm tra local đạt, dùng cùng workload đã khóa để chạy thật:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_kos_same_source.ps1 `
    -Execute -Concurrency 2 -OutputRoot $run
```

Giữ `$run` khi resume. Không dùng output mock làm bằng chứng AU đúng, không gọi lại những receipt hợp lệ chỉ để có run mới. Script tạo comparison cả khi run incomplete nếu đã có `run.json`; đọc trạng thái thực thi trước khi diễn giải omission. Runtime giữ cổng readiness hiện tại; không deploy hoặc đổi `.env`.
