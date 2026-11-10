# Báo cáo Chẩn đoán Có Đối chứng Độ trễ M3 Full Search & Phân rã Bottleneck BM25

- **Ngày thực hiện:** `2026-11-09`
- **Thư mục bằng chứng:** [`pipeline_v2/reviews/m3_search_latency_diagnostic_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1)
- **Phạm vi & Tuân thủ ràng buộc:**
  - Chỉ đọc đối với toàn bộ code production (`pipeline_v2/`), cấu hình (`configs/`), chỉ mục (`m3_full_train_20261108_v1`), nguồn raw (`data/task1_train_files_2026/cases`) và Qdrant local (`coliee_m3_full_ef2f4d6950a5b9fd`).
  - **Không** gọi Modal, **không** deploy/inference, **không** đọc `.env`, **không** đọc gold/labels, **không** sửa bất kỳ tệp production/seal/cache nào.

---

## 1. Kiểm toán Bằng chứng Trước đó (`m3_full_search_plan_ag_review_v1`)

Kết quả kiểm toán chi tiết được lưu tại [`prior_evidence_audit.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/prior_evidence_audit.json):

| Script / Artifact trong `m3_full_search_plan_ag_review_v1` | Tồn tại trên đĩa? | Trạng thái thực thi thực tế | Phân loại bằng chứng |
|---|---|---|---|
| [`probe_plan_assumptions.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_plan_assumptions.py) $\rightarrow$ [`probe_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_results.json) (`3,611` bytes) | **Có (`True`)** | Chạy thành công tới hết `ALL DONE`. | **Số đo thật đã lưu:** `EXPLAIN QUERY PLAN`; đọc 1 shard `.npz` (`10.875 ms`); Qdrant `batch=0` `vec0` (`exact=False` và `exact=True`, gồm lỗi HTTP 500 timeout tại `60.167s` khi thiếu `?timeout=120`); 1 câu BM25 (`case=4.5872s`, `passage=121.5137s`). |
| [`probe_deep_dive.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_deep_dive.py) $\rightarrow$ `probe_deep_dive_results.json` | **KHÔNG (`False`)** | **Lỗi trước khi ghi file:** In kết quả bước 1 và 2 ra stdout, sau đó dừng vì ngoại lệ tại dòng 178 (`nr.open_context("055641.txt", "p000001")`) do `055641.txt` bắt đầu từ `u000001` và `p000351`, trước khi tới dòng 189 ghi `probe_deep_dive_results.json`. | **Thiếu artifact lưu đĩa:** Các con số trích dẫn từ stdout của lần chạy lỗi này (`104.22s` vs `52.18s`, `2.42s` vs `2.65s`, `2,860` vs `97` shards) **không được dùng làm kết luận** trong báo cáo này và đã được đo lại đầy đủ có lưu trữ. |
| [`probe_mmap_and_open.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_mmap_and_open.py) $\rightarrow$ [`probe_mmap_and_open_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_mmap_and_open_results.json) (`761` bytes) | **Có (`True`)** | Chạy thành công (sau khi sửa dòng 51 lấy `large_meta["parent_handle"]` = `"p000351"`). | **Số đo thật đã lưu:** `cache_size=-2000, mmap_size=0`; BM25 có `mmap=4GiB` nhưng vẫn giữ `JOIN documents` (`86.571s`, `63.6325s`); độ trễ `open_context` (`2.4576s` trên `055641.txt`); phân phối `5` parents và `13` cửa sổ `> 64 KiB`. |
| [`test_plan_counterexamples.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/test_plan_counterexamples.py) $\rightarrow$ [`counterexample_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/counterexample_results.json) (`2,962` bytes) | **Có (`True`)** | Chạy thành công `11/11 PASS`. | **Kiểm thử logic / counterexample đơn vị** trên dữ liệu giả lập tất định (`CE01..CE11`). |
| Các ước lượng giải tích trong báo cáo trước (`"~25 MB"` RAM, `"~31.1s"` / `"~1.0s"` kiểm tra shard) | — | Không có phép đo trực tiếp trong kỳ trước. | **Ngoại suy / Ước lượng chưa đo:** Trong đợt chẩn đoán này, chúng tôi thay thế toàn bộ bằng phép đo trực tiếp (`tracemalloc` + Windows `GetProcessMemoryInfo` + chạy thật `ReadonlyCache`). |

---

## 2. Khóa Workload Tất định Trước Khi Benchmark ([`workload_manifest.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json))

