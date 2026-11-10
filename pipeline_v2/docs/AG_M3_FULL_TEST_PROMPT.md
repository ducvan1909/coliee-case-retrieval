# AG review/test và chạy runner full M3

Repo `E:/Git/coliee-case-retrieval`; Python `.venv/Scripts/python.exe`. Đọc AGENTS.md, `pipeline_v2/docs/M3_FULL.md` và `M3_FULL_TEST_REPORT.md`. User chốt checkout E: và namespace pipeline_v2. Codex viết/sửa production; AG chỉ review/test và chạy code đã freeze. Không sửa production/profile/seals/raw/gold để làm PASS.

## Local trước remote

Đọc `pipeline_v2/full_corpus/*.py`, `m3_full.py`, `configs/m3_full.json`, các tests `test_m3_full*.py` và evidence `reviews/m3_full_validation_v1/`. Giữ nguyên pilot/V1/V2; đối chiếu fingerprints trước/sau. Chỉ ghi scripts/tests/reports mới vào `pipeline_v2/reviews/m3_full_ag_review_v1/`, fault injection trên bản sao temp, SQLite audit readonly.

Kiểm độc lập schedule gồm415.693 unique passages /7.708 án, sort theo full_input_tokens rồi ID, batch64,6.496 batches, batch cuối13; metadata không rawtext, hash/offset khớp nguồnM2. Không lấy builder làm oracle duy nhất. Main cung cấp `audit_full_plan.py` nhưng AG cần tự review/audit các invariants quan trọng.

Plan thật Main đã audit PASS: `artifacts/m3_full_train_20261108_v1`, SQLite4.357.505.024bytes; dự kiến55.346.360inputtokens /55.360.576paddedtokens. Không rebuild plan này nếu fingerprint khớp. Vector FP32 thuần khoảng4,26GB ngoài SQLite/cachemetadata và DB; ghi dung lượng trống tại nơi cache và Docker data trước chạy. Không tự xóa/di chuyển dữ liệu hoặc đổi cấu hình để vượt lỗi dung lượng.

Test crash sau cachecommit trước DBupsert, sau upsert trước progress; resume không inference lại committed batch. Thiếu/hỏng committed cache fail. Orphan recovery chỉ khi run explicitlyresume, verify readonly không sửa sidecar. Journal phải durable trước upsert. Mock run không thể mở khóa/cache-adopt vào realrun; mixed injected/real runtime bị chặn. Code/profile/source/receipt drift phải fail; các lệnh local không đọc.env hoặc import/callModal. Lock chống haiwriter. Unknown usage/started attempts phải giữ lại, không quy thành0.

DB on-disk, collectionfull riêng; schema/version/foreign IDs/payload checked trước inference. Verify bounded64vectors, đủ exactmembership/payload/cachevector; không dùng old scroll/verify/restore helper gom toàn DBvectors vào RAM. Test shortresponse cócorruption, duplicates, ngoạiIDs, wrongpayload/vector, paginationcycleA→B→A. Lỗi production chặn bước phụ thuộc: gửi Codex repro/evidence, không patch.

## Chạy thật khi người dùng chủ động giao prompt này

Đây là lệnh full inference thật, không phải dryrun. Nếu chỉ được giao review local, in lệnh để user tự chạy. Trong phiên được giao chạy: dùng đúng plan Main đã dựng, không replan/rebuild khi code/profile còn khớp. Không redeploy app V2, không preflight lại chỉ để warmcontainer. Nếu receipt/code không còn khớp, dừng báo Codex thay vì sửa checksum. Docker Qdrant phải sẵn sàng; giữ nguyên mọi collection/volume cũ. Không tự reset hoặc đổi batch/model.

Chạy từng bước theo thứ tự; chỉ tiếp khi exit0 và kết quả đúng contract. Tạo reviewdir nếu chưa có; nếu đã có, dùng suffix mới và cập nhật đường dẫn evidence. Không chạy song song hai lệnh run.

