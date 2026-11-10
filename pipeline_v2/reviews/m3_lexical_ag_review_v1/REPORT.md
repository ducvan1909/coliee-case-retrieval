# Báo cáo Kiểm thử & Nghiệm thu Độc lập Reader BM25 Tối ưu (`m3_lexical`)

- **Ngày thực hiện:** `2026-11-09`
- **Phạm vi thực hiện:** Theo [`pipeline_v2/docs/AG_REVIEW_M3_LEXICAL_PROMPT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/AG_REVIEW_M3_LEXICAL_PROMPT.md)
- **Thư mục bằng chứng độc lập:** [`pipeline_v2/reviews/m3_lexical_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1)
- **Code freeze SHA-256 đã xác minh:** `3633aa881ef8ff7f739a87c5c174b00faff82f59f656466a70d3804f7c0856bf`
- **Tuân thủ ràng buộc:** Không sửa bất kỳ tệp production/config/seal/index nào; giữ nguyên `m3_full_train_20261108_v1` và các bản pilot; SQLite mở `mode=ro` (`PRAGMA query_only=1`); `0` lệnh gọi Modal/Qdrant/deploy; không truy cập `.env`, gold hay labels.

---

## 1. Kết luận Tổng thể theo Từng Hạng mục (Separated Verdicts)

