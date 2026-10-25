# Phép thử A: AU sát nguồn, gom theo legal point

Ngày 2026-10-20. Chỉ triển khai A; chưa thực hiện B (đổi cap) hoặc C (đổi model).

## Giả thuyết

V2 khôi phục một số ý nhưng thêm diễn giải sai và làm mất các ý v1 đã giữ. Thử giảm mức tự do khi viết lại và gom rule với rationale/điều kiện của cùng một legal point. Không giả định cách này chắc chắn khắc phục được giới hạn năng lực model.

Nguồn thiết kế: [pilot claim-first](31_claim_first_au_pilot.md), [v2](32_claim_first_v2_fidelity_coverage.md), review nguồn tại `knowledge_base/pipeline_v1/outputs/au_claim_v2_local_ready_20261019/semantic_review_20261019_v2/REVIEW.md`.

## Biến thử và phần giữ nguyên

Profile `claim_first_v3_source_close`; wire vẫn `au-claim-v1`. Chỉ đổi hướng dẫn và few-shot. Giữ 16 TARGET, nguyên văn source/atoms/context, model Qwen3.5-9B, schema, kinds, cap 3 AU, 800 output token, budget, grammar, cache/checkpoint và cơ chế mở context. Không tự thêm trường quote, subject, checklist hoặc lượt kiểm tra LLM.

Đây là phép thử kết hợp hai thay đổi được chấp thuận: cách viết sát nguồn và cách gom legal point. Nếu có khác biệt, chưa quy riêng cho một yếu tố. Chưa thử nâng cap, thêm NER, đổi scheduler/reranker hoặc NN–AU match.

## Cách tạo AU

1. **Claim sát nguồn:** giữ chủ thể, modality, phủ định, quan hệ nguyên nhân, điều kiện/ngoại lệ và các thành phần kết hợp. Chỉ đổi cách diễn đạt khi giữ được nghĩa; không tự gán đại từ cho người/cơ quan chưa rõ. Vẫn tạo mệnh đề pháp lý có thể đọc độc lập, không chỉ trả quote hoặc span ID.
2. **Gom đúng điểm:** một rule với rationale hoặc exception làm rõ chính rule đó thường là một AU. Không chia các câu mở đầu, slogan policy hoặc vị trí điều luật thành nhiều AU khi chúng chỉ hỗ trợ một điểm. Tách quyền, nghĩa vụ, tiêu chuẩn hoặc kết luận áp dụng độc lập. Rationale pháp lý có ích vẫn có thể là legal point riêng nếu không chỉ lặp lại.
3. **Giữ phạm vi:** không biến kết luận vụ cụ thể thành ngoại lệ tự động cho mọi vụ; không coi lời bên tranh tụng là kết luận tòa; không suy current-court adoption từ việc trích một authority.
4. **Evidence:** các ID cùng hỗ trợ toàn claim và limits. Host tiếp tục xác minh nguồn/offset, không gắn nhãn đã kiểm ngữ nghĩa chỉ vì evidence hợp lệ.
5. **Context:** chỉ hỏi câu hỏi thiếu cụ thể, trung tính; không mặc định Board/court đã đưa holding nào. Không mở chỉ để khôi phục tên citation bị che. Không có thêm vòng đọc lại mặc định.

Không auto-skip vùng không citation hoặc thiếu marker. Không gán nhãn accepted từ prompt hay số AU trả về. Không bắt buộc mỗi TARGET có AU.

## Triển khai và kiểm tra local

- `au_claim/contracts.py`: profile mới và few-shot hư cấu, thay nội dung thay vì nối thêm prompt dài. Mục tiêu không dài hơn prompt v2 (3.979 UTF-8 byte); đây là chỉ báo kích thước, không phải đo token.
- `au_claim/README.md`: hướng dẫn dùng root mới, warmup tích hợp, không resume root v1/v2 với code mới.
- `tests/test_au_claim.py`: giữ kiểm thử behavior, parse/validate few-shot với catalog tổng hợp, wire/caps/source/context bất biến, fingerprint mới, từ chối workload cũ, mock/resume và giới hạn semantic của validator.
- Main chạy wrapper local toàn 16 TARGET và kiểm diff payload so v2, kiểm hash artifact lịch sử. Các test này không chứng minh cách gom hoặc attribution của model đã tốt hơn.

Runtime, server, `.env` và các run đã có không sửa. Không cần deploy vì chỉ đổi client prompt. Mặc định script chạy mock, phải có `-Execute` mới chạy thật.

## Đối chứng live và tiêu chí phân xử

Chạy cùng 16 TARGET ở root mới sau local. So với v1 (24 AU, 15.563 token, 16 request) và v2 (34 AU, 20.863 token, 17 request) bằng artifact đã lưu. Comparator hiện vẫn ghép KOS và primary/support; bảng claim-first v1/v2/A cần đọc riêng, không nhầm baseline.

Đọc toàn bộ output; không dùng số AU tăng/giảm hay overlap làm chất lượng. Ưu tiên:

| Kiểm tra | Ví dụ calibration, chỉ dùng khi review |
|---|---|
| Không đổi chủ thể/đối tượng | applicant/police ở 011904 [16]; persuasive approach ở [20]; Board/court ở [26], [28] |
| Giữ điều kiện/ngoại lệ và conjunction | reasonableness [10]; disclosure/withholding 045155 [21] |
| Không mất legal point khi gom | exception exhaustion 045155 [10]; correctness 099980 [96]; submissions [98] |
| Không tạo AU chỉ từ context chung | 011904 [26]; 045155 [14] cần xem có thực sự thiếu kết luận không |
| Gom không làm lệch nội dung | rule/rationale 045155 [8], [10]; quyết định không xét jurisdiction vì fairness đủ quyết định 099980 [93] |

Các ví dụ trên không được đưa đáp án vào few-shot. Bản A vẫn phải giữ các ý tốt chưa liệt kê, không chỉ vượt một danh sách lỗi đã biết. Không tự hợp nhất hoặc sửa AU model sau khi chạy để tăng điểm.

Báo input/output token, request/context/retry, kết quả lỗi và latency/warmup. Claim ít hơn không tự chứng minh tiết kiệm nếu bỏ ý. Chưa chọn A nếu còn lỗi nghiêm trọng về chủ thể/ngoại lệ hoặc cải thiện một nhóm bằng cách làm mất nhóm khác.

Nếu A vẫn diễn giải sai trên input rõ: dừng nối dài prompt; thiết kế đối chứng C cùng TARGET/prompt/contract để phân biệt năng lực model. Nếu gom đúng nhưng vẫn thiếu các legal point độc lập vì cap, mới thử B. Hai bước đó chưa được triển khai trong đợt A. Cần tập giữ riêng trước kết luận tổng quát hoặc mở rộng corpus.