```powershell
Set-Location E:/Git/coliee-case-retrieval
$env:PYTHONIOENCODING='utf-8'
$fullRun='pipeline_v2/artifacts/m3_full_train_20261108_v1'

# Local, không gọi Modal:
& .venv/Scripts/python.exe -m pipeline_v2.m3_full status --run-dir $fullRun
if ($LASTEXITCODE -ne 0) { throw 'Plan drift; stop' }

# Canary: tối đa2batches cần xử lý trong invocation này, cache trước DB.
& .venv/Scripts/python.exe -m pipeline_v2.m3_full run --run-dir $fullRun --max-batches 2
if ($LASTEXITCODE -ne 0) { throw 'Canary failed; collect evidence, do not launch full' }

& .venv/Scripts/python.exe -m pipeline_v2.m3_full status --run-dir $fullRun
if ($LASTEXITCODE -ne 0) { throw 'Status failed' }

# Sau canary PASS: cùng run-dir, resume cache, xử lý phần còn lại.
& .venv/Scripts/python.exe -m pipeline_v2.m3_full run --run-dir $fullRun
if ($LASTEXITCODE -ne 0) { throw 'Full stopped; retain cache and ledger, report blocker' }

# Audit DB/cache độc lập với completed flag, local, không inference:
& .venv/Scripts/python.exe -m pipeline_v2.m3_full verify --run-dir $fullRun
if ($LASTEXITCODE -ne 0) { throw 'Full verification failed' }
```

Canary `stopped_at_batch_boundary` là partial hợp lệ, không phải lỗi. `--max-batches` tính batches phải inference/upsert trong invocation, không tính cached batches đã xác minh DB và được skip; chạy lại không mắc mãi ở2batches đầu. Chỉ `full_vectors_ingested_verified` rồi independentverify PASS mới đủ nghiệm thu ingestion; `status` không tái kiểm DB.

Lưu stdout/stderr/exitcode/walltime từng lệnh vào reviewdir; không coi shell hoàn tất là PASS. Nếu mất chat/kết nối, kiểm process/progress/ledger trước, không launch trùng job. `status` là local nhưng có kiểm hashes/provenance nên có chi phí; không poll mỗi giây. Sau lỗi provider/OOM/quota/timeout, giữ ledger và báo blocker, không retry vô hạn hoặc tự giảm batch. Khi được giao resume, dùng lại chính `run --run-dir`, không xóacache/replan để tránh mất evidence. Unknown usage có thể phản ánh request đã xử lý nhưng chưa nhận response; không tuyên bố tránh tuyệt đối mọi duplicate processing sau timeout.

Fullrun có thể kéo dài nhiều giờ và CLI chỉ in summary cuối; không giữ một request chat/tool chờ vô hạn. Dùng cơ chế process/session bền của môi trường AG và kiểm progress theo từng khoảng, hoặc bàn giao lệnh foreground cho user chạy trong terminal nếu tool không giữ được process lâu. Nếu mở helper nền trên Windows, dùng cửa sổ hidden và lưu PID/command/starttime/stdout/stderr/exit receipt; không mở nhiều writer hoặc giết job khi chỉ bị chat API stream timeout. Timeout của chat không chứng minh job inference đã dừng. Không tự thêm dịch vụ theo dõi/automation.

## Bàn giao

REPORT.md, findings.json, commands_and_results.json, independent tests/results và recomputed_metrics.json. Tính lại requests/tokens/padding/latency/errors/started attempts từ ledger bằng streaming SQL, không nạp toàn receipts/vectors vào RAM. Phân biệt newinference/cachehit/upsert, real/simulated, partial/complete; ghi canary/resume/failures cả lần không thành công. Tổng lý tưởng khôngfail/cacheimport là6.496 requests, không cộng lại2canary đã được reuse. Số input/padding phải khớp plan khi mọi batch chỉ encode1lần.

Kết luận riêng: local correctness; realcanary/resume; full ingestion; full DB membership/cache verification; memory/usage; remaining scope. Chưa có fullhybridsearch/agent/goldF1 trong runner này. Không gọi pilot snapshotrestore cho DBfull vì helper cũ gom bytes/vectors vào RAM; fullsnapshot/restore chưa thuộc lần chạy này. Không suy semantic quality từ schema/hash/PASS.