| Hạng mục | Kết luận | Tóm tắt bằng chứng |
|---|---|---|
| **`correctness`** | **`PASS`** | `32/32` unit tests hiện có (`14` test reader + `18` V2 regressions) + `8/8` bộ kiểm thử độc lập mới của AG ([`test_m3_lexical_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/test_m3_lexical_independent_ag.py), gồm `15` phép tiêm lỗi trên bản sao tạm) đều `PASS` (`0` lỗi). Công thức BM25 `float64`, bộ phân tích Unicode không bỏ stopwords, loại trừ `exclude_case` trước khi cắt `limit`, `fetchmany(4096)` không `JOIN`/`fetchall`, tích lũy chỉ số NumPy, cắt top-K giữ toàn bộ đồng hạng biên (`_top`), chế độ `--unique-cases`, đối soát cột bất biến trong `get_many` và cơ chế `guard()`/`revalidate()` đều chính xác. |
| **`actual_full_workload_parity`** | **`PASS`** | Khớp **100% danh sách ID xếp hạng** và **sai số tuyệt đối điểm số `float64` tối đa bằng `0.0` (`0 ULP`)** trên toàn bộ `16/16` phép thử (`8` câu truy vấn đã khóa `Q01..Q08` × `2` kênh `case` & `passage`, quét từ `20,184` đến `3,639,697` postings và tới `406,600` đoạn văn khớp/câu) ở cả hai chế độ: **`limit=4096, unique_cases=False`** (trong [`actual_benchmark.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_validation_v1/actual_benchmark.json) và đo lặp của AG) và **`limit=100, unique_cases=True`** (trong [`bounded_benchmark_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/bounded_benchmark_results.json) so với oracle `rank_cases` toàn kênh). |
| **`performance_cold_warm_and_resource_limits`** | **`PASS_MEASURED_WITH_DOCUMENTED_IO_AND_RESOURCE_LIMITS`** | Phân rã từng pha trên cùng trạng thái cache ấm chứng minh: (1) **Tích lũy điểm NumPy + chọn Top-K (`_top`) nhanh hơn `2.35x` median trên `passage` (`0.678s` vs `1.586s`) và `1.55x` trên `case`** so với Python scalar (riêng bước chọn top-4096 bằng `np.partition` nhanh hơn `43.7x – 61.5x`: `9.1 ms` vs `454 ms`); (2) Chế độ `--unique-cases --limit 100` giảm thời gian đọc metadata `get_many` trên `passage` từ median **`722.6 ms` (tối đa `1,468 ms` ở `4,096` hits) xuống còn `4.68 ms` (nhanh hơn `154x` median, tối đa `306x`)**; (3) Trong [`actual_benchmark.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_validation_v1/actual_benchmark.json), việc `vectorized` có median lượt đầu cao hơn `scalar` (`18.08s` vs `15.27s`) là do **bất đối xứng thứ tự ngẫu nhiên (`vectorized` chạy đầu/cold ở `5/8` câu, `scalar` chạy đầu ở `3/8` câu)** cộng với chi phí đọc `4,096` hàng metadata và `2 × guard()` (`~87 ms`); (4) Với `cache_mib=128, mmap_mib=512` trên tệp SQLite `4,058 MiB`, I/O đọc `postings` (`postings_fetch_seconds`) vẫn chiếm **`83% – 92%`** thời gian truy vấn `passage` (`8.23s` median warm). |
| **`full_search_readiness`** | **`READY_AS_LEXICAL_COMPONENT_PENDING_HYBRID_FULL_SEARCH`** | [`FastBM25`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L40-L208) và [`LexicalSession`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L210-L279) sẵn sàng làm thành phần đọc lexical cho M3 full search (`0` bug chặn). Các phần dense Qdrant adapter, phrase/identity channels, RRF fusion, context delivery và đánh giá chất lượng pháp lý COLIEE F1 chưa thuộc phạm vi reader này và không được suy diễn từ độ tương đương xếp hạng BM25. |

---

## 2. Kiểm toán Fingerprints & Tính Bất biến của Snapshot ([`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/recomputed_metrics.json))

- **Code Freeze & Cấu hình Reader mới:**
  - `lexical_implementation_aggregate_sha256`: `3633aa881ef8ff7f739a87c5c174b00faff82f59f656466a70d3804f7c0856bf`
    - [`pipeline_v2/full_search/__init__.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/__init__.py): `c805c7afaef4635cec147ca3a97b7ebe3e56805ee0a1aa3d275ff47039101a44`
    - [`pipeline_v2/full_search/lexical.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py): `a706cd707a5ea1900594454be22e4c1a996e3abc27ac7a618057afc52e2b4b0f`
    - [`pipeline_v2/m3_lexical.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/m3_lexical.py): `78f9b2a8de1bb825a32052b102e0754bf600bf1dbcfb330dbba2e930af8b966f`
  - [`pipeline_v2/configs/m3_lexical.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/configs/m3_lexical.json): `a126092312afa6e6c82b01d3e8b43b13c0dbf34399cc4619f1ccd80a2bcab812` (`cache_mib=128`, `mmap_mib=512`, `fetch_size=4096`, `max_limit=16384`).
- **Tính Bất biến của Full Run, Pilot và Code Upstream:**
  - `full_implementation_aggregate_sha256`: `e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503` (khớp tuyệt đối `34/34` file trong [`prior_state.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_validation_v1/prior_state.json)).
  - `m3_full_train_20261108_v1`: `manifest.json` (`7bdf2bb5dda4b324147f5332f4c4a0ed95b15a953b2d3c40fe9f184ca74d45b0`), `seal.json` (`b6fe2a3b0d2677362c7da29f406ca2deb009b18c23a2782fed4cae7bd38de8ec`) và `lexical.sqlite3` (`4,357,505,024` bytes, SHA-256 `6ad1f818618bd6d4d66e0b89c3b06a5bc033da4ac19c86030859fdf9b8bc03fa`) được xác thực nguyên vẹn qua `m3_lexical revalidate`.
  - `m3_opt_v2_index_20261108_v1`: `3/3` file trong `seal.json` khớp tuyệt đối kích thước và SHA-256.

---

## 3. Kiểm chứng Độc lập Tính Đúng đắn, Thuật toán & Bảo vệ Snapshot

Bộ kiểm thử độc lập [`test_m3_lexical_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/test_m3_lexical_independent_ag.py) (`8/8 PASS` trong `0.782s`, chi tiết tại [`independent_test_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/independent_test_results.json)) kết hợp với `32/32` unit tests hiện có xác nhận:

1. **Công thức BM25 `float64`, Analyzer, Stopwords, Unicode, Negation, OOV (`test_01`):**
   - [`FastBM25.search_detailed()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L127-L201) gọi đúng [`retrieval.bm25.analyze`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/retrieval/bm25.py#L7-L8) (`re.findall(r"\w+", text.casefold(), flags=re.UNICODE)`), duyệt `sorted(set(analyze(query)))`, không loại bỏ stopwords (`"the"`, `"of"`, `"not"`, `"a"`, `"1"`), tiền tính mảng `norm = k1 * (1 - b + b * array / (avg or 1))` bằng `np.float64` và tích lũy điểm vào `np.zeros(channel['n'], dtype=np.float64)`.
   - Đối chứng với oracle `float64` độc lập và [`PersistentBM25`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization_v2/index.py#L22-L89) cho độ lệch `<= 1e-15` (`0.0` trên toàn bộ 16 truy vấn thật), trong khi oracle `float32` lệch `> 6e-9` đến `1e-6`, chứng minh không có ép kiểu `float32` ngầm.
   - Truy vấn rỗng (`""`, `"   "`), chỉ có dấu câu (`"--- ... () [] !@#"`), hoặc từ khóa OOV trả về `[]` với `terms_matched=0, postings_rows=0, matched_documents=0`.
2. **Không `JOIN documents` trong vòng lặp từ khóa & `fetchmany` có giới hạn (`test_02`):**
   - `SQLSpyConnection` chặn mọi câu lệnh SQL trong `search_detailed`: xác nhận **không có từ khóa `JOIN`** trong bất kỳ câu lệnh SQL nào và **`fetchall()` không bao giờ được gọi** trên con trỏ `postings`.
   - Với `fetch_size=64` trên 3 từ khóa có `df = 150, 128, 5`, chuỗi gọi `cursor.fetchmany(64)` diễn ra đúng trình tự `[(64, 64), (64, 64), (64, 22), (64, 0), (64, 64), (64, 64), (64, 0), (64, 5), (64, 0)]` (`postings_rows = 283`).
3. **Tính đúng đắn của phép cộng chỉ số NumPy (`scores[indices] += ...`) và Reset mỗi truy vấn (`test_02`, `test_03`):**
   - Vì bảng `postings` có khóa chính `PRIMARY KEY(kind, term, id)` và `channel['ordinals']` là song ánh `0..n-1` theo thứ tự `ORDER BY id`, mọi phần tử trong `indices` của mỗi lô `fetchmany` cho một `(kind, term)` đều đôi một phân biệt. Do đó phép gán cộng `scores[indices] += ...` tại [dòng 172](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L172) hoàn toàn không gặp lỗi trùng chỉ số (duplicate-index hazard) của NumPy, tích lũy chính xác qua nhiều lô và nhiều từ khóa, đồng thời mảng `scores` được cấp phát mới ở mỗi lần gọi.
4. **Phân hoạch Top-K (`FastBM25._top`) giữ đủ đồng hạng biên & Tie-break theo ID (`test_03`):**
   - Trong [`FastBM25._top(scores, limit)`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L117-L125), `positive = np.flatnonzero(scores > 0)` trả về các chỉ số theo thứ tự tăng dần tuyệt đối, trùng với thứ tự từ điển tăng dần của `id` (`ORDER BY id` khi nạp).
   - Khi `len(positive) > limit`, `threshold` là điểm lớn thứ `limit`. Tập `above = positive[scores[positive] > threshold]` có `< limit` phần tử, và tập đồng hạng biên `equal = positive[scores[positive] == threshold]` giữ nguyên thứ tự chỉ số tăng dần, nên phép cắt `equal[:limit - len(above)]` lấy chính xác `limit - len(above)` tài liệu đồng hạng có `id` nhỏ nhất trước khi sắp xếp cuối cùng bằng `np.lexsort((positive, -scores[positive]))`. Kiểm thử trên 9 tài liệu đồng hạng biên với thứ tự chèn xáo trộn ở mọi ngưỡng `limit = 1..19` khớp 100% với oracle.
5. **Chế độ `--unique-cases` (`unique_cases=True`) chọn best hit toàn kênh trước khi cắt `limit` (`test_04`):**
   - Khi `unique_cases=True` ([dòng 178–187](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L178-L187)), reader lấy toàn bộ tài liệu có điểm dương đã sắp xếp (`self._top(scores, max(1, channel['n']))`), duyệt từ hạng cao nhất và giữ lại đoạn văn đầu tiên (điểm cao nhất, tie-break theo `id`) của mỗi `case_id` cho tới khi đủ `limit` án.
   - Kiểm thử xác nhận: khi Án 1 có 40 đoạn văn và Án 2 có 30 đoạn văn chiếm trọn 70 hạng đầu, truy vấn `unique_cases=True, limit=4` vẫn tìm đúng đoạn văn của Án 4 nằm ở hạng raw 72, giữ nguyên điểm BM25 của đoạn văn tốt nhất của từng án (không cộng dồn điểm các đoạn văn cùng án) và không làm thay đổi ngữ nghĩa khi `unique_cases=False`.
6. **Đọc Metadata theo lô `256` IDs, đối soát cột bất biến và Tiêm lỗi (`test_05`, `test_06`, `test_07`):**
   - [`FastBM25.get_many()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L98-L114) chỉ truy vấn `SELECT id,metadata FROM documents WHERE kind=? AND id IN (...)` cho các ID đã chọn sau khi cắt `limit`, chia theo lô tối đa `256` IDs (`600` hits $\rightarrow$ `3` câu lệnh SQL với `[256, 256, 88]` tham số; `unique_cases=True, limit=5` $\rightarrow$ `1` câu lệnh với `[5]` tham số).
   - `15/15` phép tiêm lỗi trên bản sao SQLite tạm thời xác nhận reader bắt chính xác mọi sai lệch: thiếu kênh trong `stats`, thông số `k1/b/avg/n` bất hợp lệ, `n != len(ids)`, `avg != mean(lengths)`, `case_id` sai định dạng `[0-9]{6}\.txt`, `length < 0`, `df` vượt `n`, `COUNT(postings) != df`, posting trỏ tới `id` ngoài bảng `documents`, `tf <= 0`, metadata chứa `"text"`, hoặc `passage_id`/`case_id` trong JSON lệch với cột bất biến.
   - Khi [`FastBM25.__init__()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L94-L96) hoặc [`LexicalSession.__init__()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L221-L225) gặp lỗi giữa chừng, kết nối `sqlite3.Connection` luôn được `.close()` sạch sẽ trong khối `except BaseException:`.
   - Kiểm thử hợp đồng đột biến SQLite trực tiếp (`test_07`): khi tệp `lexical.sqlite3` trên bản sao tạm bị sửa byte trực tiếp (`PRAGMA user_version=999`) mà không đổi `manifest.json`/`seal.json`, hàm `guard()` nhẹ trong mỗi truy vấn không hash lại tệp SQLite nhiều GB (đúng như tài liệu [`M3_LEXICAL.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/M3_LEXICAL.md) đã công bố), nhưng gọi `session.revalidate()` lập tức phát hiện lệch SHA-256 của `lexical.sqlite3`, ném `M3Error` và khóa vĩnh viễn phiên (`session.invalidated = True`).

---

## 4. Kiểm toán Startup, PRAGMAs, RAM Thực tế và CLI Độc lập ([`bounded_benchmark_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/bounded_benchmark_results.json))

### 4.1. PRAGMAs Thực nhận và Phân rã Bộ nhớ (`tracemalloc` Heap vs Windows OS WorkingSet / PrivateUsage)

Phép đo thực hiện trong hai tiến trình con hoàn toàn tách biệt (Pass 1 bật `tracemalloc` để đo cấp phát Python heap; Pass 2 tắt `tracemalloc` và gọi Windows API `GetProcessMemoryInfo` để đo `WorkingSetSize` và `PrivateUsage` thực tế của tiến trình) với cấu hình mặc định `cache_mib=128, mmap_mib=512, fetch_size=4096`:

| Giai đoạn / Cấu trúc trong Tiến trình Reader | Thời gian (`s`) | Python Heap (`tracemalloc` Current / Peak) | OS `WorkingSetSize` (Resident RAM) | OS `PrivateUsage` (Commit Charge) | Số Page Faults Tích lũy | Giải thích kỹ thuật |
|---|---:|---:|---:|---:|---:|---|
| **Trước khi mở `FastBM25`** | — | `0.000 MiB` | `39.727 MiB` | `414.289 MiB` | `10,331` | Nền Python + NumPy runtime. |
| **Sau `FastBM25.__init__` (Preload `7,708` cases + `415,693` passages)** | **`2.551s`** (warm OS cache) / `34.98s–39.53s` (cold) | **`65.067 MiB`** (`68,227,601` B) / Peak `78.832 MiB` | **`267.320 MiB`** (`+227.593 MiB`) | **`640.055 MiB`** (`+225.766 MiB`) | `99,919` | Gồm `65.07 MiB` cấu trúc Python/NumPy (`cases` `int32` = `1.61 MiB`, `norm` `float64` = `3.23 MiB`, lists `ids` + dicts `ordinals`/`case_codes` = `~60.2 MiB`) + **`~128 MiB` SQLite page cache** nạp khi quét bảng `documents` + bộ cấp phát. |
| **Sau `Q01` kênh `case` (`limit=4096`)** | `0.162s` (warm) | — | **`338.844 MiB`** (`+71.524 MiB`) | **`643.059 MiB`** (`+3.004 MiB`) | `118,233` | Các trang `postings` trong vùng `512 MiB` đầu tệp được ánh xạ vào `WorkingSet` qua `mmap` mà hầu như không tăng `PrivateUsage`. |
| **Sau `Q01` kênh `passage` (`limit=4096, unique_cases=False`)** | `1.810s` (warm) | Peak **`96.702 MiB`** | **`366.668 MiB`** (`+27.824 MiB`) | **`667.328 MiB`** (`+24.269 MiB`) | `127,970` | Cấp phát tạm thời mảng điểm `float64` (`3.17 MiB`), các lô `fetchmany(4096)` và `4,096` dict metadata JSON. |
| **Sau `Q01` kênh `passage` (`limit=100, unique_cases=True`)** | `1.661s` (warm) | — | **`367.809 MiB`** (Peak `375.105 MiB`) | **`668.023 MiB`** (`+0.695 MiB`) | `130,852` | Trạng thái bộ nhớ ổn định, không rò rỉ qua các truy vấn liên tiếp. |

- **Xác nhận PRAGMAs thực nhận từ SQLite (`3.42.0`):** `query_only = 1`, `cache_size = -131072` (`128 MiB`), `mmap_size = 536870912` (`512 MiB`), `page_size = 4096`, `page_count = 1,063,844` (`4,357,505,024` bytes), `freelist_count = 0`.
- **Chứng minh thực nghiệm `cache_mib=128 / mmap_mib=512` không phải hard RAM cap và `mmap_size` không phải Resident RAM:**
  1. `mmap_size = 512 MiB` chỉ đặt trần vùng địa chỉ ảo được ánh xạ cho 512 MiB đầu tiên của tệp `4.06 GiB`; ngay sau khi mở và preload, `WorkingSetSize` của tiến trình chỉ là **`267.32 MiB`** (chưa tới một nửa của `512 + 128 = 640 MiB`), vì các trang `mmap` chỉ chiếm RAM vật lý khi được chạm tới và vẫn có thể bị hệ điều hành thu hồi.
  2. Ngược lại, `PrivateUsage` tăng **`+225.77 MiB`** sau khi preload (và **`+253.73 MiB`** sau truy vấn `passage`), vượt mức `cache_mib = 128 MiB` vì ngoài bộ đệm trang của SQLite, tiến trình còn giữ **`65.07 MiB` Python heap** cho bảng ánh xạ `ids`/`ordinals`/`cases`/`norm` cùng các mảng làm việc tạm thời.

### 4.2. Tách biệt Chi phí Startup / Revalidate và Kiểm tra Standalone CLI Không cần `.env`/Modal

Đã chạy trực tiếp CLI [`pipeline_v2/m3_lexical.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/m3_lexical.py) trong môi trường đã xóa toàn bộ biến `MODAL_*` và `QDRANT_*`:
- **Lệnh `m3_lexical revalidate`:** `returncode = 0`, `subprocess_wall_seconds = 96.000s`, `internal_cli_seconds = 95.764s`, trả về `{"model_requests": 0, "status": "immutable_snapshot_revalidated"}`.
- **Lệnh `m3_lexical search --channel passage --query "standard of review" --query-case 000002.txt --limit 100 --unique-cases`:**
  - `returncode = 0`, `subprocess_wall_seconds = 114.719s`, `internal_cli_seconds = 114.511s`.
  - Tách biệt rõ:
    - `session_initialization_seconds = 62.764s` (trong đó kiểm tra seal SHA-256 của `4.36 GB` SQLite + `7,708` raw cases mất `27.779s`, và `preload_seconds` nạp bảng `documents` mất `34.985s`).
    - `timings.total_seconds = 51.191s` (`postings_fetch_seconds = 50.912s` cold, `mapping_and_scoring_seconds = 0.208s`, `top_selection_seconds = 0.041s`, `metadata_seconds = 0.027s`).
  - Trả về đúng `100` đoạn văn thuộc `100` án phân biệt (`"000002.txt"` bị loại trừ hoàn toàn), dẫn đầu là `031313:96cbfd326f4e974ad73ef2e6` (`score = 11.123129`).

---

## 5. Phân tích Benchmark 8 Truy vấn của Main (`actual_benchmark.json`) và Phân rã Từng Pha của AG

### 5.1. Giải thích Nguyên nhân Chênh lệch Median Lượt đầu trong `actual_benchmark.json`

Khi tính toán lại độc lập [`actual_benchmark.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_validation_v1/actual_benchmark.json) (lưu tại [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/recomputed_metrics.json#L32-L126)), toàn bộ các con số tổng hợp trong [`M3_LEXICAL.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/M3_LEXICAL.md) đều khớp chính xác tuyệt đối (`case`: scalar `0.431s`, reader mới `1.231s`, repeat `0.255s`; `passage`: scalar `15.275s`, reader mới `18.079s`, repeat `13.114s`).

Phân tích tách nhóm theo thứ tự thực thi (`execution_order`) trong [`benchmark_actual.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_validation_v1/benchmark_actual.py#L56) chỉ ra nguyên nhân trực tiếp khiến median lượt đầu của `vectorized` cao hơn `scalar`:

| Kênh | Nhóm câu truy vấn theo `execution_order` (`seed = 20261109 + ordinal`) | Số câu | Median Lượt 1 (Cold trên từ khóa mới) | Median Lượt 2 (Warm ngay sau Lượt 1) | Median Lượt 3 (`vectorized_repeat`) | Nhận xét đối chứng |
|---|---|---:|---:|---:|---:|---|
| **`case`** | **`vectorized` chạy trước (`Q01, Q04, Q05, Q06, Q08`)** | **5 / 8** | **`1.947s`** (`vectorized`) | **`0.174s`** (`scalar`) | **`0.280s`** (`vectorized`) | `vectorized` gánh chi phí đọc đĩa lần đầu ở `5/8` câu; `scalar` chạy thứ hai hưởng trọn OS page cache vừa nạp! |
| | **`scalar` chạy trước (`Q02, Q03, Q07`)** | **3 / 8** | **`2.253s`** (`scalar`) | **`0.231s`** (`vectorized`) | **`0.197s`** (`vectorized`) | Ở cả 3 câu mà `scalar` chạy trước, `vectorized` chạy sau **nhanh hơn gấp `9.75x` (`0.231s` vs `2.253s`)**! |
| | **Gộp theo vị trí (Bất kể phương pháp nào)** | 8 | **`2.100s`** (Vị trí 1) | **`0.206s`** (Vị trí 2) | **`0.255s`** (Vị trí 3) | Hiệu ứng vị trí 1 (cold) vs vị trí 2 (warm) chênh nhau **`10.2x`**, áp đảo hoàn toàn chênh lệch thuật toán. |
| **`passage`** | **`vectorized` chạy trước (`Q01, Q04, Q05, Q06, Q08`)** | **5 / 8** | **`19.927s`** (`vectorized`) | **`12.068s`** (`scalar`) | **`11.182s`** (`vectorized`) | Khi `vectorized` chạy đầu, nó tốn `19.93s` nạp trang; `scalar` chạy thứ hai giảm còn `12.07s`, và `vectorized_repeat` giảm tiếp còn **`11.18s` (nhanh hơn `scalar`)**. |
| | **`scalar` chạy trước (`Q02, Q03, Q07`)** | **3 / 8** | **`21.706s`** (`scalar`) | **`16.232s`** (`vectorized`) | **`15.047s`** (`vectorized`) | Khi `scalar` chạy đầu (`21.71s`), `vectorized` chạy thứ hai nhanh hơn (`16.23s`) và `vectorized_repeat` nhanh hơn nữa (`15.05s`). |
| | **Gộp theo vị trí (Bất kể phương pháp nào)** | 8 | **`20.817s`** (Vị trí 1) | **`14.150s`** (Vị trí 2) | **`13.114s`** (Vị trí 3) | Ngoài bất đối xứng `5/8` vs `3/8`, trong `benchmark_actual.py` hai kết nối SQLite riêng biệt còn giữ hai bộ đệm `128 MiB` độc lập và `vectorized` phải đọc thêm `4,096` hàng metadata từ bảng `documents` (`667 MiB`). |

### 5.2. Phân rã Từng Pha trên Cùng Trạng thái Cache Ấm (`bounded_benchmark_results.json`)

Để định lượng chính xác lợi ích tốc độ thực sự của NumPy và của chế độ `--unique-cases --limit 100` khi đặt trên cùng một mặt bằng công việc và cùng một kết nối SQLite đã làm ấm postings cho từng câu truy vấn (`4/8` câu chạy `vectorized` trước, `4/8` câu chạy `scalar` trước theo [`bounded_benchmark_manifest.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/bounded_benchmark_manifest.json)), bảng dưới đây tổng hợp số đo phân rã của 8 truy vấn (`Q01..Q08`):

#### Bảng A: Phân rã Thời gian Kênh `passage` trên 8 Truy vấn (`Q01..Q08`, Warm Steady-State)

| Query (`Terms` / `Postings` / `Matched Docs`) | Tổng `Vec 4096` Outer (`s`) | Tổng `Vec 4096` Không Guard & Meta (`s`) | Tổng `Scalar 4096` (`s`) | Tổng `Vec Unique-100` Outer (`s`) | Pha Fetch Postings (`Vec` / `Scal`) (`s`) | **Pha Chấm điểm (`NumPy` vs `Python`) (`s`) [Speedup]** | **Pha Chọn Top-4096 (`np.partition` vs `sorted`) (`s`) [Speedup]** | **Gộp Score + Top (`NumPy` vs `Python`) [Speedup]** | **Pha Metadata (`4096` raw vs `100` unique) (`s`) [Speedup]** | Overhead `2 × guard()` (`s`) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **`Q01`** (`4` / `245k` / `181.7k`) | 1.810 | **1.559** | 1.951 | **1.661** | 1.419 / 1.491 | **0.136s vs 0.241s** [`1.77x`] | **0.0042s vs 0.218s** [`52.1x`] | **0.140s vs 0.459s [`3.28x`]** | **0.165s vs 0.0049s** [`34.0x`] | 0.084s |
| **`Q02`** (`6` / `480k` / `365.6k`) | 4.482 | **2.924** | 3.455 | **3.061** | 2.642 / 2.568 | **0.273s vs 0.440s** [`1.61x`] | **0.0091s vs 0.445s** [`48.9x`] | **0.282s vs 0.885s [`3.14x`]** | **1.468s vs 0.0050s** [`292.0x`] | 0.088s |
| **`Q03`** (`8` / `863k` / `374.7k`) | 5.081 | **4.794** | 15.827 | **5.071** | 4.355 / 14.633 | **0.430s vs 0.743s** [`1.73x`] | **0.0085s vs 0.449s** [`53.1x`] | **0.439s vs 1.192s [`2.72x`]** | **0.209s vs 0.0044s** [`48.0x`] | 0.076s |
| **`Q04`** (`12` / `1.39M` / `394.7k`) | 17.796 | **16.366** | 26.894 | 43.891* | 15.642 / 25.237 | **0.714s vs 1.155s** [`1.62x`] | **0.0095s vs 0.500s** [`52.4x`] | **0.724s vs 1.654s [`2.29x`]** | **1.309s vs 0.0721s** [`18.2x`] | 0.117s |
| **`Q05`** (`14` / `1.16M` / `372.4k`) | 7.334 | **7.033** | 8.128 | **7.041** | 6.400 / 6.598 | **0.623s vs 1.094s** [`1.76x`] | **0.0094s vs 0.433s** [`46.0x`] | **0.633s vs 1.527s [`2.41x`]** | **0.207s vs 0.0085s** [`24.4x`] | 0.090s |
| **`Q06`** (`18` / `1.87M` / `379.9k`) | 12.498 | **11.048** | 11.960 | **11.587** | 10.060 / 9.913 | **0.980s vs 1.584s** [`1.62x`] | **0.0075s vs 0.459s** [`61.5x`] | **0.988s vs 2.043s [`2.07x`]** | **1.366s vs 0.0045s** [`306.0x`] | 0.079s |
| **`Q07`** (`35` / `2.34M` / `400.3k`) | 15.156 | **14.797** | 15.657 | **15.295** | 13.506 / 13.167 | **1.280s vs 2.006s** [`1.57x`] | **0.0109s vs 0.477s** [`43.7x`] | **1.291s vs 2.484s [`1.92x`]** | **0.265s vs 0.0045s** [`59.0x`] | 0.086s |
| **`Q08`** (`47` / `3.64M` / `406.6k`) | 23.999 | **22.720** | 23.683 | **22.870** | 20.671 / 20.065 | **2.040s vs 3.102s** [`1.52x`] | **0.0090s vs 0.509s** [`56.4x`] | **2.049s vs 3.610s [`1.76x`]** | **1.180s vs 0.0043s** [`276.7x`] | 0.089s |
| **Median qua 8 Queries** | **9.916s** | **9.041s** | **13.809s** | **9.314s** | **8.230s / 11.540s** | **0.669s vs 1.125s [`1.62x`]** | **0.0091s vs 0.454s [`52.2x`]** | **0.678s vs 1.586s [`2.35x`]** | **0.723s vs 0.0047s [`154.5x`]** | **0.087s** |

*\*Ghi chú tại `Q04` (`Vec Unique-100`): Sau khi `Vec 4096` đọc ngẫu nhiên `1.309s` bảng `documents` để lấy 4,096 metadata, một phần trang `postings` của `Q04` bị đẩy khỏi OS standby cache nên lượt `Vec Unique-100` kế tiếp mất `42.92s` ở `postings_fetch_seconds`, trong khi bản thân bước `mapping_and_scoring` vẫn giữ nguyên `0.726s`, `top_selection` là `0.050s` và `metadata_seconds` chỉ mất `0.072s`.*

#### Bảng B: Phân rã Thời gian Kênh `case` trên 8 Truy vấn (`Q01..Q08`, Warm Steady-State)

| Chỉ số (Median qua 8 Queries `Q01..Q08`) | `Vec 4096` Outer | `Vec 4096` Không Guard & Meta | `Scalar 4096` | `Vec Unique-100` Outer | Ghi chú kỹ thuật |
|---|---:|---:|---:|---:|---|
| **Tổng thời gian (`s`)** | `0.2323s` | **`0.1269s`** | `0.1374s` | `0.1996s` | Khi đặt cùng ranh giới công việc (không tính `guard` và `metadata`), `FastBM25` nhanh hơn `scalar` (`0.127s` vs `0.137s`). |
| **`postings_fetch_seconds` (`s`)** | `0.1001s` | `0.1001s` | `0.0977s` | `0.0962s` | Cả hai phương pháp tốn thời gian đọc SQLite tương đương (`~100 ms`). |
| **Chấm điểm (`mapping_and_scoring` vs `python_scoring`)** | **`0.0262s`** | **`0.0262s`** | `0.0338s` | **`0.0249s`** | NumPy nhanh hơn `1.14x – 1.77x` (trên `Q08`: `93.4 ms` vs `164.8 ms`). |
| **Chọn Top (`top_selection` vs `sort`)** | **`0.00049s`** | **`0.00049s`** | `0.00447s` | `0.00067s` | `np.partition` nhanh hơn `sorted` **`9.1x` median** (`4.96x – 23.81x`). |
| **Đọc Metadata (`get_many`)** | `0.0293s` (`4,096` hits) | — | — | **`0.00085s`** (`100` hits) | Lấy top 100 cases chỉ tốn **`0.85 ms`** (nhanh hơn `34.3x` so với lấy 4,096 cases). |
| **Overhead `2 × LexicalSession.guard()`** | `0.0872s` | — | — | `0.0812s` | Chiếm `~38%–70%` tổng thời gian `session.search()` trên kênh `case` vì kênh `case` rất nhanh (`36–180 ms`). |

---

## 6. Các Ghi nhận Kỹ thuật Không Chặn (`0` Blocking Bugs)

Chi tiết lưu tại [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/findings.json):

1. **`F-M3LEX-01` (`low`, không chặn — Gọi `self.guard()` hai lần mỗi truy vấn trong `LexicalSession.search()` tốn `~87 ms` ngoài `timings.total_seconds`):**
   - Trong [`LexicalSession.search()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L263-L275), `self.guard()` được gọi cả trước và sau `self.reader.search_detailed()`. Mỗi lệnh `guard()` đọc và tính SHA-256 của ~38 tệp `.py`/`.json` (`~47.7 ms`/lần $\rightarrow$ **`~87.1 ms` median/truy vấn**). Thời gian này nằm ngoài `result['timings']['total_seconds']`. Khi ghép vào session full search kết hợp (chạy cả `case_bm25` và `passage_bm25`), nên chỉ gọi kiểm tra mã nguồn 1 lần ở đầu mỗi request cấp cao hoặc ghi nhận riêng `guard_seconds`.
2. **`F-M3LEX-02` (`low`, không chặn — Khác biệt chi phí `get_many` giữa `limit=4096` [`723 ms` median, tối đa `1.47s`] và `unique_cases=True, limit=100` [`4.7 ms`]):**
   - Ở `limit=4096, unique_cases=False`, [`FastBM25.get_many()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/full_search/lexical.py#L98-L114) thực hiện 16 lô truy vấn `IN (256 IDs)` vào bảng `documents` (`667 MiB`), gây đọc B-tree ngẫu nhiên tốn `0.17s – 1.47s` và có thể đẩy trang `postings` khỏi cache (như ở `Q02, Q04, Q06, Q08`). Ngược lại, khi dùng `unique_cases=True, limit=100`, `get_many()` chỉ đọc đúng 100 hàng và hoàn tất trong **`4.3 – 8.5 ms`** (median **`4.68 ms`**, nhanh hơn **`154x`**). Trong bộ tìm kiếm lai M3 sắp tới, kênh `passage_bm25` nên được gọi với `unique_cases=True, limit=100` (hoặc chỉ lấy metadata sau khi hợp nhất RRF).
3. **`F-M3LEX-03` (`info`, không chặn — I/O đọc `postings` ngoài cửa sổ `mmap_mib=512` chi phối `83%–92%` độ trễ `passage` trên máy `11.6 GiB` RAM):**
   - Tệp `lexical.sqlite3` rộng `4,058.2 MiB`, nên `mmap_mib=512` chỉ bao phủ `12.6%` đầu tệp; `87.4%` còn lại (`~3.55 GiB`) đi qua `ReadFile` và bộ đệm `128 MiB` của SQLite. Do đó, dù NumPy + `np.partition` đã rút ngắn bước tính điểm + xếp hạng `2.35x` (chỉ còn `0.14s – 2.05s`), bước `postings_fetch_seconds` vẫn chiếm `83%–92%` tổng thời gian truy vấn `passage`. Đúng như [`M3_LEXICAL.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/M3_LEXICAL.md) đã ghi rõ, việc chọn cấu hình `cache_mib`/`mmap_mib` cuối cùng cần được đo trong phiên kết hợp khi chạy đồng thời với Qdrant (`vmmemWSL`).

---

## 7. Danh mục Toàn bộ Bàn giao trong `pipeline_v2/reviews/m3_lexical_ag_review_v1/`

- [`REPORT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/REPORT.md): Báo cáo kiểm thử, đối soát độ chính xác, phân rã độ trễ/RAM và kết luận nghiệm thu theo 4 hạng mục.
- [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/findings.json): Các phán quyết phân tách (`correctness`, `actual_full_workload_parity`, `performance_cold_warm_and_resource_limits`, `full_search_readiness`), checklist 6 nhóm kiểm tra và 3 ghi nhận kỹ thuật không chặn (`F-M3LEX-01..03`).
- [`commands_and_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/commands_and_results.json): Nhật ký đầy đủ mọi lệnh đã thực thi (bao gồm cả các lần chạy hiệu chỉnh `CMD-02-ATTEMPT-1/2` và `CMD-03-ATTEMPT-1`), exit code và thời gian thực thi.
- [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/recomputed_metrics.json) & [`audit_and_recompute_metrics.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/audit_and_recompute_metrics.py): Kết quả kiểm toán độc lập toàn bộ SHA-256 fingerprints, tính bất biến của snapshot/seal, phân tích tách thứ tự thực thi của `actual_benchmark.json` và tổng hợp số đo mới.
- [`test_m3_lexical_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/test_m3_lexical_independent_ag.py) & [`independent_test_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/independent_test_results.json): Bộ kiểm thử độc lập của AG (`8/8 PASS`, gồm `15` phép tiêm lỗi trên bản sao tạm) và biên bản kết quả JSON.
- [`bounded_benchmark_manifest.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/bounded_benchmark_manifest.json), [`probe_resource_and_bounded_benchmark.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/probe_resource_and_bounded_benchmark.py) & [`bounded_benchmark_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_lexical_ag_review_v1/bounded_benchmark_results.json): Manifest khóa trước và toàn bộ số đo chi tiết (`tracemalloc` heap, Windows `GetProcessMemoryInfo`, CLI không `.env`, đối soát `--unique-cases --limit 100` và phân rã từng pha trên 8 truy vấn).
