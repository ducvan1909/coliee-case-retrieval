# M3 — Tối ưu sau pilot L4

Mục tiêu là giảm padding khi embedding và bỏ chi phí dựng lại BM25/parse nguồn mỗi query. Code mới nằm trong `optimization/`, CLI `m3_opt.py`, profile `configs/m3_opt.json`, deployment riêng `deployments/modal_opt/`. Code/config/run M3 đã nghiệm thu giữ nguyên; không chạy full embedding trong bước này.

## Những phần đã thay đổi

- BM25 case và passage lưu SQLite postings, giữ công thức/analyzer và scope của pilot: case dùng toàn raw916án, passage dùng đúng1.024core bodies. Không dùng SQLite FTS scoring khác để âm thầm đổi BM25. Có readonly URI, seal và source/profile/code guards.
- Search không gọi `load_run`, không parse M1 hoặc tokenize lại toàn nguồn, không scroll toàn Qdrant hay dựng BM25 mới. Vẫn hash raw files và provenance/index bytes; kiểm schema/count DB cùng IDs/payload/fingerprint/cosine của các hit trả về. Đây là health check cho query, **không chứng minh mọi point trong DB không đổi**; full membership/vector audit ở `verify --full-db`.
- Vectors baseline đọc từ shards đã commit theo hash/ID, không mở ledger hoặc sửa cache baseline. Index mới có snapshot vectors riêng để kiểm score; không cần embed lại để tạo chỉ mục.
- Batch theo `(full_input_tokens, passage_id)` tất định, không đổi text/ID/hash. Tính padding trên pilot: input132.843tokens; baseline16=338.528padded; length-sorted16/32/64/128 lần lượt136.304/140.224/148.928/166.784. Đây là phép tính CPU, không tự coi là GPU speedup.
- App benchmark mới `coliee-pipeline-v2-embed-m3-opt-v1`, L4, BF16/2560/L2/same model+revision; tái dùng volume model weights. Maxbatch128, min0/max1container, idle120s. Chỉ upload bốn code/config/lock files, không upload corpus/.env.
- Benchmark chọn256documents đại diện theo độ dài từ đúng1.024pilot, sizes16/32/64/128, hai warm repeats/size và stress longest448-token text lặp đủbatchsize. Tổng tối đa2.304document encodings nếu chạy đủ grid (đây là benchmark có lặp đầu vào, không phải2.304unique passages). Mọi batch kiểm token/hash/model/code parity và cosine so với vectors baseline <=0,001. OOM dừng các size lớn hơn, giữ attempts/unknown usage, không retry vô hạn.
- Đo client latency, remote total, CUDA-event model+pool time, peak allocated/reserved VRAM. `remote_elapsed_seconds` cũ gồm tokenizer/copy/encode chứ không phải GPU kernel time thuần. Chọn size nhanh nhất theo warm client throughput trong grid, qua parity và stress +10% allocated-memory headroom; không tuyên bố tối ưu tuyệt đối hoặc full đã chạy.

## Lệnh hiện hành

```powershell
Set-Location E:/Git/coliee-case-retrieval
# Dựng index mới; output phải chưa tồn tại:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt build --output pipeline_v2/artifacts/TEN_INDEX_MOI
# App riêng, không deploy đè app pilot baseline:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt deploy
# Đo batch GPU có inference thật:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt benchmark --index-dir pipeline_v2/artifacts/m3_opt_index_20261107_v2 --output pipeline_v2/artifacts/TEN_BENCHMARK_MOI
# Đo search, mỗi query encode một lần rồi dùng lại vector cho các lần đo local:
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt search-benchmark --index-dir pipeline_v2/artifacts/m3_opt_index_20261107_v2 --output pipeline_v2/artifacts/TEN_SEARCH_BENCHMARK_MOI
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt search --index-dir pipeline_v2/artifacts/m3_opt_index_20261107_v2 --query "standard of review" --limit 10
& .venv/Scripts/python.exe -m pipeline_v2.m3_opt verify --index-dir pipeline_v2/artifacts/m3_opt_index_20261107_v2 --full-db
```

