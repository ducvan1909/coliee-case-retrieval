# AG review độc lập bản tối ưu M3 và kết quả benchmark

Repo `E:/Git/coliee-case-retrieval`, namespace `pipeline_v2/`, Python `.venv/Scripts/python.exe`. Đọc AGENTS.md; đường dẫn G:/scope V1 cũ đã được user thay bằng E: và pipeline_v2.

**Codex triển khai/sửa production; AG chỉ review và viết/chạy tests local độc lập. Mọi thao tác Modal phải đưa lệnh để user tự chạy.** Không gọi SDK/CLI deploy, inference, log hoặc quản lý app Modal. Không tự chạy lại benchmark trả phí. Không mở full embedding, không đọc gold/labels/evaluator/test sources hoặc credentials/.env.

## Đầu vào thật

- `docs/M3_OPTIMIZATION.md`, `configs/m3_opt.json`, `m3_opt.py`, `optimization/*.py`, `deployments/modal_opt/*.py`, các tests `test_m3_opt*.py`.
- Index `artifacts/m3_opt_index_20261107_v2/`: manifest/seal, lexical.sqlite3, vectors.npy. V1 là output lỗi dở, không dùng thay v2.
- GPU run `artifacts/m3_opt_gpu_benchmark_20261107_v1/`: benchmark_plan.json, benchmark_progress.json, benchmark_result.json, ledger.sqlite3.
- Search run `artifacts/m3_opt_search_benchmark_20261107_v1/`: search_benchmark.json, ledger.sqlite3.
- `reviews/m3_opt_validation_v1/`, gồm kiểm lexical equivalence và local probe benchmark. Checkpoint pending ngày07/11 là lịch sử trước khi benchmark kết thúc, không coi là trạng thái cuối.
- Baseline đã nghiệm thu `artifacts/m3_pilot_20261106_l4_v1/`, review `reviews/m3_ag_review_v1/`, snapshot `artifacts/m3_opt_baseline_snapshot_20261106_v1.json`; M2 nguồn/hash/provenance được tham chiếu trong manifest.

Kết quả hiện có là **claim cần kiểm độc lập**: GPU `completed_with_limits`, grid16/32/64/128 đều PASS, batch32 thắng warm client throughput19,88docs/s;65requests/374.072knowninputtokens. Search3realqueryvectors/118tokens, warm local khoảng1s. Không mặc định những claim này đúng chỉ vì status PASS.

## Phạm vi ghi

Chỉ tạo thư mục mới `pipeline_v2/reviews/m3_opt_ag_review_v1/` (suffix mới nếu tồn tại) cho tests, fixtures, evidence, reports. Production/configs/sealed artifacts/baseline/historical reports chỉ đọc. SQLite mở readonly URI, không mở Cache/runner có thể CREATE/ALTER ledger cũ. Nếu cần fault injection dùng bản sao temporary riêng. Không sửa seals nguồn. Lỗi production gửi Codex cùng evidence/repro, không tự patch.

## Kiểm bắt buộc

1. Recompute fingerprint/code/profile/index/source hashes; đối chiếu147baseline files + code snapshot không đổi. Verify local raw/hash/tokenizers có provenance, nostat-onlycache, upstream drift. Kiểm seal đủ mandatory files và cache/index/vector identity mapping, không dùng builder làm oracle duy nhất.
2. Đối chiếu persisted BM25 với công thức tham chiếu độc lập trên actual case/passage pilot scope, Unicode/digits/negation, query-case filter trước cap, deterministic ties, best-passage unique-case RRF. Index cần giữ đúngbody/IDs; không ghi lại raw hoặc tóm tắt thay source. Kiểm readonly/invalidated snapshot, source drift sau mở session.
3. Kiểm đường search không còn parse toànM1, dựngBM25 hay scroll/fullverifyQdrant mỗiquery. Nêu rõ kiểm schema/count+returned hits không chứng minh mọi point DB unchanged; offline fullDBverify khác queryhealth. Sourcehashguard phải chạy trước request inference, returnedhit payload/score/dedup/scope kiểm đúng, corrupt/stale data fail-stop. Kiểm điểm hở thiếuhit/saiorder hoặc race TOCTOU nếu có bằng chứng, không coi mọi giả định là blocker.
4. Batch length-order deterministic, đủuniqueID/inputhash/rawtext, noaliaswrongvectors; so padding cùng1024inputs: baseline338528, sorted16/32/64/128=136304/140224/148928/166784, input132843. Những số này là CPU dự báo trên1.024inputs; benchmark GPU dùng256representatives +longstress vàwarmrepeats, không trộn denominators để giả speedup.
5. Đọc ledger SQLite trực tiếp và recompute từng phase warmup/stress/warm: requests, retries/errors/unknownusage, documents(nonunique), realinput/paddedtokens, latency vàpeakmemory. Xác minh boundedplan tối đa2304documentencodings chứ không2304unique. Check code/profile/model/tokenIDs/EOS/parity từngreceipt, batch128 không OOM thật không đồng nghĩa mọiworkload128an toàn. Tests OOM mocked phải ghi simulated.
6. Recompute winner từwarm client/RPC throughput, không dùng totalqueue/coldwait làmGPUtime. So measured16vs32 cùngsample/repeats; report ítrepeats, thứtựsizecốđịnh/cold-vs-warm/networkvariance có thểlệch; đây là fastest observed within tested grid, chưa tối ưu tuyệt đối. GPU CUDAevent model+pool time, remote total CPU+GPU, client time vàqueue/coldload là các khoảngkhác nhau. Allocatedmemoryheadroom vsreservedcache đúngýnghĩa. Kiểm BF16 vectorcosine<=.001 vớibaseline, batchparity và tấtcảfinite/L2/dim2560.
7. Searchbenchmark:9localtimings tái dùng3queryvectors, không phải9request; các số này loại trừ queryRPC/sessioninit/CLIstartup. Không so~1slocal với~66scoldCLI rồi gọi là end-to-end speedup66x. Nếu thiếucoldCLI/warmfullquerybenchmark, ghi rõthiếubằngchứng; không tựgọi Modal bù. Cóthểđo local components vớivectors/cache đãcó và Qdrant readonly nếu sẵn, hoặc báoDBnotrun; khôngrestart/delete/restoreDBkhôngcầnthiết.
8. Code benchmark có đo nhưng runner full/chọn profilebatch mới chưa triển khai/chưa khóa: không tự nhận full-ready. Báo liệu index/schema/cache/ranking có nguycơkhi mởrộng415693passages, nhưngkhông tự buildfull. Không suy COLIEEF1/ngữnghĩa/ownership từspeedtest.

## Bàn giao

`REPORT.md`, `findings.json`, `commands_and_results.json`, independent tests/results vàrecomputed_metrics.json. Mỗi lỗi cópriority/source/codehash/expectedactual/repro; táchproductiondefect, checkererror, documentedlimit vàmeasurementgap. Giữattemptlỗi/retry, tokensunknownđểnull, không incredential. Finalverdict tách `correctness`, `performance_evidence`, `ready_for_full_run` (chưafullcode/khôngđủgate thìkhôngPASS).

Đề xuất batch mặc định nếu evidence đủ; không sửaprofile/deploy. Nếu cần thêmbenchmarkModal đểphân xử, đưa **lệnh cụ thể và mục tiêu phép đo** cho user tự chạy, không thực thi. Kết thúc bằng danh sách lỗi Codex cần sửa trước bước tiếp theo.
