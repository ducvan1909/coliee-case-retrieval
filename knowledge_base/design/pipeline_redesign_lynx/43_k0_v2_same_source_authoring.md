# K0 v2: authoring trên cùng nguồn cũ

## Phạm vi và mục tiêu

Triển khai riêng ngày 2026-10-25, tiếp nối contract đọc/assessment v2 ở tài liệu 41 và phục hồi báo cáo ở 42. Mục tiêu là thử khả năng soạn AU theo legal point trên nguồn án thật sau khi controls tổng hợp đã chạy được; chưa kết luận chất lượng AU hoặc mở K1.

Nguồn đối chứng cố định là `outputs/k0_ready_20261023/input/workload.json`, không chọn lại từ KOS:

| Case | Scope | Phần evidence |
|---|---:|---:|
| 011904 | 8 | 21 |
| 045155 | 5 | 30 |
| 099980 | 3 | 7 |
| Tổng | 16 | 58 |

Chỉ dùng nguyên văn và địa chỉ nguồn đã thực sự được đưa vào K0 cũ. Không lấy claim, nhãn AU hoặc câu trả lời từ KOS/reviewer làm nguồn. Đây là phạm vi tiếp xúc nguồn bằng nhau, không bảo đảm lịch đọc, số lượt đọc hoặc tổng token bằng nhau. Cả ba án vẫn `partial` vì scope không phủ toàn án.

## Contract và trách nhiệm

- Model trả đúng ba trường `aus`, `empty_reason`, `next_action`. Mỗi AU gồm `claim`, `kind`, `evidence_ids`, `limits`, có thể có `replace_id` khi sửa draft đã tồn tại.
- Model nhóm rule–rationale–exception theo legal point và giữ attribution. Không áp quota AU; không buộc một AU trên một scope.
- Host giữ catalog nguồn, hash/offset, tool đọc nguồn, draft, ngân sách và checkpoint. Không có `assessed_scope_ids` do model trả.
- Tool chỉ hoạt động trong union nguồn đã khóa: `open_region`, `search_source`, `get_drafts`, `finish_case`. Search preview và draft không tự trở thành evidence.
- Thiếu context giữ unresolved, kể cả response chứa AU có ích. Đọc được nguồn không đồng nghĩa đã đánh giá đầy đủ; kết thúc thực thi không đồng nghĩa hoàn tất assessment.
- `holding` cần cơ sở cho thấy đó là quan điểm/phán quyết tương ứng; nếu chưa đủ cơ sở, `kind` được phép null. Cảnh báo subtype của control refund không bị đổi thành kết quả đạt ngữ nghĩa.

Giữ model và cấu hình thinking của workload/endpoint cũ; không tự đổi model. Claim/limits có mục tiêu độ dài mềm, không gọi sửa vì vượt ngưỡng.

## Thực thi và cổng kiểm tra

Module mới là `knowledge_base.pipeline_v1.k0_authoring_v2`; wrapper là `experiments/run_k0_v2.ps1`. Không sửa package generation hoặc artifact K0/controls cũ.

1. Prepare khóa source union, dependency, prompt/grammar và identity vào workload mới.
2. Preflight local kiểm source, hash, provenance, payload và budget. Controls 9 tình huống là điều kiện giao thức cho phép thử có giới hạn, không phải nhãn gold hay bằng chứng chất lượng bản án.
3. Trước live, kiểm grammar native CPU và EOS trên bundle nguồn thật, tách khỏi mock. Không được lấy mock PASS thay cho kiểm endpoint/ngữ nghĩa.
4. Run mặc định không inference; mock chỉ kiểm điều phối. Chỉ `-Execute` mới gửi yêu cầu. Smoke có giới hạn request và tiếp tục tại cùng output root.
5. Resume đọc receipt hợp lệ và dựng lại state, không phát lại request đã hoàn tất. Giữ cấu hình/binding nhất quán, không tái chuẩn hóa kiểu số làm thay digest; không ghi credential vào artifact.

