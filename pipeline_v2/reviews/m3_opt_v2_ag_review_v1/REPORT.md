# Báo cáo Kiểm thử Độc lập & Thực thi Nghiệm thu M3 Optimization V2 (`m3_opt_v2`)

- **Ngày thực hiện:** `2026-11-08`
- **Phạm vi thực hiện:** Theo [`pipeline_v2/docs/AG_M3_OPT_V2_TEST_PROMPT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/AG_M3_OPT_V2_TEST_PROMPT.md)
- **Thư mục bằng chứng độc lập:** [`pipeline_v2/reviews/m3_opt_v2_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1)
- **Nguyên tắc:** Không sửa bất kỳ file code/config/profile production nào; giữ nguyên toàn bộ snapshot/artifact baseline và V1 (`147/147` file baseline khớp tuyệt đối); chỉ chạy đúng phạm vi pilot được giao.

---

## 1. Kết luận Tổng thể theo Từng Hạng mục (Separated Verdicts)

| Hạng mục | Kết luận | Tóm tắt bằng chứng |
|---|---|---|
| **`local_correctness`** | **`PASS`** | `18/18` unit tests V2 + `4` bộ kiểm thử độc lập của AG + `16/16` phép đối soát BM25 2 kênh (`case`/`passage`) so với oracle độc lập đều `PASS` (`max_score_diff = 3.55e-15`). SQLite giảm từ `138,936,320` xuống `93,270,016` bytes (`-32.87%`), không chứa `"text"`. `verify --full-db` đạt `PASS` (`1,024` points Qdrant, `916` raw cases, `vectors.npy` khớp tuyệt đối 64 shard baseline). |
| **`real_compatibility`** | **`PASS`** | Đã deploy app mới `coliee-pipeline-v2-embed-m3-opt-v2` và chạy `preflight` thật trên NVIDIA L4 (`9/9` requests thành công, `1,856` input tokens). Độ lệch cosine tối đa trên 8 document fixtures là `0.000210 <= 0.001` (singleton vs batch: `0.000158 <= 0.001`) và trên 3 query fixtures so với app baseline là `2.38e-07 <= 0.001`. |
| **`gpu_benchmark`** | **`PASS_COMPLETED_WITH_DOCUMENTED_PILOT_LIMITS`** | Đã chạy `benchmark` thật trên NVIDIA L4 (`89/89` requests thành công, `0` lỗi/retry, `412,295` input tokens, `433,024` padded tokens, tổng `2,560` lượt mã hóa tài liệu đúng trần quy định). Trên mẫu 4 nhóm độ dài × 64 passages (`256` unique IDs, 3 lượt lặp crossover), **`batch_size = 64` là fastest observed** về warm client throughput (`23.00 docs/s` so với `21.85 docs/s` ở `bs=32` và `17.17 docs/s` ở `bs=16`), giữ `56.22%` allocated VRAM headroom và `max_cosine_deviation = 0.000885 <= 0.001`. |
| **`search_latency`** | **`PASS_COMPONENTS_AND_WALLTIME_MEASURED`** | Đã chạy `search-benchmark` (`3` queries × `3` repeats) và `3` lượt đo `Measure-Command` độc lập ngoài tiến trình. Thời gian truy hồi cục bộ (`local_vector_reuse_seconds`) giảm xuống **`0.174s – 0.264s` (trung bình `0.208s`**, nhanh hơn **~5.2x** so với `1.091s` ở V1 nhờ loại bỏ `"text"` khỏi SQLite metadata và truy vấn theo lô). Thời gian toàn trình subprocess (`Measure-Command`) đạt **`6.34s – 6.59s`** (`full_cli_seconds`: `6.15s – 6.38s`). |
| **`full_readiness`** | **`NOT_READY_BY_DESIGN_SCOPE`** | Đúng theo kế hoạch trong [`M3_OPTIMIZATION_V2.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/M3_OPTIMIZATION_V2.md), bản V2 chỉ đóng băng ở phạm vi pilot (`mode="pilot_only"`, `1,024` passages / `916` cases). Chưa triển khai runner full-corpus (`415,693` passages), chưa đánh giá COLIEE gold F1 hoặc M4 agent. |

---

## 2. Fingerprints & Đối soát Tính Bất biến của Snapshot Cũ

Tất cả fingerprints được tính độc lập trong [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/recomputed_metrics.json#L3-L37):

- **Production Code & Profile Fingerprints:**
  - `v2_code_fingerprint`: `e2e554dd44bbd99ab93b61ca893094fe9dd47e0cd8604e5898e8b169bf931cf3` (khớp 10 file trong `implementation()`).
  - `v1_code_fingerprint`: `126ff7504aed84f8d89b8d46560dea25c8ccf3a4d8aaa001d2789d83a9d98845` (giữ nguyên không đổi).
  - `base_code_fingerprint`: `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63` (giữ nguyên không đổi).
  - `v2_profile_sha256` (`configs/m3_opt_v2.json`): `dcec3736aa6e5b2be170c5755bae0f6a4fcdf708f86311400d06959c3323410b`.
  - `v1_profile_sha256` (`configs/m3_opt.json`): `68915606a25dbd5027332b674987d005bcabff86753a557902b92591f2c83b62` (giữ nguyên).
  - `base_profile_sha256` (`configs/m3.json`): `157bc10faed9660445a47daf50b73158c13da1daf7c60c39aeafabe0b0355b96` (giữ nguyên).
  - `v2_embedding_fingerprint`: `9105955758bda2eba37350535866f9b217e1b9650b1a3f081496a7c4a9965c49`.
  - `base_embedding_fingerprint`: `d945329fa49e2f4b4f83d530df03fb4897babd5345562cbeaebd3b21499649bf`.
- **Snapshot & Index Integrity:**
  - `m3_pilot_20261106_l4_v1`: `147/147` file khớp tuyệt đối `sha256` và `bytes` (`0` mismatch).
  - `m3_opt_index_20261107_v2` (V1): `seal.json` giữ nguyên hợp lệ (`lexical.sqlite3 = 138,936,320` bytes).
  - [`m3_opt_v2_index_20261108_v1`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_opt_v2_index_20261108_v1): `seal.json` hợp lệ (`manifest_sha256 = a906d3812bf36ce8d9ff5f9912d5716199f4d9b93718f80345a55f6098161058`, `lexical.sqlite3 = 93,270,016` bytes, giảm `45,666,304` bytes = **`-32.87%`**).
- **Runtime & Model Attestation trên Modal L4:**
  - App V2: `coliee-pipeline-v2-embed-m3-opt-v2` (`engine_sha256 = c2c580bf1f32a9437aaae4dfdf1d7d3f08674ed1f26a3c24ee55a34bbfc14501`, `wrapper_sha256 = 4a08b2e0d8c14cfd6671bb04045c4cbd4be2d4a184fc01c1f0a73edec3acc101`).
  - Model: `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`, `torch.bfloat16`, `dimensions = 2560`, GPU `NVIDIA L4` (`device_total_bytes = 23,689,363,456` ≈ `23.69 GB`).
  - Packages: `torch=2.8.0`, `transformers=4.57.1`, `tokenizers=0.22.2`, `modal=1.5.3`, `numpy=2.5.4`, `huggingface_hub=0.36.2`, `safetensors=0.8.0`.

---

## 3. Kết quả Kiểm thử Local & Phân xử Các Finding V1

Bộ kiểm thử độc lập [`test_m3_opt_v2_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/test_m3_opt_v2_independent_ag.py) và kết quả trong [`independent_local_test_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/independent_local_test_results.json) xác nhận toàn bộ 6 vấn đề từ kỳ review V1 (`F-M3OPT-01`..`06`) đã được xử lý triệt để:

1. **BM25 Metadata & Batched Fetch (`F-M3OPT-02`, `F-M3OPT-04` — ĐÃ XỬ LÝ):**
   - [`PersistentBM25.create()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization_v2/index.py#L29-L59) loại bỏ `"text"` khỏi `documents.metadata`, chỉ giữ một `Counter` trong RAM tại một thời điểm và flush `postings` theo từng lô tối đa `512` hàng.
   - [`PersistentBM25.get_many()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization_v2/index.py#L61-L69) lấy metadata theo lô `256` IDs thay vì `N` câu lệnh `SELECT` đơn lẻ.
   - Đường dẫn tương đối (`Path("sub/rel_lexical.sqlite3")`) được `.resolve()` trước khi mở URI `?mode=ro`.
   - Trên 16 phép kiểm tra BM25 thực tế (8 truy vấn × 2 kênh `case`/`passage`), thứ tự ID và metadata khớp 100%, `max_score_diff = 3.5527e-15`, và thời gian truy vấn BM25 kênh `case` giảm từ **`~0.31s` (V1) xuống `0.0225s` (V2)** (nhanh hơn **~13.8 lần**).
2. **Session Lifecycle, Lazy Init & Tamper Guards (`F-M3OPT-03` — ĐÃ XỬ LÝ):**
   - [`FastSession.__init__()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization_v2/index.py#L126-L144) không còn gọi `iter_documents("passage")` hay `validate_vectors()` trên toàn bộ ma trận khi khởi tạo; chỉ kiểm tra `shape == (1024, 2560)` và `dtype == float32` sau khi `validate_seal()` đã xác thực SHA-256. Quét toàn bộ phần tử/norm chỉ chạy khi gọi `verify(full_db=True)`.
   - Khi thay đổi file raw case trong lúc session đang mở (kiểm thử trên bản sao tạm trong `test_03`), ranking giữ snapshot bất biến đúng hợp đồng, nhưng gọi `session.open()` hoặc `session.revalidate()` lập tức phát hiện sai lệch hash, ném `M3Error("Current evidence source hash drift")` và đánh dấu `session.invalidated = True` chặn mọi thao tác tiếp theo.
   - Các lệnh CLI cục bộ (`build`, `verify`, `open`, `--help`) không đọc `.env`, không import `modal`, và không ghi file rác vào thư mục индекс/runtime.
3. **Full DB Verification (`verify --full-db`):**
   - Sau khi đảm bảo Docker Desktop và container `coliee-pipeline-v2-qdrant` hoạt động ổn định, lệnh `verify --full-db` trả về `EXIT_CODE=0` trong `2.783s` (`session_initialization_seconds = 0.561s`), xác nhận đầy đủ `1,024` points trong collection `coliee_m3_pilot_99e66b7f9bbf4be4` và `916` raw cases.

---

## 4. Kết quả Thực thi Remote trên Modal L4

### 4.1. Compatibility Preflight (`m3_opt_v2_compat_20261108_v1`)
- **Trạng thái:** `"PASS"` (`execution_mode = "real"`, `EXIT_CODE = 0`, `full_cli_seconds = 60.594s`).
- **Chi phí & Requests:** `9` requests (`3` `v2_document`, `3` `query` trên app baseline, `3` `v2_query` trên app V2), `0` lỗi/retry, `1,856` input tokens, `0` unknown token attempts.
- **Độ lệch Cosine (Parity):**
  - Document batch (8 passages trải đều độ dài từ `2` đến `448` tokens) so với vector baseline đã lưu: `max_cosine_deviation = 0.0002096 <= 0.001`.
  - Document singleton vs batch (passage ngắn nhất và dài nhất `448` tokens): `max_singleton_batch_deviation = 0.0001576 <= 0.001`.
  - Query parity giữa app baseline (`coliee-pipeline-v2-embed-m3-pilot-v1`) và app V2 (`coliee-pipeline-v2-embed-m3-opt-v2`) trên 3 câu truy vấn chuẩn: khớp 100% `token_ids` và `input_hashes`, độ lệch cosine lần lượt là **`5.96e-08`**, **`2.38e-07`**, và **`1.19e-07`** (tất cả đều `<< 0.001`).

### 4.2. GPU Benchmark V2 (`m3_opt_v2_gpu_benchmark_20261108_v1`)
- **Trạng thái:** `"completed_with_limits"` (`execution_mode = "real_modal"`, `EXIT_CODE = 0`, `full_cli_seconds = 158.756s`, `total_seconds = 156.973s`).
- **Tổng hợp Ledger (`ledger.sqlite3`):**
  - Tổng số requests: **`89/89` thành công** (`1` warmup-16 + `4` stress [16, 32, 64, 128] + `84` warm calls [48 cho `bs=16`, 24 cho `bs=32`, 12 cho `bs=64`]), `0` lỗi, `0` retry, `0` `unknown_token_attempts`.
  - Tổng số lượt mã hóa tài liệu: **`2,560` encodings** (`16` warmup + `240` stress + `2,304` warm = `256` unique IDs × `3` sizes × `3` repeats), đúng bằng giới hạn trần đã quy định.
  - Tổng lượng token qua 89 calls: **`412,295` input tokens**, **`433,024` padded tokens**.
  - Thứ tự crossover 3 vòng lặp (`seed = 20261108`): `[[16, 64, 32], [64, 32, 16], [32, 16, 64]]`.
- **Kết quả Stress Memory (448-token longest passage):**
  - Cả 4 mức `stress-16`, `stress-32`, `stress-64`, `stress-128` đều `PASS` (không bị OOM), với `max_cosine_deviation = 0.000134 <= 0.001`.
  - Tại `stress-128` (`57,344` tokens): `peak_allocated_bytes = 12.63 GB` (`53.32%` VRAM), `peak_reserved_bytes = 20.56 GB` (`86.79%` VRAM), `client_elapsed_seconds = 23.70s` (`remote_elapsed_seconds = 12.66s`).

#### Bảng Đối soát Hiệu năng Warm Calls (3 Repeats × 256 Unique Passages = 768 Docs / Candidate)

| Batch size | Warm Calls | Docs | Real Input Tokens | Padded Tokens | Padding Ratio (`padded/input`) | Client Time (s) | Remote Time (s) | GPU CUDA Time (s) | RPC Overhead / Call (s) | **Warm Client docs/s** | Warm Remote docs/s | Warm GPU docs/s | GPU Padded tok/s | Peak Allocated VRAM (Warm / Stress) | Allocated Headroom | Reserved VRAM (Stress / Pool) | Max Cosine Dev |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **16** | 48 | 768 | 101,403 | 104,208 | `1.0277` (+2.77%) | 44.730 | **22.105** | **21.339** | 0.471s | 17.170 | **34.744** | **35.991** | **4,883.5** | 8.51 GB / 8.68 GB | **63.36%** | 9.36 GB / 20.56 GB* | `0.000525` |
| **32** | 24 | 768 | 101,403 | 107,040 | `1.0556` (+5.56%) | 35.146 | 23.601 | 22.968 | 0.481s | 21.851 | 32.541 | 33.439 | 4,660.5 | 8.92 GB / 9.24 GB | **61.00%** | 10.96 GB / 20.56 GB* | `0.000518` |
| **64** | 12 | 768 | 101,403 | 113,664 | `1.1209` (+12.09%) | **33.389** | 25.892 | 25.253 | 0.625s | **23.002** | 29.661 | 30.412 | 4,501.0 | 9.73 GB / 10.37 GB | **56.22%** | 14.16 GB / 20.56 GB* | `0.000885` |

*\*Lưu ý về `reserved_headroom_fraction` (`F-M3OPTV2-01` — mức `low`, không chặn): Do `stress-128` chạy trước vòng lặp warm và không bị OOM, PyTorch CUDA caching allocator giữ lại pool bộ nhớ đã cấp phát (`20.56 GB` = `86.79%` VRAM) cho toàn bộ các lệnh gọi tiếp theo trên cùng container (vì `torch.cuda.empty_cache()` chỉ được gọi khi xảy ra `OutOfMemoryError`). Do đó `reserved_headroom_fraction` ghi nhận `13.21%` cho cả 3 kích thước batch, trong khi mức `peak_reserved_bytes` thực tế của riêng từng kích thước đo tại `stress-16/32/64` lần lượt là `9.36 GB` (`60.49%` headroom), `10.96 GB` (`53.74%` headroom), và `14.16 GB` (`40.23%` headroom).*

#### Phân rã Padding theo Từng Nhóm Độ dài (Per-Stratum Breakdown — 1 Repeat = 64 Docs)

| Stratum | Độ dài Token (`min..max`) | Input Tokens (1 pass) | Padded `bs=16` (Ratio) | Padded `bs=32` (Ratio) | Padded `bs=64` (Ratio) |
|---|---|---|---|---|---|
| `length_quarter_1` | `34..49` | 2,597 | 2,720 (`1.0474`) | 2,848 (`1.0967`) | 3,136 (`1.2075`) |
| `length_quarter_2` | `78..88` | 5,309 | 5,376 (`1.0126`) | 5,472 (`1.0307`) | 5,632 (`1.0608`) |
| `length_quarter_3` | `122..136` | 8,277 | 8,400 (`1.0149`) | 8,512 (`1.0284`) | 8,704 (`1.0516`) |
| `length_quarter_4` | `222..319` | 17,618 | 18,240 (`1.0353`) | 18,848 (`1.0698`) | 20,416 (`1.1588`) |
| **Tổng (1 pass = 256 docs)** | **`34..319`** | **33,801** | **34,736 (`1.0277`)** | **35,680 (`1.0556`)** | **37,888 (`1.1209`)** |

- **Nhận định từ Benchmark V2:** Khi loại bỏ hiện tượng phình padding giả tạo của mẫu quantile V1 (tỷ lệ padding ở `bs=64` giảm từ `33.23%` ở V1 xuống `10.79%` tổng padded tokens ở V2), **`batch_size = 64` vượt lên dẫn đầu về tốc độ toàn trình từ phía client (`23.00 docs/s`, nhanh hơn `+5.3%` so với `bs=32` và `+34.0%` so với `bs=16`)** nhờ giảm số cuộc gọi RPC từ 48 (`bs=16`) và 24 (`bs=32`) xuống còn 12 cuộc gọi cho mỗi 768 tài liệu. Đúng quy ước, kết quả này ghi nhận `batch_size = 64` là *fastest observed* trên 4 cửa sổ pilot đã đo, không tự động suy diễn thành kết luận tuyệt đối cho toàn bộ phân phối full corpus.

---

### 4.3. Search Benchmark & Đo Walltime Subprocess (`search-benchmark` & `Measure-Command`)

Bảng phân tách rõ các ranh giới thời gian (không gộp chung thời gian truy hồi cục bộ với thời gian RPC hay thời gian khởi tạo tiến trình CLI):

| Phép đo / Lượt chạy | Subprocess Walltime (`Measure-Command`) | Internal CLI (`full_cli_seconds`) | Khởi tạo Session (`session_init`) | Warm Request gồm RPC (`warm_session_request`) | Client RPC (`client_rpc_seconds`) | GPU Remote (`remote_total_seconds`) | Truy hồi Cục bộ (`local_retrieval_seconds`) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **`search-benchmark` — Query 1** (`"standard of review"`, `excl=null`) | — | 13.370s (cả 3 queries) | 0.592s | 5.297s | 4.039s | 0.305s | `0.211s / 0.206s / 0.236s` (mean **`0.218s`**) |
| **`search-benchmark` — Query 2** (`"standard of review"`, `excl=079659.txt`) | — | ↑ | ↑ | 2.976s | 2.162s | 0.055s | `0.174s / 0.180s / 0.238s` (mean **`0.197s`**) |
| **`search-benchmark` — Query 3** (`"décision n'est pas..."`, `excl=null`) | — | ↑ | ↑ | 2.899s | 2.108s | 0.112s | `0.181s / 0.182s / 0.264s` (mean **`0.209s`**) |
| **Standalone CLI Run 1** ([`search_walltime_01.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/search_walltime_01.json)) | **6.585s** | 6.381s | 0.608s | 5.373s | 4.165s | 0.055s | **0.201s** |
| **Standalone CLI Run 2** ([`search_walltime_02.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/search_walltime_02.json)) | **6.511s** | 6.332s | 0.596s | 5.528s | 4.402s | 0.062s | **0.198s** |
| **Standalone CLI Run 3** ([`search_walltime_03.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/search_walltime_03.json)) | **6.338s** | 6.149s | 0.615s | 5.323s | 4.152s | 0.142s | **0.214s** |

- **Phân tích các thành phần độ trễ:**
  1. **Truy hồi cục bộ (`local_retrieval_seconds` — gồm kiểm tra Qdrant schema/count, dense search, kiểm tra payload/score, BM25 2 kênh `case` + `passage` trên SQLite, và hợp nhất RRF `k=60`):** Đạt trung bình **`0.208s`** (`0.174s – 0.264s`), giảm **~5.2 lần** so với mức `1.091s` của bản tối ưu V1 và giảm **~310 lần** so với phần dựng lại cục bộ của baseline (`~65s`).
  2. **Khởi tạo `FastSession` (`session_initialization_seconds` — gồm kiểm tra seal SHA-256 của 3 file index, kiểm tra SHA-256 của 916 raw cases, mở SQLite readonly và mmap `vectors.npy`):** Mất **`0.56s – 0.61s`**.
  3. **Gọi RPC mã hóa câu truy vấn (`client_rpc_seconds`):**
     - Khi chạy trong cùng một phiên ấm (`search-benchmark` Query 2 & 3), thời gian RPC là **`2.11s – 2.16s`** (`remote_total_seconds = 0.055s – 0.112s`), giúp tổng thời gian `warm_session_request_seconds_including_RPC` đạt **`2.90s – 2.98s`**.
     - Khi khởi chạy từ một tiến trình CLI mới tinh (`search_walltime_01..03` hoặc Query 1 đầu phiên), lần gọi đầu tiên của `modal.Cls.from_name(...).remote()` tốn thêm ~2s thiết lập kết nối gRPC/lookup stub với Modal (`client_rpc_seconds = 4.04s – 4.40s`, dù GPU remote vẫn chỉ mất `0.055s – 0.142s` trên container đã ấm).
  4. **Tổng thời gian Walltime ngoài tiến trình (`Measure-Command`):** Đạt **`6.34s – 6.59s`** (trong đó `full_cli_seconds` là `6.15s – 6.38s` và chi phí nạp Python process/teardown là `0.18s – 0.20s`), nhanh hơn **~10.3 lần** so với `66.2s – 67.3s` của baseline CLI.

---

## 5. Danh mục File Bằng chứng Độc lập đã Tạo

Tất cả các file kiểm thử, kết quả đo và đối soát được lưu trong [`pipeline_v2/reviews/m3_opt_v2_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1):

- [`REPORT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/REPORT.md): Báo cáo tổng hợp kết quả kiểm thử local, preflight, GPU benchmark, search latency và phân tích giới hạn.
- [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/findings.json): Kết luận phân tách theo 5 hạng mục, trạng thái phân xử 6 finding từ V1 (`RESOLVED_IN_V2`), và 2 ghi nhận không chặn (`F-M3OPTV2-01`, `F-M3OPTV2-02`).
- [`commands_and_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/commands_and_results.json): Nhật ký toàn bộ các lệnh đã thực thi, exit codes, thời gian và đường dẫn artifact.
- [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/recomputed_metrics.json): Số liệu tính toán lại độc lập từ các file SQLite ledger, manifest, seal và raw cases.
- [`test_m3_opt_v2_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/test_m3_opt_v2_independent_ag.py) & [`independent_local_test_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/independent_local_test_results.json): Script kiểm thử độc lập (BM25 512-row batching, relative path, 16-query oracle, session tamper invalidation, vector NaN audit) và kết quả chạy.
- [`recompute_all_v2_metrics.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/recompute_all_v2_metrics.py): Script đối soát độc lập toàn bộ ledgers và artifacts V2.
- [`search_walltime_01.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/search_walltime_01.json), [`search_walltime_02.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/search_walltime_02.json), [`search_walltime_03.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_opt_v2_ag_review_v1/search_walltime_03.json): Kết quả đầu ra của 3 lượt đo `Measure-Command` cho lệnh `m3_opt_v2 search`.