CLI tự đọc `.env` local trước khi import Modal, không log/copy credentials. Nếu console Windows lỗi mã hóa dấu checkmark của Modal, đặt `$env:PYTHONIOENCODING='utf-8'` trước lệnh; không đổi model/profile để khắc phục console.

## Checkpoint, attempts và giới hạn

21tests BM25 oracle/batching/session/runtime/benchmark-control local PASS (0,448s) sau sửa; kiểm độc lập ban đầu do subagent viết, phần hoàn thiện và chạy cuối do Main tiếp quản vì subagents hết quota. Không gọi đây là reviewer độc lập đã nghiệm thu toàn bộ bản cuối. Tests dùng mocks không phải GPU/DB PASS. Hai tests benchmark bổ sung kiểm winner theo throughput và allocated VRAM (không loại size chỉ vì reserved-cache lớn), cùng OOM dừng các size lớn hơn. Test fixture ledger được đóng trước cleanup trên Windows; không sửa baseline cache.

Build index v1 dừng do adapter mới giả định M0 có manifest.json; M0 thực dùng inventory/candidate files. Sửa đúng adapter mới và build outputv2; giữ v1 không seal làm checkpoint thất bại. V2 build hoàn tất61,945s/CLI62,374s,916cases/1.024vectors reused,0inference. Lỗi test đầu về error-message wrapping và sau đó kỳ vọng unknown-token sai được sửa: response có input-token count hợp lệ thì giữ count dù kiểm metrics thất bại, lỗi trước response mới là unknown.

Deploy attempt đầu lỗi console `charmap` khi in checkmark; chạy lại UTF-8 thành công app riêng. Hai lần verify DB (sandbox và approved read) chưa chạy được do Docker Engine dừng; Docker CLI xác nhận thiếu named pipe Linux Engine. Đã thử khởi động Docker Desktop, vẫn cần Engine running; ghi đúng là connection failure, không nhận code/DB PASS. Kết quả thực cuối sẽ được ghi sau khi benchmark/verify kết thúc. Baseline snapshot giữ ở `artifacts/m3_opt_baseline_snapshot_20261106_v1.json`; đã đối chiếu147files cùng code hash, không đổi.

Đối chiếu BM25 trên dữ liệu thật đã PASS6checks (3queries ×2channels), cùng toàn bộ thứ hạng/điểm số tolerance1e-10. Query postings persisted0,069–0,256s/kênh; đây không phải hybrid end-to-end và không phải GPU số đo. Evidence `reviews/m3_opt_validation_v1/{check_real_lexical.py,real_lexical_equivalence.json}`.

Benchmark thực đã khởi chạy ở `artifacts/m3_opt_gpu_benchmark_20261107_v1/`, nhưng log Modal xác nhận đang chờ scheduling GPU_L4 worker. Không chuyển loại GPU khác hoặc suy throughput từ số padding. Warm-up ledger đang `started`, tokens unknown cho đến có response; không nhận request là success hoặc0usage khi chưa kết thúc.

Docker Engine sau đó được người dùng bật. `verify --full-db` đã **PASS1.024points** trên collection thật (CLI3,896s). Đo9lượt local hybrid với document-vector probes đã lưu: session init1,062s, query0,937–1,067s; vẫn hash đủ916raw sources và validate hit payload/score. Đây là đo đường local không gồm GPU query embedding và không phải phép đo semantic retrieval. Evidence `reviews/m3_opt_validation_v1/{check_local_retrieval.py,local_retrieval_probe_benchmark.json}`.

Search benchmark với3query embeddings thật đã được khởi chạy riêng ở `artifacts/m3_opt_search_benchmark_20261107_v1/`, cũng đang chờ L4. Hai job client vẫn theo dõi request, không gửi lặp hoặc tự chạy full. Checkpoint `reviews/m3_opt_validation_v1/checkpoint_status_20261107.json` ghi trạng thái chờ, không phải nghiệm thu GPU cuối. Khi tiếp tục, đọc ledger/result hiện có trước, không chạy lại cùng benchmark/output chỉ vì chưa thấy output console. Thử đọc metadata request qua `FunctionCallList` báo API không hỗ trợ; không coi đó là lỗi inference, không dùng API này trong production.
