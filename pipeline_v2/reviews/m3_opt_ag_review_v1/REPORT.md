# Báo cáo Review Độc lập & Đối soát Benchmark M3 Optimization (`m3_opt`)

- **Ngày thực hiện:** `2026-11-08`
- **Phạm vi kiểm tra:** Theo [`pipeline_v2/docs/AG_M3_OPT_REVIEW_PROMPT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/AG_M3_OPT_REVIEW_PROMPT.md)
- **Chế độ thực thi:** Chỉ đọc trên toàn bộ production code, cấu hình và artifact đã đóng dấu; chỉ mở SQLite qua URI readonly (`?mode=ro` + `PRAGMA query_only = ON`); không gọi Modal CLI/SDK; không sửa file production.
- **Thư mục bằng chứng độc lập:** [`pipeline_v2/reviews/m3_opt_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_ag_review_v1)

---

## 1. Kết luận Tổng thể (Separated Verdicts)

| Hạng mục đánh giá | Kết luận | Tóm tắt bằng chứng |
|---|---|---|
| **`correctness`** | **`PASS_WITH_NONBLOCKING_DEFECTS`** | Toàn bộ 147 file baseline snapshot, 64 shard `.npz` (`(1024, 2560)` `float32`, diff `0.0`), 916 raw cases, 1,024 M2 passages, BM25 SQLite vs độc lập (`max_score_diff = 3.55e-15`), RRF `k=60` (`max_rrf_diff = 6.94e-18`), và các chốt chặn fail-closed trong [`FastSession`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L174-L286) đều khớp tuyệt đối. Có **4 lỗi/khiếm khuyết code (`F-M3OPT-01`..`04`)** không làm sai lệch kết quả pilot hiện tại nhưng cần sửa trước khi mở rộng. |
| **`performance_evidence`** | **`QUALIFIED_PASS_WITH_MEASUREMENT_GAPS`** | Đã đối soát độc lập toàn bộ 65 request trong [`m3_opt_gpu_benchmark_20261107_v1/ledger.sqlite3`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_gpu_benchmark_20261107_v1/ledger.sqlite3) và 3 request + 9 lượt search trong [`m3_opt_search_benchmark_20261107_v1/ledger.sqlite3`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_search_benchmark_20261107_v1/ledger.sqlite3). Mọi con số đo được là thật, nhất quán và có provenance đầy đủ. Tuy nhiên có **2 khoảng trống phép đo (`F-M3OPT-05`, `F-M3OPT-06`)**: mẫu 256-doc theo quantile làm phình padding ở batch lớn (`52.72%` ở `bs=128` so với `0.052%` trên full corpus 415,693 passages), và search benchmark đo `FastSession.search_vector()` in-process (`~1.09s`) thay vì toàn trình CLI (`~3.25s` warm). |
| **`ready_for_full_run`** | **`NOT_READY`** | Chưa có runner/config cho full corpus (`415,693` passages / `7,708` cases); [`m3.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/configs/m3.json) vẫn khóa `mode="pilot_only"`, `pilot_size=1024`, `batch_size=16`, `scan_cap=1024`; ngoài ra [`PersistentBM25.create()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L29-L51) đang lưu nguyên văn `text` vào `documents.metadata` và [`FastSession.__init__()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L175-L192) đang nạp toàn bộ passages + quét toàn bộ `vectors.npy` trên mỗi lần khởi tạo. |

---

## 2. Kết quả Kiểm tra Độc lập theo 8 Yêu cầu

### 2.1. Kiểm tra 1 — Baseline Immutability & Sealed Optimization Index
- **Baseline Snapshot (`m3_pilot_20261106_l4_v1`):** Đối soát toàn bộ **147/147 file** trên đĩa khớp tuyệt đối cả `sha256` lẫn `bytes` với [`m3_opt_baseline_snapshot_20261106_v1.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_baseline_snapshot_20261106_v1.json) (`0` mismatch).
- **Code & Profile Fingerprints:**
  - `baseline_code_sha256`: `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63` (khớp 11 file baseline).
  - `opt_code_fingerprint`: `126ff7504aed84f8d89b8d46560dea25c8ccf3a4d8aaa001d2789d83a9d98845` (khớp 9 file optimization).
  - `base_embedding_fingerprint`: `d945329fa49e2f4b4f83d530df03fb4897babd5345562cbeaebd3b21499649bf`.
  - `opt_embedding_fingerprint`: `c2d56b0dbb8ad1d8e2d314806d457c44c0a5e5c80ebb7211b5f14a31534692d3` (chỉ khác 3 trường runtime cho phép: `modal_app="coliee-pipeline-v2-embed-m3-opt-v1"`, `scaledown_window_seconds=120`, `max_batch_size=128`).
