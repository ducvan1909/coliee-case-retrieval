# AG kiểm thử bản sửa M3 optimization V2

Repo `E:/Git/coliee-case-retrieval`, Python `.venv/Scripts/python.exe`; đọc AGENTS.md. User đã chốt E: và namespace pipeline_v2 thay cấu hình G:/V1 cũ. **Codex triển khai và sửa production; AG chỉ review, viết tests độc lập và chạy thử theo các lệnh người dùng chủ động giao.** Không sửa production/config/profile để làm test PASS. Chat Codex chuẩn bị lệnh, không tự gọi Modal.

## 1. Đọc bản được bàn giao

Các đường dẫn bên dưới tương đối với `pipeline_v2/`, trừ lệnh PowerShell chạy từ repo root. Đọc `docs/M3_OPTIMIZATION_V2.md` và `docs/M3_OPT_V2_TEST_REPORT.md` để xác định snapshot code, index mới và gate đã đạt. Sau đó đọc `m3_opt_v2.py`, `optimization_v2/*.py`, `deployments/modal_opt_v2/*.py`, `configs/m3_opt_v2.json`, tests `test_m3_opt_v2*.py`. Báo cáo AG trước ở `reviews/m3_opt_ag_review_v1/` là input cần phân xử, không mặc định mọi finding là lỗi production.

Baseline/code/artifact cũ read-only. Đặc biệt không sửa `m3.json`, `m3_opt.json`, index/pilot/benchmarks V1, M0-M2, raw data, labels/gold/evaluator/test sources. Không đọc/in `.env` hoặc credentials; CLI chính thức tự nạp local khi cần Modal. Chỉ ghi code test/evidence/reports vào thư mục review mới `reviews/m3_opt_v2_ag_review_v1/` hoặc suffix mới nếu đã tồn tại. SQLite audit dùng readonly URI; fault injection chỉ trên bản sao temp.

## 2. Kiểm local trước; lỗi chặn gửi lại Codex

- BM25 metadata không còn `text`; postings tạo per-document/bounded batches; relative paths hoạt động; top-hit metadata fetch theo lô, sameformula/analyzer Unicode/digits/negation/eligibility/ties so oracle độc lập.
- Kiểm index thật đủ1.024IDs/916cases, vectors khớp cache baseline và source/hash, metadata/source offsets giữ nguyên. Không dùng builder làm oracle duy nhất. So kích thước SQLite cũ–mới có evidence; đừng chỉ suy giảm từ code.
- Session không preload toàn metadata hoặc quét norm/finite của toàn vectors trong constructor. Full content hashes kiểm một lần khi mở snapshot và khi explicit verify; source hash kiểm lại lúc mở evidence. Query giữ snapshot bất biến: không tuyên bố phát hiện ngay mọi concurrent raw/index mutation khi ranking. Test thay nguồn trong session rồi mở evidence phải fail, explicit revalidate phải invalidate stale session; đừng yêu cầu globalhash perquery trái contract đã chốt.
- Toàn vẹn DB: schema/count/returned-hit ID/payload/score/dedup/query-case đúng; cheapcheck không phải fullDBattestation. Full audit riêng ở verify. Verify/open không đọc `.env`, không tạo inference; index/source không bị ghi lại. Test invalidindices/vectorrows/hash và readonly behavior.
- App unified V2 dùng document/query templates riêng, inputIDs/EOS/tokenhash/code/package/model attestation. Real search không được mở bằng simulated/failed/stale/incomplete compatibility. Latest failed preflight không để PASS cũ dùng tiếp. Receipt buộc cả document-vector parity và query-vector parity so baseline; query app mới chưa checked không được tự dùng với vectors baseline.
- Benchmark4nhóm×64uniqueID fixed, cùnginputs giữa16/32/64,3counterbalanced warm rounds;128 là stress memory riêng. Recompute perstratum input/padding/range, requests/retries/unknown usage, bounded workloads và metrics từ ledger, không suy full-corpus optimal từ pilot. OOM128 không làm mất viable results16/32/64; không giảprocessedtokens0 khi OOM/timeout.
- Thời gian phân biệt local, warm session inclRPC, startup/queue, internalCLI timer và walltime subprocess. Không so~1slocal với66scoldCLI rồi gọiend-to-end66x. Baselinev1 batch32 là fastestobserved trên mẫu cũ, không tự chốt cấu hình full.

Nếu có production defect chặn remote, dừng bước phụ thuộc và gửi repro/evidence cho Codex; không tự patch. Các lỗi checker của AG tự sửa nhưng giữ attempts để phân biệt.

## 3. Các lệnh chạy thật sau local PASS

