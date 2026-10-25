# Controls cho cải tiến KOS — kế hoạch39

Module riêng; không sửa K0 v1, không deploy và không gửi bản án trước khi controls đạt.
Model/endpoint lấy từ `knowledge_base/.env` hiện có; phải khớp identity K0.

- `prepare`: khóa một positive-only giữ grammar cũ và9 controls của wire có `empty_reason`.
- `preflight`: khóa source/parent/code/payload/tokenizer và dự toán cả10request.
- CPU replay dùng helper đã có, tokenizer Qwen đúng revision, XGrammar0.2.1 và EOS248044/248046.
- `run-positive --execute`: chỉ gửi một job. Readiness/warmup chỉ GET, tối đa600s.
- `run-balanced --execute`: chỉ gửi9job sau khi positive có receipt hợp wire **và Main review nội dung**. Không tự pass vì AU_count>0.

Cả hai stage dùng cùng `live/` và binding toàn bộ joblist. Trần12POST, input6000/output800 mỗi request, tổng reserve và usage thực mỗi chỉ số<=30000. Không reset bằng resume. Intent trước POST, receipt bất biến trước ledger; kết quả hoàn tất không gọi lại. Unknown usage cho truy hồi GET nhưng chặn POST mới; không blind retry sau timeout/404.

```powershell
G:
cd G:\Git\coliee-case-retrieval
$run = "knowledge_base\pipeline_v1\outputs\kos_authoring_controls_20261024"

# Root này đã prepare; để tạo workload khác phải có ngân sách riêng được cho phép.
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.kos_authoring_controls preflight --output-root $run
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.kos_authoring_controls run-positive --execute --output-root $run
```

CPU report phải khớp hash bundle trước run-positive/run-balanced. Positive control fail thì dừng; không gọi balanced hoặc bản án để bù. Giữ cùng root để truy hồi nếu endpoint chưa ready, không tạo job mới để retry.

Ví dụ JSON được tạo từ nguồn tổng hợp khác nguồn controls, ID demo không làm evidence. `lexical_concept_hints` chỉ giúp đọc kết quả, không là entailment checker. Main review là agent review, không human gold. CPU/mocks chỉ kiểm cơ chế. Report toàn bộ token kể cả controls thất bại và startup warmup riêng nếu quan sát được.

Đây mới là module controls và transport của39. Authoring/ReadAssessment/validate0AU trên bản án chỉ triển khai/thực thi sau khi controls cuối đạt; chưa có phép mởK1.