- **Trạng thái Index Artifacts:**
  - `m3_opt_index_20261107_v1`: Không có `manifest.json` và không có `seal.json` (`failed_partial`), bị từ chối fail-closed khi mở qua [`FastSession`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L178).
  - [`m3_opt_index_20261107_v2`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_index_20261107_v2): `seal.json` hợp lệ, khóa chính xác 3 file (`lexical.sqlite3`: `138,936,320` bytes, `vectors.npy`: `10,485,888` bytes, `manifest.json`: `294,824` bytes).
- **Đối soát Độc lập `vectors.npy`:** Ghép trực tiếp 64 shard `.npz` đã commit trong `m3_pilot_20261106_l4_v1/vectors/` theo thứ tự `pilot_manifest.json`:
  - `shape = (1024, 2560)`, `dtype = float32`, `all_finite = True`.
  - `max_abs_diff = 0.0` (`np.array_equal == True`), `max_norm_deviation_from_1 = 1.192e-07 <= 0.002`.
  - `passage_ids` và `exact_input_sha256` khớp 1-1 (`True`).

### 2.2. Kiểm tra 2 — Persistent Lexical Index (`PersistentBM25`)
- Đã viết [`IndependentBM25Oracle`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_ag_review_v1/audit_m3_opt_independent.py#L46-L101) đọc trực tiếp từ 916 file raw (`data/task1_train_files_2026/cases/*.txt`), `m2_passages_20261106_v1/sources/*.json` và `m2_navigation_20261106_v3/sources/*.json`.
- Trên toàn bộ 16 phép đối soát (8 truy vấn × 2 kênh `case` / `passage`, bao gồm tiếng Pháp có dấu, chữ số, phủ định `n'est pas`, ký hiệu `97(1)`, `100%`, `don't`, loại trừ `query_case` trước `limit`, và truy vấn rỗng kết quả):
  - `all_queries_ids_equal = True`
  - `all_queries_metadata_equal = True`
  - `max_score_diff_across_all_queries = 3.5527e-15` (sai số dấu phẩy động cấp `1e-15`).
- **Phát hiện quan trọng (`F-M3OPT-02`):** Trong [`PersistentBM25.create()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L47), cột `documents.metadata` lưu toàn bộ `json.dumps(d)` **bao gồm cả trường `"text"` nguyên văn** (`43.81 MB` raw text của 916 cases + `2.24 MB` text của 1,024 passages). Khi `PersistentBM25.search()` lấy top-`1024` hits, nó chạy tới 916 câu lệnh `SELECT metadata FROM documents WHERE kind=? AND id=?` và `json.loads()` toàn bộ văn bản từng vụ án chỉ để xóa `"text"` trong Python (`{k:v for k,v in d.items() if k!="text"}`). Điều này khiến `case` BM25 trên SQLite mất `0.29–0.33s`/truy vấn (chậm hơn `~70x` so với BM25 trong RAM `0.004s`) và sẽ gây phình bộ nhớ/SQLite nghiêm trọng nếu chạy trên 415,693 passages.

### 2.3. Kiểm tra 3 — Fast Search Path, Provenance Guards & Qdrant Verification
- [`FastSession.search_vector()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L222-L253) không gọi `load_run`, không parse lại M1, không build lại BM25, và không scroll toàn bộ Qdrant; mỗi truy vấn gọi `self.guard()`, `validate_vectors()`, `self.cheap_db_check()`, và kiểm tra chặt chẽ toàn bộ `dense` hits trả về (`passage_id` duy nhất, thuộc snapshot 1,024 passages, khớp 7 trường payload, không chứa `query_case`, và `|self.vectors[i] @ vector - score| <= 1e-4`).
- Đã kiểm thử tiêm lỗi (fault injection) trong [`test_m3_opt_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_ag_review_v1/test_m3_opt_independent_ag.py#L244-L318): mọi sai lệch (raw hash drift sau khi khởi tạo session, dense score lệch `0.001`, duplicate hit IDs, lọt `query_case`, hỏng `seal.json`) đều bị chặn fail-closed bằng `M3Error`.

### 2.4. Kiểm tra 4 — Deterministic Length Bucketing & Phân tích Toán học Padding (256 vs 1,024 vs 415,693 Passages)
- Đã xác minh độc lập `PinnedTokenizer.count(text) == full_input_tokens` trên toàn bộ 1,024 pilot passages (`True`).
- Bảng đối soát lượng token thật (`input_tokens`) và `padded_tokens` trên **3 quy mô dữ liệu** (tính trực tiếp từ artifact thật trong [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_ag_review_v1/recomputed_metrics.json#L281-L395)):

| Tập dữ liệu | Chế độ / Batch size | Số passages | `input_tokens` | `padded_tokens` | Tỷ lệ padding (`(padded-input)/padded`) | Giảm `padded_tokens` so với unsorted `bs=16` |
|---|---|---:|---:|---:|---:|---:|
| **Pilot 1,024** (`m3_pilot_20261106_l4_v1`) | Unsorted `bs=16` | 1,024 | 132,843 | 338,528 | 60.76% | 0.00% |
| **Pilot 1,024** | Sorted `bs=16` | 1,024 | 132,843 | 136,304 | **2.54%** | **-59.74%** |
| **Pilot 1,024** | Sorted `bs=32` | 1,024 | 132,843 | 140,224 | **5.26%** | **-58.58%** |
| **Pilot 1,024** | Sorted `bs=64` | 1,024 | 132,843 | 148,928 | **10.80%** | **-56.01%** |
| **Pilot 1,024** | Sorted `bs=128` | 1,024 | 132,843 | 166,784 | **20.35%** | **-50.73%** |
| **Benchmark Sample 256** (`representative`) | Sorted `bs=16` (1 pass) | 256 | 33,288 | 37,152 | **10.40%** | — |
| **Benchmark Sample 256** (`representative`) | Sorted `bs=32` (1 pass) | 256 | 33,288 | 41,632 | **20.04%** | +12.06% vs `bs=16` |
| **Benchmark Sample 256** (`representative`) | Sorted `bs=64` (1 pass) | 256 | 33,288 | 49,856 | **33.23%** | +34.19% vs `bs=16` |
| **Benchmark Sample 256** (`representative`) | Sorted `bs=128` (1 pass) | 256 | 33,288 | 70,400 | **52.72%** | **+89.49% vs `bs=16`** |
| **Full Corpus 415,693** (`m2_passages_20261106_v1`) | Unsorted `bs=16` | 415,693 | 55,346,360 | 119,037,164 | 53.50% | 0.00% |
| **Full Corpus 415,693** | Sorted `bs=16` | 415,693 | 55,346,360 | 55,349,888 | **0.0064%** | **-53.502%** |
| **Full Corpus 415,693** | Sorted `bs=32` | 415,693 | 55,346,360 | 55,353,664 | **0.0132%** | **-53.499%** |
| **Full Corpus 415,693** | Sorted `bs=64` | 415,693 | 55,346,360 | 55,360,576 | **0.0257%** | **-53.493%** |
| **Full Corpus 415,693** | Sorted `bs=128` | 415,693 | 55,346,360 | 55,374,912 | **0.0516%** | **-53.481%** |

> [!IMPORTANT]
> **Giải thích nghịch lý hiệu năng giữa `batch_size=16`, `32`, `64`, `128` (`F-M3OPT-05`):**
> Trên tập mẫu 256 passages rút theo quantile (`representative(passages, 256)`), 256 văn bản trải đều từ `4` đến `448` tokens. Do mật độ mẫu quá thưa (chỉ ~0.57 văn bản cho mỗi độ dài token), khi tăng batch size lên `64` và `128`, mỗi batch buộc phải gom các văn bản có độ dài chênh lệch rất lớn (lô thứ 2 của `bs=128` gom từ ~150 đến 448 tokens và pad toàn bộ 128 văn bản lên `448` tokens = `57,344` padded tokens cho `25,528` input tokens!).
> Ngược lại, trên **Full Corpus 415,693 passages**, trung bình có **~928 passages có cùng chính xác một độ dài token**, nên ngay cả ở `batch_size=128`, lượng padding toàn corpus chỉ là **`0.0516%`** (`55,374,912` padded tokens so với `55,346,360` input tokens)!

### 2.5 & 2.6. Kiểm tra 5 & 6 — Đối soát GPU Benchmark Ledger (`m3_opt_gpu_benchmark_20261107_v1`)
- Đã mở readonly [`m3_opt_gpu_benchmark_20261107_v1/ledger.sqlite3`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_gpu_benchmark_20261107_v1/ledger.sqlite3) và tính lại toàn bộ **65 attempts**:
  - `status`: `65/65` là `"success"`, `0` retry/error, `0` `unknown_token_attempts`.
  - Tổng số lượt mã hóa tài liệu (non-unique): `16 (warmup) + 240 (stress 16+32+64+128) + 2,048 (warm 4 × 2 × 256) = 2,304` lượt (khớp `maximum_documents_if_all_grid_sizes_complete = 2304`). Số tài liệu pilot duy nhất được chọn: `256` IDs (`254` unique `input_hashes` do 3 đoạn ngắn trùng nội dung).
  - Tổng token thật qua 65 lệnh: `374,072` `input_tokens`; tổng `padded_tokens`: `506,016`.
  - `warmup-16`: `client_elapsed_seconds = 1943.429s` (~32.4 phút chờ cấp phát container L4 + `model_load_seconds = 19.609s`), `remote_elapsed_seconds = 0.988s`, `gpu_model_pool_seconds = 0.861s`. Đã được tách riêng khỏi `warm_calls`.
  - Toàn bộ 65 receipts đều xác nhận đồng nhất: GPU `NVIDIA L4` (`device_total_bytes = 23,689,363,456` ≈ `23.69 GB`), `torch.bfloat16`, `Qwen/Qwen3-Embedding-4B` (`revision = 5cf2132abc99cad020ac570b19d031efec650f2b`), `dimensions = 2560`, `engine_sha256 = b0971725...`, `wrapper_sha256 = 39ea6e57...`.

| Batch size | Requests (warm) | Docs | Real tokens | Padded tokens | Client time (s) | Remote time (s) | GPU CUDA time (s) | RPC overhead / call (s) | Client docs/s | Remote docs/s | GPU CUDA docs/s | GPU **padded** tok/s | Peak Allocated VRAM (GB / %) | Allocated Headroom | Peak Reserved VRAM (GB / %) | Max Cosine Dev vs Baseline |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **16** | 32 | 512 | 66,576 | 74,304 | 31.320 | 14.999 | 14.485 | 0.510s | 16.347 | **34.135** | **35.346** | **5,129.6** | 8.68 GB (36.65%) | **63.35%** | 9.01 GB (38.04%) | `0.000571` |
| **32** | 16 | 512 | 66,576 | 83,264 | **25.754** | 17.717 | 17.289 | 0.502s | **19.880** | 28.899 | 29.614 | 4,815.9 | 9.25 GB (39.03%) | **60.97%** | 10.61 GB (44.79%) | `0.000377` |
| **64** | 8 | 512 | 66,576 | 99,712 | 29.044 | 22.318 | 21.887 | 0.841s | 17.628 | 22.942 | 23.393 | 4,555.8 | 10.38 GB (43.83%) | **56.17%** | 13.81 GB (58.30%) | `0.000479` |
| **128** | 4 | 512 | 66,576 | 140,800 | 50.344 | 32.206 | 31.756 | 4.534s | 10.170 | 15.898 | 16.123 | 4,433.8 | 12.66 GB (53.43%) | **46.57%** | 20.21 GB (85.32%) | `0.000288` |

- **Nhận xét kỹ thuật từ bảng đối soát:**
  1. **Tốc độ xử lý tensor thực của GPU L4 (`GPU padded tok/s`) gần như cố định ở mức `4,434–5,130 padded tokens/s`.** Việc `Remote docs/s` giảm từ `34.14` (`bs=16`) xuống `28.90` (`bs=32`), `22.94` (`bs=64`), `15.90` (`bs=128`) là hệ quả trực tiếp của việc `padded_tokens` trong mẫu 256-doc bị thổi phồng từ `74,304` lên `140,800`.
  2. **`batch_size=32` thắng `Client docs/s` (`19.88 docs/s`)** vì giảm một nửa số cuộc gọi RPC từ 32 xuống 16 giúp tiết kiệm `8.28s` chi phí mạng/tuần tự hóa (`~0.50s/call`), lớn hơn phần thời gian GPU tăng thêm do padding (`2.72s`).
  3. **Numeric Parity:** Độ lệch cosine tối đa so với vector baseline (`bs=16` unsorted) trên toàn bộ các batch size là `0.000571 <= 0.001` (vượt ngưỡng kiểm định `parity_cosine_atol = 0.001`). Lưu ý: `benchmark_index` tính `max_cosine_deviation_vs_baseline` trực tiếp khi nhận phản hồi và lưu vào `benchmark_result.json`, không lưu lại mảng vector đầu ra của benchmark vào đĩa.
  4. **VRAM Headroom:** Cả 4 kích thước batch đều đạt `allocated_headroom_fraction >= 46.57% >> 10%`. Tuy nhiên ở `batch_size=128`, `peak_reserved_bytes` của PyTorch caching allocator lên tới `20.21 GB / 23.69 GB` (chỉ còn `14.68%` reserved headroom) và chi phí tuần tự hóa/mạng mỗi call tăng lên `4.53s/call`, nên `batch_size=128` không an toàn để làm mặc định.

### 2.7. Kiểm tra 7 — Đối soát Search Benchmark (`m3_opt_search_benchmark_20261107_v1`)
- Đã kiểm tra readonly [`m3_opt_search_benchmark_20261107_v1/ledger.sqlite3`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_search_benchmark_20261107_v1/ledger.sqlite3) và [`search_benchmark.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_search_benchmark_20261107_v1/search_benchmark.json):
  - Có chính xác **3 request** (`118` input tokens tổng cộng: `35 + 35 + 48`, `0` lỗi).
  - **Phát hiện lỗi cấu hình app (`F-M3OPT-01`):** Cả 3 query requests trong `search_benchmark` (cũng như `FastSession.search()`) đều gọi `ModalEmbedder(self.base["profile"])` — tức là gọi ứng dụng Modal của baseline pilot (`coliee-pipeline-v2-embed-m3-pilot-v1`, `engine_sha256 = 1ec94f4d...`) thay vì ứng dụng `modal_opt` (`coliee-pipeline-v2-embed-m3-opt-v1`, `engine_sha256 = b0971725...`). Do container của pilot app đang tắt, `benchmark-query-0` phải chịu thêm một lần cold-start/queue wait **`2,114.83s`** (`remote_elapsed_seconds = 0.630s`), trong khi `benchmark-query-1` và `2` (khi container đã ấm) chỉ mất **`1.029s`** và **`1.096s`** client time (`0.0526s` và `0.0528s` remote time).
  - **Thời gian tìm kiếm cục bộ (`FastSession.search_vector()`):** Qua 9 lần chạy (3 queries × 3 repeats), thời gian đạt **`0.990s – 1.626s`** (trung bình **`1.091s`**).
  - **Phân biệt rõ với Baseline CLI (`F-M3OPT-06`):** Con số `66.17s – 67.33s` của baseline là thời gian **toàn trình CLI** (gồm khởi tạo Python, kiểm tra M1/M2, dựng lại BM25 từ đầu, gọi Modal query, scroll kiểm tra toàn bộ Qdrant, và RRF). Trong khi đó `0.99s – 1.63s` trong `search_benchmark.json` chỉ là thời gian chạy `session.search_vector()` trong tiến trình sau khi đã có query vector và đã mở `FastSession`. Nếu tính toàn trình CLI ấm của `m3_opt search` (ghi nhận tại `m3_opt_index_20261107_v2_runtime/operations/1794067162583804700_b93c98744ef74764be50dbbdcfeb5022_search.json`), tổng thời gian `cli_seconds` là **`3.249s`** (nhanh hơn **~20.5 lần** so với `~66.6s` của baseline CLI; riêng phần truy hồi cục bộ giảm từ `~65s` xuống `~1.09s`, tức nhanh hơn **~60 lần**).

### 2.8. Kiểm tra 8 — Đánh giá Sẵn sàng cho Full-Corpus Run (`415,693` Passages / `7,708` Cases)
Hệ thống **CHƯA SẴN SÀNG (`NOT_READY`)** để chạy full-corpus vì 4 nút cổ chai kỹ thuật sau:
1. **Chưa có Full-Corpus Runner & Profile (`F-M3OPT-07`):** [`m3.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/configs/m3.json) vẫn khóa cứng `mode="pilot_only"`, `pilot_size=1024`, `batch_size=16`, và [`build_index()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L137-L171) chỉ đóng gói lại từ `baseline_run` 1,024 passages.
2. **Phình dữ liệu và chậm truy vấn trong `PersistentBM25` (`F-M3OPT-02`):** Lưu nguyên văn `text` vào `documents.metadata` và nạp toàn bộ `docs` + `frequencies` vào RAM cùng lúc trong `PersistentBM25.create()` sẽ tiêu tốn nhiều GB RAM và làm file `lexical.sqlite3` phình lên hàng chục GB khi đánh chỉ mục 415,693 passages + 7,708 cases.
3. **Chi phí khởi tạo `FastSession.__init__()` ở quy mô 415,693 passages (`F-M3OPT-03`):** Наạp toàn bộ 415,693 bản ghi `documents("passage")` vào RAM và gọi `validate_vectors()` quét toàn bộ file `vectors.npy` (`415,693 × 2,560 × 4 bytes = 4.26 GB`) trên mỗi lần khởi tạo `FastSession` sẽ làm mất tác dụng của `mmap_mode="r"`.
4. **Cấu hình `fusion.scan_cap = 1024`:** Ở pilot 1,024 passages, `scan_cap = 1024` bao phủ 100% kho văn bản; nhưng ở full corpus 415,693 passages (trung bình ~54 passages/case), nếu một số vụ án dài chiếm nhiều đoạn trong top-1024 của `passage_bm25` hoặc `dense_passage`, số lượng unique cases trước khi hợp nhất RRF có thể bị thu hẹp đáng kể.

---

## 3. Khuyến nghị Batch Size Mặc định & Lệnh Đo Modal Bổ sung (Nếu cần)

### 3.1. Khuyến nghị Batch Size Mặc định
- **Khuyến nghị dùng ngay (Conservative Default): `batch_size = 32`.**
  - **Lý do:** Trên benchmark thực tế đã chạy, `batch_size = 32` đạt thông lượng end-to-end cao nhất (`19.88 docs/s`, nhanh hơn `+21.6%` so với `batch_size = 16`), giữ `60.97%` allocated VRAM headroom (`55.21%` reserved headroom), và độ lệch cosine tối đa chỉ `0.000377 <= 0.001`.
- **Tiềm năng trên Full Corpus (`415,693` passages): `batch_size = 64` (hoặc `32`).**
  - Trên full corpus đã sắp xếp theo độ dài, tỷ lệ padding ở `batch_size = 64` chỉ là `0.0257%` (thay vì `33.23%` như trong mẫu 256-doc quantile). Khi không còn 33% token rác do lấy mẫu thưa, thời gian GPU cho mỗi 512 văn bản ở `bs=64` sẽ giảm từ `~21.9s` xuống `~14.6s`, kết hợp với chỉ 8 cuộc gọi RPC (`~6.7s` overhead) sẽ cho thông lượng end-to-end ước tính `~24.0 docs/s` (với `56.17%` allocated VRAM headroom).

### 3.2. Lệnh Modal Tùy chọn để Phân xử `batch_size = 32` vs `64` (Người dùng tự quyết định)
Bạn **không bắt buộc** phải chạy thêm Modal nếu chấp nhận `batch_size = 32` làm mặc định an toàn. Nếu muốn phân xử thực nghiệm giữa `16`, `32`, `64` trong điều kiện **mật độ độ dài sát với full corpus** (không bị méo bởi mẫu 256-doc quantile), sau khi Codex cập nhật hàm chọn mẫu benchmark để lấy **256 passages liên tiếp nhau về độ dài từ tập 1,024 pilot** (nơi padding nội bộ mỗi batch chỉ `~1–3%`), bạn có thể chạy lệnh giới hạn sau:

```powershell
.venv\Scripts\python.exe -m pipeline_v2.m3_opt --env-file pipeline_v2/.env benchmark --index-dir pipeline_v2/artifacts/m3_opt_index_20261107_v2 --output pipeline_v2/artifacts/m3_opt_gpu_benchmark_dense_v2
```

---

## 4. Danh sách Việc Codex Cần Sửa Trước Bước Tiếp Theo

1. **[`F-M3OPT-02` - Mức `medium`] Loại bỏ `"text"` khỏi `documents.metadata` và tối ưu truy vấn metadata trong [`PersistentBM25`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L29-L78):**
   - Không ghi trường `"text"` vào cột `metadata` của bảng `documents` trong `lexical.sqlite3`; chuyển quá trình tạo postings sang xử lý theo lô (streaming) thay vì giữ toàn bộ `docs` và `frequencies` trong RAM.
   - Trong `PersistentBM25.search()`, truy vấn `metadata` cho tập `chosen` bằng một truy vấn theo lô hoặc chỉ lưu các trường định danh nhẹ cho kênh `case` (`case_id`, `source_hash`).
2. **[`F-M3OPT-03` - Mức `medium`] Tránh nạp toàn bộ passages và quét toàn bộ `vectors.npy` trong [`FastSession.__init__()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L175-L192) & tách side-effect CLI trong [`m3_opt.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/m3_opt.py#L32-L56):**
   - Sau khi `validate_seal()` đã xác thực SHA-256 của `vectors.npy`, chỉ kiểm tra `shape` và `dtype` của mmap khi mở session thường; chỉ quét toàn bộ phần tử/norm khi gọi `verify(full_db=True)`.
   - Chỉ nạp `.env` cho các lệnh có kết nối Modal (`deploy`, `benchmark`, `search`, `search-benchmark`) và không ghi file vào `<index_dir>_runtime/operations/` khi chạy lệnh đọc thuần túy (`verify`, `open`).
3. **[`F-M3OPT-04` - Mức `low`] Chuẩn hóa đường dẫn tuyệt đối trong [`PersistentBM25.__init__()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L24-L26):**
   - Đổi `self.path = Path(path)` thành `self.path = Path(path).resolve()` để `self.path.as_uri()` không ném `ValueError` khi truyền đường dẫn tương đối.
4. **[`F-M3OPT-01` - Mức `medium`] Làm rõ hoặc đồng bộ hóa ứng dụng Modal cho Query Embedding trong [`FastSession.search()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization/index.py#L262) và [`search_benchmark()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/m3_opt.py#L84):**
   - Quyết định rõ việc mã hóa câu truy vấn dùng `OptModalEmbedder` (`coliee-pipeline-v2-embed-m3-opt-v1`) hay giữ `ModalEmbedder` của baseline để tránh chờ cold-start 2 lần trên 2 ứng dụng Modal khác nhau.