Giới hạn pilot: 12 POST tối đa, input 6.000 token/request, output 800 token/request, tổng 30.000 token; tính cả lỗi/retry. Host dùng bộ đếm bảo thủ cho admission, báo riêng usage provider và phần chưa biết. Chạm cap thì checkpoint/incomplete, không ghi là tiết kiệm. Warmup/readiness không phải bảo đảm endpoint sẽ luôn sẵn sàng.

## Đầu ra và đánh giá sau live

Workload và preflight; bundle/report grammar; ledger/receipt từng request; state nguồn/draft; `run.json` với request, token, latency, reading coverage, unresolved và các lỗi. Artifact kiểm thử local nằm riêng với live.

Đối chiếu K0 cũ và K0 v2 theo cùng source union: số legal point có nguồn hỗ trợ, bỏ sót, rule–rationale–exception, attribution, kind và độ khái quát; báo token/request kể cả run lỗi. Không đánh giá chỉ bằng số AU: K0 cũ trả 0 AU không có nghĩa v2 sinh càng nhiều càng tốt.

Không tự chạy model trong đợt triển khai code. Chỉ cung cấp lệnh sau khi kiểm local đạt. Ngữ nghĩa trên án thật vẫn chờ output live và review riêng; chưa mở toàn KOS, toàn corpus, retrieval hoặc reranker.

## Lệnh sử dụng

Kiểm local trước, không inference:

```powershell
G:
cd G:\Git\coliee-case-retrieval
$run = 'knowledge_base\pipeline_v1\outputs\k0_authoring_v2_20261025'
& .\knowledge_base\pipeline_v1\experiments\run_k0_v2.ps1 -OutputRoot $run
```

Sau khi local đạt, chạy smoke một request mới. Wrapper kiểm native CPU, controls đã lưu và readiness trước dispatch; không cần gọi lại chín controls:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_k0_v2.ps1 `
    -Execute -MaxNewRequests 1 -OutputRoot $run
```

Kiểm output smoke rồi tiếp tục tại đúng root, không xóa cache hoặc tạo run khác để tránh checkpoint lỗi:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_k0_v2.ps1 `
    -Execute -OutputRoot $run
```

Không thêm `-Mock` vào lệnh live. File `live/run.json` là kết quả thật; `mock/run.json` chỉ là kiểm thử điều phối. Hạn mức là tích lũy của run, không được làm mới chỉ bằng cách gọi lại script.

## Checkpoint local ngày 2026-10-25

- Wrapper mặc định đã thực thi prepare/preflight/native CPU/dry-run thành công, chưa tạo `live/` và chưa gọi model.
- Grammar: 4 bộ gồm 3 payload nguồn thật và 1 nhánh sửa draft; 7 positive/10 negative và EOS PASS, inference 0.
- Suite kết hợp chạy 35 test: 33 PASS, 2 lỗi assertion trong test (tên trường thống kê và escape của literal EBNF). Sau khi sửa riêng test, cả 2 test bị ảnh hưởng đã chạy lại PASS; không sửa production để chiều test.
- Mock kiểm checkpoint/resume có POST giả lập tích lũy 1→2→3→3; receipt hoàn tất không được phát lại. Mock thiếu context trả `execution_complete=true`, `work_scope_complete=false` đúng chủ đích.
- Cổng controls đọc offline hợp lệ; 72 file K0/controls lịch sử giữ nguyên hash. Bằng chứng: `outputs/k0_authoring_v2_20261025/LOCAL_VALIDATION.json` và các report dưới root này.
- Payload ban đầu chứa đủ cả union scope của từng case, reservation input lần lượt 3.759/3.597/2.379; đây là số host dự trù, không phải usage provider hay giá tiền. Chưa biết model sẽ mở lại nguồn bao nhiêu lần.

Trạng thái bàn giao: sẵn sàng smoke thật bằng lệnh ở trên. Chưa có AU v2 trên án thật để đánh giá hoặc so chất lượng với KOS/K0 cũ.