Các thao tác Modal bên dưới là lệnh để **người dùng chủ động chạy hoặc chủ động giao AG chạy thử trong chat AG**. Không tự làm thêm deploy/retry/log/workload ngoài phạm vi được giao; không chạy full corpus. Trước mỗi bước đọc receipts hiện có, không gửi trùng job đang chạy. Nếu user chỉ yêu cầu review local thì đưa nguyên các lệnh này để user tự chạy, không gọi Modal.

Docker Qdrant cần sẵn sàng và giữ collection baseline `coliee_m3_pilot_99e66b7f9bbf4be4`; không reset/xóa collection/volumes. Lần verify local của Main nhận ConnectionError, nên kiểm bước này trước remote. Main đã chuẩn bị index mới theo tài liệu, không rebuild nếu code/profile khớp và index đã PASS. Mỗi output mới phải chưa tồn tại; nếu tên đã dùng, đổi suffix mới và ghi rõ vào report. Không sửa checksum để vượt guard stalecode. Chạy từng bước theo thứ tự, chỉ tiếp tục khi exit code bằng 0 và receipt bước trước PASS; không gửi cả chuỗi rồi bỏ qua lỗi.

```powershell
Set-Location E:/Git/coliee-case-retrieval
$env:PYTHONIOENCODING='utf-8'

# Local DB/index audit, không inference:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt_v2 verify --index-dir pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1 --full-db
if ($LASTEXITCODE -ne 0) { throw 'Local DB/index verify failed; stop before Modal' }

# App mới V2; không deploy đè hai app V1:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt_v2 deploy
if ($LASTEXITCODE -ne 0) { throw 'Deploy failed' }

# Kiểm app V2 tương thích baseline, gồm query+document parity:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt_v2 preflight --index-dir pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1 --output pipeline_v2/artifacts/m3_opt_v2_compat_20261108_v1
if ($LASTEXITCODE -ne 0) { throw 'Compatibility failed; do not benchmark or search' }

# Chỉ chạy khi compatibility trên PASS thật:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt_v2 benchmark --index-dir pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1 --compatibility pipeline_v2/artifacts/m3_opt_v2_compat_20261108_v1 --output pipeline_v2/artifacts/m3_opt_v2_gpu_benchmark_20261108_v1
if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed; inspect receipt before next step' }

& .venv/Scripts/python.exe -m pipeline_v2.m3_opt_v2 search-benchmark --index-dir pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1 --compatibility pipeline_v2/artifacts/m3_opt_v2_compat_20261108_v1 --output pipeline_v2/artifacts/m3_opt_v2_search_benchmark_20261108_v1
if ($LASTEXITCODE -ne 0) { throw 'Search benchmark failed' }
```

Đo walltime một lệnh search thật từ process launch đến kết thúc (tách khỏi internalCLI timer); output trong review dir của AG, không in credentials:

```powershell
Measure-Command {
  & .venv/Scripts/python.exe -m pipeline_v2.m3_opt_v2 search --index-dir pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1 --compatibility pipeline_v2/artifacts/m3_opt_v2_compat_20261108_v1 --query "standard of review" --limit 10 |
    Set-Content -Encoding utf8 pipeline_v2/reviews/m3_opt_v2_ag_review_v1/search_walltime_01.json
}
```

Ghi exit code riêng, không coi Measure-Command hoàn tất là search PASS. Nếu cần warm repeats chạy tối đa3lượt như kế hoạch và tên output khác nhau; ghi cả cold/warm, không bỏ lượt chậm. Preflight có gọi baseline app làm reference một lần; sau gate, document/query bình thường đều dùng app V2. Không gọi lại preflight chỉ để làm ấm container hoặc sửa failed receipt thành PASS.

Giới hạn lượt benchmark mặc định: 256 IDs ×3 sizes ×3 repeats =2.304 document encodings, thêm warmup16 và stress16+32+64+128, tổng tối đa2.560 encodings trong một lượt; không phải2.560 nguồn duy nhất. Không tự tăng repeats, thêm sizes hoặc retry vô hạn khi thiếu L4/quota. Ghi checkpoint và báo blocker nếu provider chưa sẵn sàng.

## 4. Kết quả cần trả

REPORT.md, findings.json, commands_and_results.json, independent test scripts/results, recomputed_metrics.json; fingerprint code/profile/source/index/model/app/runtime, actualrequest counts/input/padding/latency/VRAM/failures/retries/unknownusage. Full old snapshots phải giữ nguyên. Tách local correctness, real compatibility, GPU benchmark, search latency và full readiness; chưa chạy thì not_run, không đổi thành mockPASS. Không suy COLIEE F1/ngữnghĩa từ performance. Lỗi production giao Codex sửa; không mở runner full hay tự đổi profile batchsize trong review.
