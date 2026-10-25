# Mốc 1 — baseline AU đủ KOS-5

Module dùng source/SourceBlock/SentenceAtom đã có, không đọc KOS annotation để chọn target. Manifest hiện tại có 436 request: 011904=41, 013009=21, 013948=68, 045155=90, 099980=216. Mỗi target là block hoặc slice theo atom đã được tạo ở Plan 04. Heading/editorial không bị bỏ chỉ vì loại block.

Baseline `m1-sourceblock-all-v1` thích nghi từ P2a: không ContextHint, context trước/sau theo whole atom tổng tối đa 800 ký tự. Không sao chép toàn bộ batch nhiều target vào mỗi request. Đây là cấu hình riêng, không dùng kết quả lịch sử P2a/P2b làm phép so sánh cùng workload.

Model Qwen/Qwen3.5-9B, không thinking; giữ prompt/compact schema hiện tại, output cap 800, tối đa ba AU/request. Runner dùng jobs và `host_validated`, có warmup/schema probe, cache/resume và ledger hiện có. Mốc1 không chạy repair toàn bộ và không promote AU thành semantic accepted.

## Chuẩn bị local

```powershell
G:
cd G:\Git\coliee-case-retrieval
$py = ".\.venv\Scripts\python.exe"
$manifest = "knowledge_base\pipeline_v1\manifests\au_compact_kos5_full_m1.v1.json"
$run = "knowledge_base\pipeline_v1\outputs\milestone1_kos5_$(Get-Date -Format yyyyMMdd_HHmmss)"

& $py -m knowledge_base.pipeline_v1.milestone1 build --output $manifest
if ($LASTEXITCODE -ne 0) { throw "Build chưa PASS." }

& $py -m knowledge_base.pipeline_v1.milestone1 preflight `
    --manifest $manifest --planned-budget --output-root $run
if ($LASTEXITCODE -ne 0) { throw "Preflight chưa PASS." }
```

`--planned-budget` là lựa chọn rõ ràng dùng dự phòng toàn workload, thay vì trần env của pilot 10 target. Không sửa `.env`. Nếu không có flag này, preflight kiểm tra budget hiện tại trong `.env` và báo fail nếu thiếu. Xem `planned_budget`, `approved_budget`, `costs` trong `preflight_ready.json` trước khi chạy.

Preflight mới: 436 source requests, dự phòng input 3.593.190 và output 348.800. Input là **UTF-8 bytes của full prompt +128 framing mỗi request**, không phải token thực từ provider. Giới hạn input bảo thủ 11.488 cộng output 800 cho context deployment 12.288; request lớn nhất có dự phòng input 11.442. Các con số này không chứng minh đủ rẻ cho toàn corpus. Warmup/probe là chi phí riêng.

## Chạy thật sau PASS

Lệnh này gọi inference trả phí trên toàn bộ năm án; warmup đã nằm trong runner:

```powershell
& $py -m knowledge_base.pipeline_v1.milestone1 run `
    --execute --manifest $manifest `
    --preflight "$run\preflight_ready.json" `
    --output-root $run
```

Để resume, giữ nguyên `$run`, manifest, prompt/model và preflight. Lệnh không tự tăng budget hoặc tự sửa kết quả semantic. Retry outage là tùy chọn `--retry-provider-unavailable`; nếu hết trần, giữ incomplete và ledger, không tính là tiết kiệm hoặc đã xử lý đủ.

Source/hash/binding hoặc preflight thay đổi phải chuẩn bị lại ở output mới. Không dùng lại cache khác identity. Lock chặn hai lượt chạy cùng output root; lock tồn tại sau hard kill cần kiểm tra tiến trình/job trước khi xử lý thủ công, không tự xóa và dispatch lại.

## Đối chiếu KOS local

Chạy cả khi run incomplete để xem phần đã xử lý và lỗi; không gán các vùng chưa xử lý thành false negative:

```powershell
& $py -m knowledge_base.pipeline_v1.kos_comparison compare `
    --run "$run\run.json" `
    --source-store knowledge_base\pipeline_v1\outputs\source_store_v1 `
    --kos-root G:\Legal-AI\kos_sample `
    --kos-manifest knowledge_base\pipeline_v1\manifests\selected_kos_manifest.v1.json `
    --workload-manifest $manifest `
    --output-root "$run\comparison"
```

Kết quả `comparison.json` và `comparison.html` gồm AU/evidence, heuristic overlap candidates, khác kind/claim/attribution, split/merge candidates, coverage và cost. KOS 61 file/18 AU trong snapshot hiện tại chỉ là tham khảo; query case có thể không có AU annotation KOS. Overlap không chứng minh legal equivalence; không gọi số khác biệt là precision/recall gold.

`needs_split`, unresolved, unrun và quote ambiguity hiển thị riêng. `complete` của compact protocol không tự làm Mốc1 complete: wrapper kiểm tra toàn bộ request identity và coverage state. `semantic accepted` vẫn false. Token thực lấy từ receipt/ledger, không cộng hai lần; unknown usage và warmup/probe/history được ghi riêng, không suy USD khi chưa có billing.

## Kiểm thử local

Warmup chờ có giới hạn khi endpoint trả 429/503 hoặc 409 với đúng thông báo
`Inference busy`. Lỗi 409 khác không được retry. Báo cáo warmup chỉ lưu mã HTTP,
`retryable` và diagnostic, không lưu body lỗi/credential. CLI báo rõ
`warmup_failed_before_source_dispatch` cùng đường dẫn báo cáo khi chưa sẵn sàng.
Thay đổi warmup có hiệu lực local; thay đổi mutex worker cần deploy lại gateway.
Khi chạy lại dùng cùng output root để giữ identity/cache; không xóa job đang chạy
phía server để vượt trạng thái busy.

```powershell
& $py -m unittest knowledge_base.pipeline_v1.tests.test_milestone1_independent `
    knowledge_base.pipeline_v1.tests.test_kos_comparison `
    knowledge_base.pipeline_v1.tests.test_kos_comparison_independent -q
```

Chưa chạy full 436 request trong đợt triển khai. Smoke đối chiếu sử dụng output cũ chỉ xác nhận adapter/HTML hoạt động, không thay thế kết quả thực nghiệm Mốc1.
