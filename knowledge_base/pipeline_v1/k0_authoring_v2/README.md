# K0 authoring v2

Runner riêng dùng contract `{aus, empty_reason, next_action}` trên đúng nguồn K0 cũ: 16 scope, 58 phần evidence, 3 án. Không thay package hoặc output cũ; không chạy toàn KOS-5.

[Phạm vi, contract, cổng kiểm tra và lệnh chạy](../../design/pipeline_redesign_lynx/43_k0_v2_same_source_authoring.md).

Từ repo root:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_k0_v2.ps1
```

Mặc định chỉ prepare/preflight, kiểm native CPU grammar và dry-run; không inference. `-Mock` kiểm điều phối local. `-Execute -MaxNewRequests 1` chạy smoke thật; tiếp tục bằng `-Execute` với cùng `-OutputRoot`.

Wrapper đọc cấu hình local `knowledge_base/.env` khi chạy thật qua loader hiện có. Model/endpoint phải phù hợp identity của nguồn và controls đã khóa; không fallback model. Readiness dùng GET trước dispatch, không chạy lại chín controls.

Output root mặc định: `knowledge_base/pipeline_v1/outputs/k0_authoring_v2_20261025`. Xem `input/preflight.json`, `cpu_authoring.json`, `live/run.json`, `live/state.json`, ledger/receipt. Không inference trong quá trình triển khai. `complete` là thực thi kết thúc; phải xem riêng `work_scope_complete`, unresolved và `semantic_quality`. Mọi case vẫn partial; chưa cho phép K1 hoặc toàn corpus.

Để bảo toàn transport/receipt đã kiểm, runner tải code K0 cũ vào namespace riêng với core/tools v2; không thay global/module K0 cũ. Cổng controls dùng kiểm tra reporter đã khóa trong namespace đọc riêng, dừng trước phần ghi báo cáo. Dependency/anchor được khóa; thay đổi code phải prepare workload mới, không sửa hash trong checkpoint cũ.
