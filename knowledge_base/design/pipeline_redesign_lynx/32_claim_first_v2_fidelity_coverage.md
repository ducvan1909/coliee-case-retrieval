# Claim-first v2: giữ nghĩa và đủ legal point

## Phạm vi

Sửa hướng dẫn và few-shot trong module thử `au_claim`; không thay pipeline mặc định, model Qwen3.5-9B, wire `au-claim-v1`, grammar, taxonomy, cap 3 AU/TARGET, output cap 800 hoặc transport. Profile mới là `claim_first_v2`. Không thêm lượt validate mặc định, NER hay verifier. Chưa mở rộng workload hoặc gọi inference trong đợt sửa local.

Đầu vào thiết kế: [pilot claim-first](31_claim_first_au_pilot.md), kết quả `knowledge_base/pipeline_v1/outputs/au_claim_kos16_20261019_ready/live/run.json` và đánh giá `semantic_review_20261019_v1/REVIEW.md` trong cùng root.

## Thay đổi

1. Claim giữ bên có quyền/nghĩa vụ, hành động, điều kiện và ngoại lệ. Người phát biểu quy tắc không nhất thiết là bên thực hiện nghĩa vụ. Không thay đại từ bằng chủ thể suy đoán.
2. Điều kiện làm đổi nghĩa phải được giữ trong claim; limits bổ sung phạm vi và giới hạn, không chỉ ghi tên nguồn. Mỗi AU phải đọc riêng được, không dựa AU khác để khôi phục ngoại lệ bị bỏ.
3. Model xét các legal point độc lập trong TARGET trước khi kết thúc ngay trong cùng lượt trả lời. Không xuất suy luận/checklist, không ép đủ ba AU. Gom rationale hỗ trợ với legal point tương ứng; không gom quyền, tiêu chuẩn và nghĩa vụ độc lập thành topic chung.
4. Phân biệt dữ kiện tài liệu thuần với quy tắc/kết luận áp dụng có giá trị authority. Không cấm rationale pháp lý hoặc holding theo tình tiết riêng; không biến ví dụ thực tế thành ngoại lệ tự động cho mọi vụ.
5. Evidence IDs hỗ trợ cả claim và limits. Không tăng enum và không ép kind khi không chắc; sai kind không được chữa bằng cách bịa nội dung.
6. Thay few-shot đơn giản bằng các ví dụ tổng hợp ngắn, khác miền benchmark, có nhiều câu và các ranh giới trên. Không đưa đáp án KOS vào payload.

## Kiểm thử local

- Giữ wire, grammar, cap và luồng context như v1; xác minh JSON của ví dụ bằng validator với catalog tổng hợp.
- TARGET, source, hash và alias không đổi; không đưa annotation KOS vào model.
- Profile/prompt hash thay đổi làm request identity thay đổi. Workload/receipt v1 không được tái sử dụng làm kết quả v2; thử bằng root mới.
- Mock toàn 16 TARGET, resume và comparator chạy không network; lịch sử v1 và baseline primary/support giữ nguyên bytes.
- Kiểm thử phải ghi rõ validator vẫn chấp nhận claim sai nghĩa nếu JSON/ID hợp lệ. Không viết test để ngụ ý grammar đã ngăn sai chủ thể, omission hay mất ngoại lệ.
- Báo kích thước prompt bằng byte/ký tự và chi phí payload dự kiến; chỉ usage provider mới là token thực.

## Đối chứng live sau local

Chạy cùng 16 TARGET/model/schema/cap, concurrency 2, root mới. Warmup đã có trong script `knowledge_base/pipeline_v1/experiments/run_au_claim.ps1`. Giữ root v2 khi resume. Không cần deploy lại endpoint vì chỉ đổi hướng dẫn client.

Run v1 làm đối chứng ngữ nghĩa: `outputs/au_claim_kos16_20261019_ready/live/run.json` (16 request, 24 AU, 15.563 provider token). Comparator hiện có vẫn đối chiếu baseline primary/support; không nhầm cột baseline đó với claim-first v1. So v1/v2 dựa các artifact đã lưu và đọc nguồn; không sửa hash lịch sử để ép chúng qua preflight code mới.

Các trường hợp đã biết cần đọc lại:

| Loại | Vùng kiểm tra |
|---|---|
| Chủ thể nghĩa vụ | 011904 [28], Board/Court |
| Ngoại lệ | 045155 [21], disclosure và 27(3) |
| Điều kiện kết hợp | 011904 [10], các thành phần reasonableness |
| Omission | 011904 [26]; 045155 [10]; 099980 [96], [98] |
| Fact/rationale/holding | 011904 [25]; 045155 [10], [14] |
| Claim và limits cùng có evidence | 011904 [20]; 045155 [8], [9] |

Đọc toàn bộ kết quả, không chỉ các lỗi đã biết: giữ các điểm tốt của v1 như danger rationale, fairness theo từng vụ và quyền trình bày ý kiến. Không lấy exact claim match hay evidence overlap làm semantic score.

Chưa promote nếu còn sai nghiêm trọng về chủ thể hoặc ngoại lệ. Nếu cải thiện lỗi đã biết nhưng tạo omission khác, không coi là thắng. Tính tổng provider token, request, retry, context và run lỗi; không áp ngưỡng giảm 30% bằng cách đánh đổi mất ý. Prompt v2 có thể dài hơn v1: đo tổng workload trước khi kết luận đáng chi phí.

Đây là calibration sau khi đã xem lỗi. Cần mẫu giữ riêng trước kết luận tổng quát; không gọi đây là chất lượng trên toàn án hay retrieval. Chưa có inference v2 hoặc kết luận chất lượng từ kiểm thử local.