### 2.1. Quy tắc chọn và trạng thái Exposure / Holdout
- **Xác định tập Holdout cần tránh tuyệt đối:**
  - `20` án train holdout trong [`knowledge_base/pipeline_v1/manifests/split_registry.v1.json`](file:///e:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/manifests/split_registry.v1.json) (`reserved_holdout`).
  - `10` án holdout và `10` án discovery cùng `1,522` án fresh eligible trong [`pipeline_v2/artifacts/m0_20261105_v2/cohort.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m0_20261105_v2/cohort.json).
- **Nguồn lấy mẫu tất định (Exposed Diagnostic Pool):**
  - Để tuyệt đối không chạm vào bất kỳ án holdout hay làm lộ thêm án fresh nào trong `cohort.json`, tập nguồn ứng viên gồm đúng `15` án train đã được đánh dấu công khai là `development` (`10` án) và `calibration` (`5` án) trong `split_registry.v1.json` (giao bằng `0` với mọi tập holdout/fresh).
  - **Tuyên bố trung thực:** Đây là **mẫu chẩn đoán kỹ thuật từ các án đã exposed (diagnostic exposed workload), KHÔNG phải mẫu blind evaluation**.
- **Quy tắc chọn 8 câu truy vấn (`seed = 20261109`):**
  - Dùng `random.Random(20261109).sample(candidate_pool, 8)` chọn 8 `query_case` trước khi chạy bất kỳ phép đo nào.
  - Với án thứ $i \in \{0..7\}$, bắt đầu từ ký tự xuống dòng `\n` đầu tiên sau vị trí `len(raw_text) // 3` và trích nguyên văn $W_i$ token phân tách bởi khoảng trắng theo dãy cố định $W = [4, 6, 8, 12, 16, 24, 36, 56]$ để bao phủ tự nhiên từ truy vấn ngắn đến truy vấn dài mà không chọn theo độ trễ, điểm số hay gold.

### 2.2. Bảng 8 Truy vấn BM25 Đã Khóa (`Q01..Q08`)

| ID | `query_case` (Exclusion) | `span_bytes` | Lexical Tokens | Unique Terms | Tổng `df` Postings (`case`) | Tổng `df` Postings (`passage`) | Postings Hợp lệ Sau Exclusion (`passage`) | Max Term `df` (`passage`) | Trích dẫn văn bản đầu câu truy vấn |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| **`Q01`** | `011904.txt` | `[17208, 17245]` | 4 | 4 | 20,184 | **245,083** | 244,983 | 177,090 (`at`) | `<FRAGMENT_SUPPRESSED>  (QL), at para.` |
| **`Q02`** | `006725.txt` | `[31987, 32028]` | 6 | 6 | 35,132 | **480,176** | 479,734 | 359,820 (`the`) | `[14]\r\nFinally, the tribunal could also` |
| **`Q03`** | `043625.txt` | `[30861, 30902]` | 8 | 8 | 39,121 | **863,196** | 862,535 | 359,820 (`the`) | `Annual review of orders\r\n131. (1) The Board` |
| **`Q04`** | `013948.txt` | `[6857, 6926]` | 12 | 12 | 71,519 | **1,387,108** | 1,386,784 | 359,820 (`the`) | `(1) Before making a decision, was the PRRA officer required to give` |
| **`Q05`** | `047415.txt` | `[97067, 97156]` | 16 | 14 | 60,036 | **1,157,969** | 1,156,193 | 359,820 (`the`) | `(b) When Mr. Mahjoub is at home alone, the ethernet wire...` |
| **`Q06`** | `099980.txt` | `[63390, 63512]` | 24 | 18 | 82,045 | **1,874,283** | 1,872,499 | 359,820 (`the`) | `[73]\r\nIt is that aspect of the judgment in Seck 1 that is...` |
| **`Q07`** | `040898.txt` | `[4809, 4997]` | 38 | 35 | 178,769 | **2,340,921** | 2,340,791 | 359,820 (`the`) | `<FRAGMENT_SUPPRESSED> ; 302 N.R. 178; 2003 FCA 39 (F.C.A.)...` |
| **`Q08`** | `034501.txt` | `[7363, 7697]` | 56 | 47 | 227,554 | **3,639,697** | 3,639,340 | 359,820 (`the`) | `[5] \r\n  At any rate, in August 2009, the citizenship officer...` |

### 2.3. Bảng 3 Vector Chẩn đoán Kênh Dense Đã Khóa (`V01..V03`)
Được chọn tất định từ bảng `schedule` (`6,496` batches `0..6495`, sắp theo `full_input_tokens` tăng dần) tại 3 phân vị cố định `batch = 1000, 3248, 5500` (`ordinal_in_batch = 0`) trước khi xem kết quả:
- **`V01`**: `batch=1000`, `passage_id="095448:88b488d43fde1389756a8dd7"`, `exclude_case="095448.txt"`, `full_input_tokens=46`.
- **`V02`**: `batch=3248`, `passage_id="041666:b5120463c47e98934ef7bde9"`, `exclude_case="041666.txt"`, `full_input_tokens=106`.
- **`V03`**: `batch=5500`, `passage_id="000713:3a2a0520d60f55dd1d773c75"`, `exclude_case="000713.txt"`, `full_input_tokens=246`.

---

## 3. Môi trường Hệ thống, Cấu trúc SQLite và Chi phí Startup / Preload Thực tế

### 3.1. Thông số môi trường và SQLite ([`environment_snapshot.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/environment_snapshot.json), [`sqlite_and_preload_diagnostics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/sqlite_and_preload_diagnostics.json))
- **Hệ điều hành & Phần cứng:** Windows 11 (`10.0.26100`), 12 luồng CPU, Python `3.12.0`, SQLite `3.42.0`.
- **Bộ nhớ vật lý (RAM) & Đĩa:** Tổng RAM **`11.611 GiB`** (`12,467,421,184` bytes), RAM trống khả dụng lúc bắt đầu **`3.106 GiB`** (`73%` memory load; các tiến trình đang chạy gồm `vmmemWSL` `583.5 MB`, `ChatGPT` `451 MB`, `WizTree64` `374 MB`, `brave` `341.7 MB`, `language_server` `332.1 MB`). Đĩa `E:` trống **`41.987 GiB`**, `C:` trống **`4.535 GiB`**.
- **Kích thước và cấu trúc `lexical.sqlite3`:**
  - Dung lượng tệp: **`4,357,505,024` bytes (`4.0582 GiB`)** = `1,063,844` trang × `4,096` bytes/trang (`freelist_count = 0`).
  - **PRAGMAs mặc định (Phương án A & B):** `cache_size = -2000` ($\approx 2\text{ MiB}$), `mmap_size = 0`, `temp_store = 0`, `query_only = 1`.
  - **PRAGMAs cấu hình rõ (Phương án C):** `mmap_size = 4294967296` ($4\text{ GiB}$), `cache_size = -524288` ($512\text{ MiB}$), `temp_store = MEMORY`, `query_only = 1`.
  - **Thống kê bảng `documents` và `postings`:**
    - Kênh `case`: `7,708` tài liệu, `avg_length = 4,747.40`, tổng metadata JSON = `832,464` bytes (`108` bytes/hàng); `112,492` từ khóa phân biệt, tổng cộng **`7,368,370` postings** (`max_df = 7,708`).
    - Kênh `passage`: `415,693` đoạn văn, `avg_length = 94.98`, tổng metadata JSON = **`667,359,391` bytes (`~636.4 MiB`, trung bình `1,605.41` bytes/hàng, tối đa `1,816` bytes/hàng)**; `113,404` từ khóa phân biệt, tổng cộng **`24,592,796` postings** (`max_df = 359,820`).
- **Kế hoạch thực thi truy vấn (`EXPLAIN QUERY PLAN`):**
  - **Phương án A (`JOIN documents`):**
    1. `SEARCH p USING INDEX sqlite_autoindex_postings_1 (kind=? AND term=?)`
    2. `SEARCH d USING INDEX sqlite_autoindex_documents_1 (kind=? AND id=?)`
  - **Phương án B & C (Không `JOIN`):**
    1. `SEARCH postings USING INDEX sqlite_autoindex_postings_1 (kind=? AND term=?)`

### 3.2. Chi phí Startup / Preload và Peak RAM Thực tế (So với ước lượng `"~25 MB"` trước đây)

Báo cáo trước ước lượng việc nạp `passage_id -> length` tốn `"~25 MB"` mà chưa đo thực tế. Phép đo trực tiếp bằng cả `tracemalloc` (Python heap) và Windows `GetProcessMemoryInfo` (`WorkingSetSize` & `PrivateUsage`, đo độc lập khi tắt `tracemalloc`) cho kết quả chính xác như sau:

| Cấu hình dữ liệu Preload (`case` 7.708 hàng + `passage` 415.693 hàng) | Thời gian Preload (`s`) | Python Heap Delta (`tracemalloc`) | Peak Python Heap (`tracemalloc`) | OS `WorkingSet` Delta (Không `tracemalloc`) | OS `PrivateUsage` Delta (Không `tracemalloc`) | Ghi chú kỹ thuật |
|---|---:|---:|---:|---:|---:|---|
| **Chỉ `case_lengths` + `case_case_ids` (`7,708` hàng)** | `0.042s` | **`1.390 MiB`** (`1,457,010` B) | `1.390 MiB` | — | — | Rất nhỏ, nạp tức thời. |
| **Chỉ `passage_lengths` (`dict[str, int]`, `415,693` hàng)** | — | **`44.957 MiB`** (`47,140,661` B) | — | — | — | Đủ để chạy `passage_bm25` nếu tách `case_id` từ tiền tố `id[:6] + ".txt"` (đã xác minh đúng **100%** trên cả `415,693` hàng). |
| **Đầy đủ `lengths` + `sys.intern(case_id)` cho cả `case` và `passage` (Dùng trong B & C)** | **`2.927s`** (`3.524s` khi bật `tracemalloc`) | **`50.251 MiB`** (`52,692,005` B) | **`50.255 MiB`** | **`+65.656 MiB`** (`46.52` $\rightarrow$ `112.18 MiB`) | **`+65.508 MiB`** (`418.23` $\rightarrow$ `483.73 MiB`) | `sys.intern(cid)` gộp 415.693 chuỗi `case_id` về đúng 7.708 đối tượng chuỗi duy nhất. |
| **Đầy đủ `lengths` + `case_id` KHÔNG `sys.intern`** | `6.295s` | **`79.839 MiB`** (`83,717,179` B) | **`79.839 MiB`** | — | — | Tốn thêm `~29.6 MiB` vì cấp phát lặp 415.693 chuỗi `"XXXXXX.txt"`. |

> **Kết luận về RAM Preload:** Con số `"~25 MB"` trước đây là ước lượng thấp hơn thực tế. Số đo thật trên Python 3.12 64-bit là **`44.96 MiB` heap** (nếu chỉ lưu `id -> length` và dùng tiền tố `id[:6]`) hoặc **`50.25 MiB` heap / `+65.5 MiB` OS Private RAM** (nếu lưu cả `id -> interned_case_id` cho cả hai kênh), với thời gian nạp một lần khi mở session là **`2.927 giây`**.

---

## 4. Kết quả Đo Phân rã BM25 (`A` vs `B` vs `C`) và Kiểm chứng Độ chính xác

### 4.1. Kiểm chứng Độ chính xác (`correctness_comparison.json`)
- **Kiểm tra với `IndependentBM25Oracle` trên bộ fixtures nhỏ (`12/12` phép thử):** Cả 3 phương án `A`, `B`, `C` khớp 100% danh sách ID và điểm số với oracle độc lập (`max_score_diff = 0.0 <= 1e-12`).
- **Kiểm tra giữa `PersistentBM25.search()` nguyên bản (không gắn timer từng bước) và `Variant A` có gắn timer trên `Q01`:** Khớp 100% ID, điểm số (`max_abs_score_diff = 0.0`) và metadata.
- **Kiểm tra trên toàn bộ 8 câu truy vấn thật (`Q01..Q08`) ở cả 2 kênh `case` và `passage` (`limit = 4096`):**
  - Danh sách ID xếp hạng của `A`, `B`, và `C`: **Khớp tuyệt đối 100% (`ids_exact_match = True` trên cả 16/16 cặp kênh × truy vấn)**.
  - Độ lệch điểm số tuyệt đối lớn nhất giữa `A`, `B`, và `C`: **`0.0` (khớp từng bit IEEE-754 float64)** vì cả 3 phương án duyệt `sorted(set(analyze(query)))` và `postings` theo đúng thứ tự khóa chính `(kind, term, id)`.
  - Metadata trả về: **Khớp tuyệt đối 100% (`metadata_exact_match = True`)**.

### 4.2. Phân rã Thời gian Kênh `passage` BM25 (`limit = 4096`, 1 First-Observed + 3 Warm Crossover Repeats)

Bảng dưới đây trình bày **median [min .. max]** của 3 lượt `warm_repeat` (đổi thứ tự `A, B, C` theo crossover seed) cùng lượt `first_observed` cho từng truy vấn `Q01..Q08`:

| Query (`Terms` / `Postings`) | Phương án | `First Observed` Total (`s`) | **Warm Total Median (`s`)** `[Min .. Max]` | Pha `b`: `df/stats` Warm Med (`s`) | **Pha `c`: SQLite Postings (+JOIN ở A) Warm Med (`s`) `[Min .. Max]`** | Pha `d`: Python Scoring Warm Med (`s`) | Pha `e`: Sort Top Hits Warm Med (`s`) | Pha `f`: Metadata (`4096` / `100` hits) Warm Med (`s`) | Tốc độ tăng so với A (Warm Median) | Số Query Hòa vốn Preload (`2.927s`) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **`Q01`** (`4` / `245,083`) | **A** | 86.638 | **45.600** `[3.173 .. 71.610]` | 0.0002 | **44.871** `[2.580 .. 70.993]` (98.4%) | 0.162 | 0.201 | 0.259 / 0.0038 | `1.00x` | — |
| | **B** | 55.246 | **2.265** `[1.989 .. 11.494]` | 0.0002 | **1.513** `[1.293 .. 10.804]` (66.8%) | 0.293 | 0.188 | 0.219 / 0.0037 | **`20.14x`** | `0.068` |
| | **C** | 55.850 | **1.094** `[1.069 .. 1.266]` | 0.0001 | **0.450** `[0.450 .. 0.524]` (41.2%) | 0.319 | 0.227 | 0.153 / 0.0020 | **`41.67x`** | **`0.066`** |
| **`Q02`** (`6` / `480,176`) | **A** | 70.171 | **60.686** `[43.566 .. 78.902]` | 0.0002 | **59.473** `[42.481 .. 77.677]` (98.0%) | 0.374 | 0.468 | 0.321 / 0.0042 | `1.00x` | — |
| | **B** | 24.936 | **5.719** `[4.260 .. 19.865]` | 0.0002 | **4.301** `[2.878 .. 18.691]` (75.2%) | 0.618 | 0.490 | 0.186 / 0.0039 | **`10.61x`** | `0.053` |
| | **C** | 2.861 | **2.983** `[2.963 .. 3.121]` | 0.0001 | **1.618** `[1.593 .. 1.751]` (54.2%) | 0.627 | 0.514 | 0.236 / 0.0020 | **`20.34x`** | **`0.051`** |
| **`Q03`** (`8` / `863,196`) | **A** | 150.076 | **10.432** `[8.971 .. 125.844]` | 0.0002 | **9.212** `[7.728 .. 124.496]` (88.3%) | 0.540 | 0.527 | 0.222 / 0.0035 | `1.00x` | — |
| | **B** | 99.009 | **5.749** `[5.665 .. 11.950]` | 0.0003 | **4.113** `[4.065 .. 10.132]` (71.5%) | 0.947 | 0.461 | 0.244 / 0.0042 | **`1.81x`** | `0.625` |
| | **C** | 49.707 | **4.123** `[4.103 .. 4.828]` | 0.0001 | **2.643** `[2.610 .. 3.200]` (64.1%) | 0.885 | 0.447 | 0.193 / 0.0019 | **`2.53x`** | **`0.464`** |
| **`Q04`** (`12` / `1,387,108`) | **A** | 32.736 | **95.059** `[14.237 .. 98.188]` | 0.0003 | **93.388** `[12.508 .. 96.493]` (98.2%) | 0.965 | 0.520 | 0.268 / 0.0044 | `1.00x` | — |
| | **B** | 14.569 | **10.605** `[7.372 .. 15.869]` | 0.0003 | **7.790** `[4.787 .. 13.098]` (73.5%) | 1.676 | 0.487 | 0.241 / 0.0037 | **`8.96x`** | `0.035` |
| | **C** | 6.472 | **6.959** `[6.386 .. 7.122]` | 0.0002 | **4.581** `[3.923 .. 4.716]` (65.8%) | 1.547 | 0.484 | 0.193 / 0.0019 | **`13.66x`** | **`0.033`** |
| **`Q05`** (`14` / `1,157,969`) | **A** | 196.344 | **104.860** `[27.883 .. 144.692]` | 0.0003 | **103.328** `[26.570 .. 143.138]` (98.5%) | 0.716 | 0.450 | 0.340 / 0.0040 | `1.00x` | — |
| | **B** | 91.168 | **26.464** `[7.643 .. 32.927]` | 0.0003 | **23.579** `[5.699 .. 29.839]` (89.1%) | 1.214 | 0.468 | 1.123 / 0.0045 | **`3.96x`** | `0.037` |
| | **C** | 42.335 | **15.931** `[5.764 .. 28.149]` | 0.0002 | **14.048** `[3.854 .. 26.256]` (88.2%) | 1.245 | 0.450 | 0.185 / 0.0021 | **`6.58x`** | **`0.033`** |
| **`Q06`** (`18` / `1,874,283`) | **A** | 23.692 | **206.195** `[18.120 .. 294.489]` | 0.0004 | **204.173** `[16.409 .. 292.324]` (99.0%) | 1.254 | 0.468 | 0.268 / 0.0050 | `1.00x` | — |
| | **B** | 11.226 | **19.719** `[11.177 .. 22.037]` | 0.0004 | **16.697** `[8.604 .. 17.047]` (84.7%) | 1.941 | 0.485 | 0.241 / 0.0078 | **`10.46x`** | `0.016` |
| | **C** | 7.985 | **8.140** `[7.905 .. 69.622*]` | 0.0003 | **5.386** `[5.342 .. 64.572*]` (66.2%) | 1.993 | 0.581 | 0.199 / 0.0022 | **`25.33x`** | **`0.015`** |
| **`Q07`** (`35` / `2,340,921`) | **A** | 151.169 | **247.449** `[209.401 .. 297.277]` | 0.0007 | **243.485** `[207.087 .. 294.655]` (98.4%) | 1.637 | 0.515 | 0.340 / 0.0048 | `1.00x` | — |
| | **B** | 25.831 | **16.884** `[15.069 .. 51.034]` | 0.0006 | **13.277** `[11.939 .. 47.372]` (78.6%) | 2.707 | 0.543 | 0.258 / 0.0044 | **`14.66x`** | `0.013` |
| | **C** | 12.095 | **11.714** `[9.833 .. 33.140*]` | 0.0004 | **7.970** `[6.715 .. 29.698*]` (68.0%) | 2.757 | 0.482 | 0.193 / 0.0024 | **`21.12x`** | **`0.012`** |
| **`Q08`** (`47` / `3,639,697`) | **A** | 242.378 | **90.540** `[68.345 .. 285.604]` | 0.0009 | **87.603** `[65.477 .. 282.560]` (96.8%) | 2.272 | 0.494 | 0.167 / 0.0041 | `1.00x` | — |
| | **B** | 44.867 | **25.808** `[22.109 .. 33.239]` | 0.0009 | **21.409** `[17.860 .. 28.874]` (83.0%) | 3.661 | 0.469 | 0.158 / 0.0049 | **`3.51x`** | `0.045` |
| | **C** | 14.925 | **14.768** `[14.627 .. 14.811]` | 0.0005 | **10.471** `[10.392 .. 10.552]` (70.9%) | 3.609 | 0.472 | 0.187 / 0.0022 | **`6.13x`** | **`0.039`** |
| **Tổng hợp 8 Queries (Median của Medians)** | **A** | **118.357** `[23.69 .. 242.38]` | **92.799** `[10.432 .. 247.449]` | 0.0003 | **90.495** `[9.212 .. 243.485]` | 0.841 | 0.470 | 0.263 / 0.0042 | `1.00x` | — |
| | **B** | **35.349** `[11.23 .. 99.01]` | **13.745** `[2.265 .. 26.464]` | 0.0003 | **10.744** `[1.513 .. 23.579]` | 1.445 | 0.477 | 0.230 / 0.0043 | **`6.75x`** | `0.041` |
| | **C** | **13.510** `[2.86 .. 55.85]` | **7.549** `[1.094 .. 15.931]` | 0.0002 | **4.984** `[0.450 .. 14.048]` | 1.397 | 0.481 | 0.193 / 0.0020 | **`12.29x`** | **`0.034`** |

*\*Ghi chú về hiện tượng nhiễu crossover (`*` ở `Q06 pass=3` và `Q07 pass=3`):* Trong `Q06`, ở các lượt `pass=0, 1, 2` (khi `C` chạy trước `A`), `Variant C` chỉ mất **`7.985s`, `7.905s`, `8.140s`**. Cuối `pass=2`, `Variant A` chạy và mất **`294.489s`** (quét ngẫu nhiên hàng trăm MB bảng `documents`, đẩy các trang `postings` khỏi `~3.1 GiB` RAM trống của hệ thống). Ngay sau đó ở đầu `pass=3` (thứ tự crossover `C -> A -> B`), `Variant C` phải nạp lại các trang `postings` từ đĩa nên mất `69.622s`. Khi không có `Variant A` chạy xen kẽ làm loạn OS cache, `Variant C` giữ độ trễ ổn định **`1.09s – 14.77s`** trên toàn bộ dải `245k – 3.64M` postings.

### 4.3. Phân rã Thời gian Kênh `case` BM25 (`limit = 4096`)
Trên kênh `case` (`7,708` tài liệu, bảng `documents` chỉ chứa `832 KB` metadata):
- **Phương án A:** Warm median qua 8 truy vấn = **`0.584s`** (`[0.196s .. 1.943s]`), trong đó `Stage c` = `0.517s`, `Stage d` = `0.035s`, `Stage e` = `0.005s`, `Stage f` = `0.028s` (`0.0007s` nếu chỉ lấy top 100 cases).
- **Phương án B:** Warm median = **`0.456s`** (`[0.164s .. 1.619s]`), `Stage c` = `0.377s`.
- **Phương án C:** Warm median = **`0.176s`** (`[0.073s .. 0.570s]`, **nhanh hơn `3.31x` so với A**), `Stage c` = `0.101s`, `Stage d` = `0.045s`, `Stage f` (`limit=100`) = **`0.00067s` (`0.67 ms`)**.

---

## 5. Kết quả Đo Kênh Dense Cục bộ Công bằng ([`dense_measurements.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/dense_measurements.json))

Tất cả truy vấn Qdrant chạy với `exact=True`, `with_payload=True`, `with_vector=False`, bộ lọc `must=[embedding_fingerprint]` + `must_not=[case_id=query_case]`, tách biệt rõ **Qdrant server timeout (`?timeout=120` trên URL)** và **HTTP client timeout (`timeout=(10.0, 130.0)` trong `requests`)**:

| Vector (`batch` / `tokens`) | `limit` | `First Observed` Client / Server (`s`) | **Warm Client Median (`s`)** `[Min .. Max]` | **Warm Server Median (`s`)** `[Min .. Max]` | Số Unique Cases trả về | Số Shards `.npz` chạm (All Hits vs Top-100 Unique Cases) | Số điểm đồng hạng (`exact_score_ties`) | Kiểm tra thật `ReadonlyCache` Top-100 Leads (First Uncached vs Warm LRU) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`V01`** (`1000` / `46` tok) | `256` | **`81.800s` / `81.717s`** | **1.033s** `[0.762 .. 1.314]` | **1.009s** `[0.746 .. 1.301]` | 256 | `194` vs **`89`** | 26 | **`4.031s`** cold / **`0.00052s`** LRU |
| | `4096` | `2.771s` / `2.637s` | **1.151s** `[0.918 .. 1.199]` | **1.023s** `[0.833 .. 1.077]` | 3,945 | `1,469` vs **`89`** | 446 | ↑ |
| **`V02`** (`3248` / `106` tok) | `256` | `0.938s` / `0.928s` | **0.936s** `[0.744 .. 1.178]` | **0.911s** `[0.725 .. 1.167]` | 170 | `244` vs **`98`** | 4 | **`3.922s`** cold / **`0.00065s`** LRU |
| | `4096` | `1.907s` / `1.856s` | **0.966s** `[0.484 .. 1.378]` | **0.880s** `[0.368 .. 1.329]` | 1,169 | `2,882` vs **`98`** | 60 | ↑ |
| **`V03`** (`5500` / `246` tok) | `256` | `1.384s` / `1.375s` | **0.799s** `[0.575 .. 1.067]` | **0.780s** `[0.548 .. 1.055]` | **`97` (`< 100`!)** | `237` vs **`94`** | 1 | **`3.799s`** cold / **`0.00062s`** LRU |
| | `4096` | `2.298s` / `2.170s` | **1.007s** `[0.432 .. 1.332]` | **0.917s** `[0.354 .. 1.233]` | **`274` (`>= 100`)** | `2,627` vs **`97`** | 34 | ↑ |

**Ba phát hiện thực nghiệm quan trọng từ Kênh Dense:**
1. **Giải thích chính xác lỗi timeout 60s khi Qdrant cold (`V01 limit=256 = 81.800s`):** Ngay sau khi SQLite quét bảng `documents` ở bước kiểm tra trước đó, các trang vector `on_disk=True` của Qdrant trong WSL2 bị đẩy khỏi `3.1 GiB` RAM trống. Lượt truy vấn `exact=True` đầu tiên (`V01 limit=256`) mất **`81.717s`** để đọc lại `4.26 GB` vectors từ đĩa. Nhờ truyền `?timeout=120`, truy vấn hoàn tất thành công thay vì bị Qdrant ngắt ở `60.0s` như mặc định.
2. **Khi đã warm, `limit=256` và `limit=4096` có độ trễ tương đương (`~0.80s – 1.15s` median):** Vì `exact=True` luôn tính cosine trên toàn bộ `415,693` điểm.
3. **Bằng chứng trên dữ liệu thật cho thấy `limit=256` chưa đủ `100` unique cases (`V03`):** Với `V03` (`000713.txt`), `256` raw hits đầu tiên chỉ chứa **`97` unique cases (`< 100`)**, trong khi mở rộng lên `4,096` thu được **`274` unique cases**. Nếu truy vấn Qdrant 1 lần ở `limit=4096` (hoặc 2 bước `256 -> 4096`) rồi cắt cửa sổ adaptive trong RAM, ta lấy đủ `100` unique cases chỉ trong `~1.0s` warm.

---

## 6. Phân xử 5 Giả thuyết (`H1` – `H5`)

| Mã | Giả thuyết | Phán quyết | Số đo đối chứng & Giới hạn |
|---|---|---|---|
| **`H1`** | **`JOIN` / random lookup chiếm phần lớn thời gian** | **`SUPPORTED`** *(Nguyên nhân chính của Phương án A hiện tại)* | Trên kênh `passage`, Phương án A mất median **`92.80s`** warm (`[10.43s .. 247.45s]`), trong đó riêng **Pha `c` (`postings JOIN documents`) chiếm `90.50s` (`88.3% – 99.3%` tổng thời gian)**. Khi giữ nguyên mọi PRAGMA mặc định của SQLite và chỉ bỏ `JOIN documents` bằng bảng preload trong RAM (**Phương án B**), thời gian median warm giảm xuống **`13.74s`** (**nhanh hơn `6.75x`**, từng câu nhanh hơn `1.81x – 20.14x`), chứng minh phép `JOIN` ngẫu nhiên vào bảng `documents` (`667 MB` JSON metadata, ~2 hàng/trang 4KB) là thủ phạm số 1. *Giới hạn:* Sau khi bỏ `JOIN`, việc quét hàng triệu dòng `postings` của các từ khóa phổ biến (`the`, `of`) vẫn tốn `4.98s – 10.74s` ở Pha `c`. |
| **`H2`** | **Python scoring / sort chiếm phần lớn thời gian** | **`CONTRADICTED`** *(trên Phương án A; chỉ là chi phí tuyến tính thứ cấp ~25% sau khi đã tối ưu sang C)* | Trong Phương án A, **Pha `d` (Python scoring)** chỉ tốn median **`0.841s`** (`[0.162s .. 2.272s]`) và **Pha `e` (sort)** tốn **`0.470s`** (`[0.201s .. 0.527s]`) — cộng lại chỉ chiếm **`1.41%`** tổng thời gian median của A (`92.80s`). Do đó `H2` bị **bác bỏ** đối với code hiện tại. Khi chuyển sang Phương án C (tổng median giảm còn `7.55s`), Pha `d` (`1.40s`, tương quan tuyến tính chặt với số postings $r = 0.9927$) + Pha `e` (`0.48s`) chiếm `~24.9%` thời gian còn lại (đứng thứ hai sau Pha `c` SQLite scan `4.98s`). |
| **`H3`** | **Đọc metadata / JSON chiếm phần lớn thời gian** | **`CONTRADICTED`** *(trực tiếp ở Pha `f`; chỉ tác động gián tiếp làm phình trang B-tree của `documents` trong `H1`)* | **Pha `f` (`get_many` + `json.loads` cho `4,096` hits)** chỉ tốn warm median **`0.263s` (A), `0.230s` (B), `0.193s` (C)** (`< 0.5%` thời gian của A). Nếu chỉ gọi `get_many` cho **100 unique-case best hits**, thời gian Pha `f` giảm xuống **`0.0020s – 0.0042s` (`2–4 ms`)**! Do đó `H3` bị **bác bỏ** về mặt trực tiếp; kích thước JSON metadata trong bảng `documents` chỉ gây hại gián tiếp khi Phương án A thực hiện `JOIN documents` trên mỗi posting. |
| **`H4`** | **I/O và cache state chi phối** | **`SUPPORTED`** *(Đồng nguyên nhân chính tương tác với `H1` và quyết định phương sai giữa các lượt chạy)* | (1) Máy chủ chỉ có **`3.11 GiB` RAM trống** trên tổng `11.61 GiB`, nhỏ hơn kích thước tệp `lexical.sqlite3` (**`4.06 GiB`**) + Qdrant vectors (**`4.26 GiB`**). (2) Giữ nguyên thuật toán không `JOIN` (B vs C) và bật read-only `mmap_size=4GiB, cache_size=512MiB` giúp giảm thêm một nửa thời gian median warm của `passage` từ **`13.74s` (B) xuống `7.55s` (C)** (`1.82x`) và của `case` từ **`0.456s` xuống `0.176s`** (`2.59x`). (3) Trong các vòng lặp crossover (`Q06`, `Q07`), mỗi khi `Variant A` chạy (`294s–297s`), nó đẩy các trang `postings` ra khỏi OS cache, làm lượt chạy kế tiếp bị chậm lại rõ rệt cho tới khi nạp lại vào cache. |
| **`H5`** | **Chênh lệch Qdrant timeout / cold state làm so sánh sai lệch** | **`SUPPORTED`** | Lượt `first_observed` của Qdrant `exact=True` (`V01 limit=256`) mất **`81.800s`** do phải nạp lại vector từ đĩa sau khi SQLite chiếm page cache — vượt ngưỡng timeout nội bộ 60s mặc định của Qdrant nếu không truyền `?timeout=120`. Khi đã warm, Qdrant `exact=True` chỉ mất **`0.80s – 1.15s` median**. So sánh Qdrant warm (`~1.0s`) với BM25 cold (`118s`) hoặc ngược lại sẽ gây kết luận sai lệch. Khi đặt cả hai trên cùng mặt bằng **warm steady-state**, Qdrant `exact=True` (`~1.01s` + `0.6ms` LRU shard check) nhanh hơn `passage` BM25 cả ở Phương án A (`92.80s`), Phương án B (`13.74s`) lẫn Phương án C (`7.55s`). |

---

## 7. Tương quan với Số lượng Postings vs Số từ Truy vấn & Ước lượng Chi phí Kênh

1. **Đối chiếu độ trễ với tổng số Postings (`sum(df)`) so với số từ khóa (`unique_terms`):**
   - Trên kênh `case` (nằm gọn trong cache), độ trễ warm median có tương quan tuyến tính gần tuyệt đối với tổng số postings ($r = 0.9991 \text{ – } 0.9996$).
   - Trên kênh `passage`, thời gian chấm điểm Python (**Pha `d`**) tương quan tuyến tính chặt với tổng số postings (**$r = 0.9965$ ở A, $r = 0.9952$ ở B, $r = 0.9927$ ở C**). Minh chứng điển hình là cặp **`Q04` (12 từ khóa, `1,387,108` postings)** vs **`Q05` (14 từ khóa, `1,157,969` postings)**: dù `Q04` ít từ khóa hơn `Q05`, `Q04` có nhiều hơn `229,139` postings nên thời gian chấm điểm Pha `d` của `Q04` dài hơn `Q05` ở cả 3 phương án (`1.547s` vs `1.245s` ở C; `1.676s` vs `1.214s` ở B; `0.965s` vs `0.716s` ở A).
2. **Ước lượng chi phí tổng hợp các kênh cục bộ (Analytical Channel Bounds — Chưa phải Latency Hybrid thực tế):**
   - *Lưu ý bắt buộc:* Adapter hybrid `pipeline_v2/full_search/` chưa được triển khai; các con số dưới đây là **dự báo giải tích (sequential sum và parallel max lower-bound)** từ warm median của từng kênh độc lập, **chưa gồm RPC tạo query embedding qua Modal và chưa gồm tranh chấp I/O/RAM khi chạy đồng thời**:
     - **Với Phương án A hiện tại:** Sequential sum $\approx 0.584\text{s (case)} + 92.799\text{s (passage)} + 1.007\text{s (dense 4096)} = \mathbf{94.391\text{s}}$; Parallel lower-bound ($\max$) = **`92.799s`**.
     - **Với Phương án B (Preload + Không JOIN):** Sequential sum $\approx 0.456\text{s} + 13.745\text{s} + 1.007\text{s} = \mathbf{15.208\text{s}}$; Parallel lower-bound ($\max$) = **`13.745s`**.
     - **Với Phương án C (Preload + Không JOIN + Read-only Mmap/Cache):** Sequential sum $\approx 0.176\text{s} + 7.549\text{s} + 1.007\text{s} = \mathbf{8.733\text{s}}$; Parallel lower-bound ($\max$) = **`7.549s`** (trên truy vấn ngắn–trung bình `Q01..Q04`, `passage` BM25 C là **`1.09s – 6.96s`**).

---

## 8. Kết luận: Trả lời 5 Câu hỏi Chốt cho Codex Main

1. **BM25 chậm ở bước nào?**
   - Trong `PersistentBM25.search("passage")` hiện tại (**Phương án A**, warm median **`92.80s`**, range `10.43s – 247.45s`), **`88.3% – 99.3%` thời gian (warm median `90.50s`) nằm ở Pha `c` (`SELECT p.id, p.tf, d.length FROM postings p JOIN documents d ...`)**, do thực hiện `245,083` đến `3,639,697` phép tra cứu B-tree ngẫu nhiên vào bảng `documents` (`667 MB` JSON metadata) với bộ đệm SQLite mặc định chỉ `2 MiB`.
   - Sau khi loại bỏ `JOIN documents` và bật cấu hình cache/mmap read-only (**Phương án C**, warm median giảm còn **`7.55s`**, range `1.09s – 15.93s`), phần thời gian còn lại phân bổ ở: **Pha `c` quét tuần tự `postings` + khởi tạo tuple Python (`4.98s` median, `~66%`)** và **Pha `d` tính điểm BM25 trong Python qua hàng triệu postings của stopwords (`1.40s` median, `~18.5%`)**, tiếp theo là **Pha `e` sort (`0.48s`, `~6.4%`)** và **Pha `f` đọc metadata 4.096 hits (`0.19s`, `~2.6%`)**.

2. **Phần nào do implementation, phần nào chưa đủ evidence?**
   - **Đã chứng minh do implementation hiện tại:**
     1. Phép `JOIN documents` trong vòng lặp từng từ khóa của `PersistentBM25.search` (gây chậm gấp `6.75x`).
     2. Cấu hình SQLite mặc định `cache_size = -2000` (`2 MiB`), `mmap_size = 0` trên tệp `4.06 GiB` (gây chậm thêm `1.82x` trên `passage` và `2.59x` trên `case`).
     3. Gọi `get_many` giải mã JSON metadata cho toàn bộ `4,096` raw hits (`193–263 ms`) thay vì chỉ cho các passage leads được giữ lại của `<= 100` unique cases (`2–4 ms`).
     4. Thiếu tham số `?timeout=120` trên URL truy vấn Qdrant (gây lỗi HTTP 500 ở `60.0s` khi Qdrant đọc đĩa lần đầu mất `81.80s`) và thiếu LRU shard cache khi kiểm tra `ReadonlyCache` (`3.80s – 4.03s` uncached vs `0.5 – 0.65 ms` với LRU cache).
   - **Đã chứng minh do đặc trưng dữ liệu / cấu hình đã khóa + giới hạn RAM máy chủ:**
     - Bộ phân tích từ vựng đã khóa giữ nguyên stopwords (`"the"` có `df = 359,820`, `"of"` có `df = 346,161`). Với câu truy vấn dài (18–47 unique terms, `1.87M – 3.64M` postings), ngay cả khi không `JOIN` và đã warm cache (Phương án C), việc đọc và chấm điểm 2–3,6 triệu dòng trong Python+SQLite vẫn tốn `8.1s – 14.8s`.
     - Máy chủ chỉ có `~3.1 GiB` RAM vật lý trống trong khi `lexical.sqlite3` (`4.06 GiB`) và Qdrant (`4.26 GiB` vectors) cùng hoạt động.
   - **Phần chưa đủ evidence (cần đo sau khi có code S1–S4):**
     - Mức độ tranh chấp bộ nhớ thực tế giữa SQLite `mmap` và `vmmemWSL` (Qdrant) khi chạy chung trong cùng một lệnh `search_corpus`.
     - Phân phối độ dài và số lượng postings của các câu truy vấn thực tế do agent M4 sinh ra.

3. **Tối ưu nào giữ ranking và có lợi sau khi tính startup/RAM?**
   - **Phương án C (kết hợp Phương án B)** giữ **100% thứ tự xếp hạng, điểm số (`max_abs_score_diff = 0.0`) và metadata** trên toàn bộ 8 truy vấn ở cả hai kênh `case` và `passage`.
   - **Chi phí Startup & RAM thực tế đã đo:** Nạp bảng `id -> length` và `id -> sys.intern(case_id)` lúc mở session chỉ mất **`2.927 giây`** và **`50.251 MiB` Python heap (`+65.508 MiB` OS Private RAM)** (hoặc **`44.957 MiB` Python heap** nếu dùng tiền tố `passage_id[:6] + ".txt"` đã được chứng minh đúng 100% trên 415.693 đoạn văn).
   - **Điểm hòa vốn (Break-even):** Vì Phương án C tiết kiệm từ **`6.31 giây` đến `235.74 giây` trên mỗi câu truy vấn warm** (median tiết kiệm **`81.99 giây/câu`**), chi phí preload `2.927s` **hoàn vốn ngay trong câu truy vấn ĐẦU TIÊN (`breakeven = 0.012 .. 0.464 queries`, median `0.036 queries`)**.

4. **Có cần thay thiết kế full search hay chỉ tối ưu reader?**
   - **Chỉ cần tối ưu ở tầng Reader trong module mới `pipeline_v2/full_search/`, KHÔNG cần thay đổi thiết kế kiến trúc M3 Full Search và KHÔNG cần xây lại `lexical.sqlite3` hay collection Qdrant:**
     1. Khi mở session chỉ đọc, nạp `passage_lengths` (`44.96 MiB` heap, dùng tiền tố `id[:6] + ".txt"` hoặc `sys.intern(case_id)` `50.25 MiB`) và bỏ hẳn `JOIN documents` khỏi vòng lặp tính điểm BM25.
     2. Bật read-only `PRAGMA cache_size` / `mmap_size` có trần hợp lý (ví dụ `mmap_size = 1 GiB – 2 GiB`, `cache_size = -262144` [`256 MiB`], `temp_store = MEMORY`) để tăng tốc quét `postings` mà không ép `vmmemWSL` (Qdrant) bị swap trên máy có `3.1 GiB` RAM trống.
     3. Chạy BM25 đúng 1 lượt (single pass) cho mỗi truy vấn, duyệt danh sách điểm đã sắp xếp tới `scan_cap = 4096` để lấy `<= 100` unique cases và chỉ gọi `get_many` cho các passage leads được giữ lại (`2–4 ms`).
     4. Truyền `?timeout=120` vào Qdrant `/points/query`, gọi `exact=True` ở `limit=4096` (hoặc 2 bước `256 -> 4096` vì `V03` thực tế chỉ có `97` unique cases ở `256`), và dùng LRU shard cache khi đối soát các passage leads được giữ lại trên `ReadonlyCache`.

5. **Phép đo tiếp theo nào còn cần, nếu chưa phân xử được?**
   - Mọi giả thuyết `H1..H5` về nguyên nhân độ trễ BM25 và Qdrant đơn kênh đã được phân xử dứt điểm bằng số đo thực nghiệm.
   - Phép đo duy nhất còn cần ở **mốc S4 (sau khi triển khai `full_search` session)** là chạy chuỗi truy vấn kết hợp tuần tự `case_bm25 + passage_bm25 (Variant C) + dense_passage (Qdrant exact=True + LRU shard check)` trong cùng một tiến trình để kiểm tra xem mức `PRAGMA mmap_size` (`512 MiB` vs `1 GiB` vs `2 GiB`) nào giữ được cả `postings` của SQLite lẫn vectors của Qdrant (`vmmemWSL`) ổn định trong `~3.1 GiB` RAM vật lý khả dụng mà không gây hiện tượng đẩy trang chéo (cross-eviction).

---

## 9. Danh mục Toàn bộ Bàn giao trong `pipeline_v2/reviews/m3_search_latency_diagnostic_v1/`

- [`REPORT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/REPORT.md): Báo cáo tổng hợp và kết luận phân xử.
- [`workload_manifest.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/workload_manifest.json): Manifest khóa 8 câu truy vấn (`Q01..Q08` kèm `span_bytes`, `source_hash`, `df`, tổng postings) và 3 vector chẩn đoán (`V01..V03`).
- [`commands_and_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/commands_and_results.json): Nhật ký toàn bộ lệnh thực thi, exit codes, thời gian và lịch sử các lần thử (bao gồm cả audit `probe_deep_dive.py` lỗi trước đó và `CMD-02-ATTEMPT-1`).
- [`measurements.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/measurements.json) & [`measurements_summary.csv`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/measurements_summary.csv): Toàn bộ số đo chi tiết từng lượt chạy (192 lượt BM25 + 24 lượt Qdrant + kiểm tra shard + preload RAM) và bảng tổng hợp CSV.
- [`correctness_comparison.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/correctness_comparison.json): Kết quả đối soát độ chính xác giữa `IndependentBM25Oracle`, `PersistentBM25.search` nguyên bản, và 3 phương án `A`, `B`, `C` (`max_abs_score_diff = 0.0`).
- [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/findings.json): Kết quả phân xử cấu trúc cho `H1..H5` và trả lời 5 câu hỏi kết luận.
- Các tệp dữ liệu thành phần & scripts:
  - [`prior_evidence_audit.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/prior_evidence_audit.json), [`environment_snapshot.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/environment_snapshot.json), [`sqlite_and_preload_diagnostics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/sqlite_and_preload_diagnostics.json), [`dense_measurements.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/dense_measurements.json), [`bm25_measurements.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/bm25_measurements.json).
  - [`scripts/01_inspect_env_and_lock_workload.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/scripts/01_inspect_env_and_lock_workload.py)
  - [`scripts/02_inspect_sqlite_and_preload_ram.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/scripts/02_inspect_sqlite_and_preload_ram.py)
  - [`scripts/03_benchmark_dense_local.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/scripts/03_benchmark_dense_local.py)
  - [`scripts/04_benchmark_bm25_controlled.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/scripts/04_benchmark_bm25_controlled.py)
  - [`scripts/05_analyze_and_generate_artifacts.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_search_latency_diagnostic_v1/scripts/05_analyze_and_generate_artifacts.py)
