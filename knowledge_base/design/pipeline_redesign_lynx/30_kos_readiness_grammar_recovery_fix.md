# Sửa readiness, grammar và khôi phục calibration KOS

## Bằng chứng run cũ

`kos_same_source_20261018_ready/live`: 27 logical request, 24 verified, 2 pending, 1 invalid. Hai pending stage1 chạm 600 giây trước POST, không phải hết token. Request invalid stage2 trả global `complete` nhưng có anchor `unresolved`; validator từ chối đúng. Run ghi 25 POST, 49.490 token provider đã biết; hai job chưa có usage, không báo tổng hoàn chỉnh. Preflight PASS không chứng minh endpoint readiness hoặc mọi ràng buộc liên trường đã được grammar bảo vệ.

## Phạm vi sửa

1. Readiness chung có thời hạn trước dispatch; timeout lưu HTTP status/ready/error type/số lần/thời gian, không lưu credential hoặc body provider. Không gọi là `BudgetError` nếu lỗi readiness/retrieval. Hết thời hạn dừng dispatch mới, giữ checkpoint. Resume toàn cache hợp lệ không cần warmup. Giữ GET-before-POST và kiểm tra vắng job có thẩm quyền.
2. Grammar stage2 khớp validator: `complete` có anchor và chỉ `keep/reject`; `unresolved` có ít nhất một anchor unresolved nếu danh sách không rỗng; `revisit_target` giữ các tổ hợp mà contract cho phép. Không thay schema, prompt, nhãn hoặc model.
3. Recovery offline sang root mới: tái dựng workload cùng source/profile; chỉ cho payload khác EBNF. Revalidate raw response và evidence của receipt verified bằng validator hiện tại. Lưu provenance rằng generation dùng grammar cũ; không giả là đã sinh dưới grammar mới.

Không sửa run cũ, không xóa receipt invalid, không tắt kiểm hash. Hai pending chỉ requeue nếu ledger xác nhận chưa POST/chưa quan sát job tồn tại; pending có POST chưa rõ kết quả phải retrieve riêng, không tự chạy lại. Chỉ invalid do ràng buộc global/anchor vừa sửa mới được thử lại bằng payload grammar mới.

## Kế toán và kiểm thử

Ledger mới ghi prior accounting riêng với attempt/reservation/token của run cũ, tính cả generation invalid. Import cache không tạo POST/attempt giả. Ngân sách kiểm cả prior và phát sinh mới. Tổng token chưa biết giữ unknown; cache usage, generation mới và chi phí run lỗi phải phân biệt.

Test local: tổ hợp grammar đúng/sai, readiness timeout không POST và không dispatch dây chuyền, cache resume không health, tamper bị từ chối, pending có POST không tự requeue, receipt import chỉ khác grammar, giữ nguyên hash mọi file cũ. XGrammar/endpoint chưa chạy thật thì ghi rõ giới hạn; không coi mock PASS là decoder/semantic PASS.

Recovery chuẩn bị input và checkpoint; bước execute do người dùng chạy sau, không deploy hoặc inference trong đợt sửa local. Khi live hoàn tất mới đối chiếu AU KOS theo kế hoạch 29; không dùng sửa protocol để tuyên bố chất lượng AU đạt.

## Lệnh recovery offline

```powershell
G:
cd G:\Git\coliee-case-retrieval
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_target_context.recovery `
    --old-root knowledge_base\pipeline_v1\outputs\kos_same_source_20261018_ready `
    --output-root knowledge_base\pipeline_v1\outputs\kos_same_source_20261018_recovered_v1
```

Chỉ dùng lệnh trên khi thư mục đích chưa tồn tại. Sau khi recovery đã chuẩn bị và preflight đạt, dùng wrapper hiện tại với **root mới**, không chạy tiếp vào root có code hash cũ:

```powershell
& .\knowledge_base\pipeline_v1\experiments\run_kos_same_source.ps1 `
    -Execute -Concurrency 2 `
    -OutputRoot knowledge_base\pipeline_v1\outputs\kos_same_source_20261018_recovered_v1
```

Warmup đã nằm trong runner. Khi warmup hết hạn, xem `live/readiness.json`; giữ root này để resume. Không cần chạy recovery lại. Chưa có module XGrammar trong `.venv` Windows ở lần sửa này: local tests xác minh các nhánh grammar và validator, chưa thay thế kiểm tra decoder thực trên endpoint.
