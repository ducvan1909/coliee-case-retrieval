# Báo cáo Kiểm thử & Nghiệm thu Độc lập Chỉ mục BM25 Sparse (`m3_sparse`) và Tích hợp Hybrid (`m3_hybrid`)

- **Ngày thực hiện:** `2026-11-10`
- **Phạm vi thực hiện:** Theo [`pipeline_v2/docs/AG_REVIEW_M3_SPARSE_PROMPT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/AG_REVIEW_M3_SPARSE_PROMPT.md) và [`pipeline_v2/docs/PROGRESS.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/PROGRESS.md)
- **Thư mục bằng chứng độc lập:** [`pipeline_v2/reviews/m3_sparse_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1)
- **Code freeze SHA-256 đã xác minh:**
  - `sparse_implementation_aggregate_sha256`: `dd4eeb17401cbda28f9a14d7f9300fffde3765397e94e9bfe775385c7f2e5c7e`
  - `hybrid_implementation_aggregate_sha256`: `0a008897ab102f3cf0c72b0f4c6b6031c20e01949e6d4cd7682dcf1e3ac96eaf`
  - `lexical_implementation_aggregate_sha256`: `3633aa881ef8ff7f739a87c5c174b00faff82f59f656466a70d3804f7c0856bf`
  - `full_implementation_aggregate_sha256`: `e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503`
- **Tuân thủ ràng buộc:** Chỉ đọc trên toàn bộ mã nguồn production, cấu hình, seals và artifacts (`m3_sparse_20261110_v1`, `m3_full_train_20261108_v1`); mọi phép tiêm lỗi đều chạy trên bản sao tạm trong `tempfile.TemporaryDirectory()`; `0` lệnh gọi Modal/dựng lại corpus; không mở gold/labels hay dùng chất lượng COLIEE F1 để chọn cấu hình hiệu năng; giữ nguyên lịch sử ledger ingestion (bao gồm attempt `id=4293` trạng thái `started`, `tokens=null`).

---

## 1. Kết luận Riêng theo Từng Hạng mục (6 Separated Verdicts)

| Hạng mục | Kết luận | Tóm tắt bằng chứng định lượng |
|---|---|---|
| **`1. correctness`** | **`PASS`** | `37/37` unit/regression tests hiện có (`CMD-01`) + `6/6` nhóm kiểm thử độc lập mới của AG ([`test_m3_sparse_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/test_m3_sparse_independent_ag.py), gồm `11` phép tiêm lỗi trên bản sao tạm có tính lại seal) đều `PASS` (`0` lỗi). Công thức đóng góp BM25 `float64` tiền tính, IDF riêng từng kênh (`case` vs `passage`), bộ phân tích Unicode giữ nguyên stopwords/negation, loại trừ `exclude_case` trước khi cắt top-$K$, chọn passage đại diện bằng `np.maximum.at`/`np.minimum.at` không cộng dồn điểm các đoạn văn cùng án, tie-break theo thứ tự từ điển `id`, đọc postings hoàn toàn từ mảng mmap và chỉ truy vấn SQLite `documents` cho các hits giữ lại đều chính xác tuyệt đối. |
| **`2. index_integrity`** | **`PASS`** | Kiểm toán trực tiếp [`m3_sparse_20261110_v1`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_sparse_20261110_v1) xác nhận: `11/11` tệp trong [`seal.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_sparse_20261110_v1/seal.json) (`403,896,521` bytes / `385.186 MiB`) khớp tuyệt đối kích thước và SHA-256; `database_sha256` khớp với `lexical.sqlite3` đã seal (`6ad1f818...03fa`); cả `112,492` từ khóa kênh `case` (`7,368,370` postings, `N=7,708`) và `113,404` từ khóa kênh `passage` (`24,592,796` postings, `N=415,693`) đều có `indptr` (`uint64`) bắt đầu từ `0`, tăng nghiêm ngặt ($\text{df} \ge 1$) và kết thúc đúng bằng tổng số postings; `indices` (`uint32`) tăng nghiêm ngặt trong từng từ khóa; `values` (`float64`) hữu hạn dương và khớp `0.0` sai số trên `1,593,478` postings đối chứng trực tiếp với SQLite. |
| **`3. actual_corpus_parity`** | **`PASS`** | Trên toàn bộ `16/16` phép thử (`8` câu truy vấn đã khóa `Q01..Q08` $\times$ `2` kênh `case` & `passage`, quét từ `20,184` đến `3,639,697` postings/câu), `SparseBM25` khớp **100% danh sách ID xếp hạng** và có **`max_abs_score_diff = 0.0` (`0 ULP`)** so với cả oracle scalar SQL độc lập ([`actual_benchmark.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_validation_v1/actual_benchmark.json)) lẫn `FastBM25` (`m3_lexical`) ở cả hai chế độ `limit=4096, unique_cases=False` và `limit=100, unique_cases=True`. |
| **`4. latency_and_ram`** | **`PASS_MEASURED_WITH_MMAP_RESIDENCY_AND_GUARD_NOTES`** | **Về độ trễ:** Tách khỏi chi phí mở session (`35.25s–38.70s`) và `2 × guard()` (`~101.8 ms`), thời gian truy vấn nội tại `SparseBM25.search_detailed()` cho `--unique-cases --limit 100` đạt median **`11.82 ms` trên `case`** (`1.23 ms` cộng mảng + `9.25 ms` chọn đại diện + `1.10 ms` metadata) và **`37.09 ms` trên `passage`** (`15.71 ms` cộng mảng + `17.67 ms` chọn đại diện + `2.38 ms` metadata) — **nhanh hơn `264.3x` median (tới `1,176x` ở `Q04` và `324.1x` ở `Q08`)** so với `FastBM25` SQLite warm (`9,219.2 ms` median). Tính cả `2 × guard()`, `SparseSession.search()` đạt median **`0.117s` (`case`) và `0.166s` (`passage`)** (nhanh hơn oracle scalar **`381x`** trên `passage`).<br>**Về RAM:** Các mảng `.npy` được mở bằng `np.memmap` chỉ đọc (`369.105 MiB` payload: `85.212 MiB` case + `283.893 MiB` passage) và **không có nhánh nào sao chép toàn bộ mảng**. Sau `SparseBM25.__init__()`, Python heap (`tracemalloc`) là **`86.35 MiB`** (cho các list/dict `catalog.json`), `PrivateUsage` của tiến trình chỉ tăng **`+97.25 MiB`** (từ `414.16 MiB` lên `511.41 MiB`), còn `WorkingSetSize` đạt **`505.97 MiB`** (`514.35 MiB` trong hybrid session) do bước kiểm tra 225,896 lát cắt từ khóa lúc mở chạm qua toàn bộ các trang mmap. Khi chạy 3 truy vấn hybrid, hệ điều hành thu hồi các trang mmap ít dùng nên `WorkingSetSize` giảm xuống còn **`211.76 – 288.72 MiB`** (`PeakWorkingSetSize = 522.71 MiB`). |
| **`5. hybrid_integration`** | **`PASS_LOCAL_CACHED_VECTOR_VERIFIED_PENDING_REAL_MODAL_QUERY`** | Trên 3 truy vấn chẩn đoán dùng vector cache (`V01` [`095448.txt`], `V02` [`041666.txt`], `V03` [`000713.txt`]) chạy qua Qdrant local thật (`415,693` điểm), [`SparseHybridSession`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/sparse_bm25/index.py#L443-L478) cho kết quả **khớp 100% từng kênh (`case_bm25`, `passage_bm25`, `dense_passage`) và top-20 án sau RRF (`k=60`)** với `HybridSession` dùng SQLite ([`local_acceptance.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_validation_v1/local_acceptance.json)) cũng như bản tham chiếu cosine toàn cục (`max_dense_cosine_diff <= 1.54e-7`). Tổng thời gian hai kênh BM25 trong hybrid giảm từ **`73.04s -> 0.41s` (`177x` ở `V01`), `196.56s -> 0.61s` (`322x` ở `V02`), và `337.55s -> 0.54s` (`628x` ở `V03`)**, kéo tổng thời gian mỗi request hybrid từ **`90.64s–346.96s` xuống còn `7.37s–32.79s`** (`0` request model). Một lượt kiểm tra query embedding thật qua Modal sẽ được chạy riêng khi người dùng cấp lệnh. |
| **`6. remaining_m3_scope`** | **`INCOMPLETE_PENDING_PHRASE_IDENTITY_CONTEXT_AND_REAL_MODAL_QUERY`** | Đúng như [`PROGRESS.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/PROGRESS.md) đã ghi nhận, việc nghiệm thu `m3_sparse` và `m3_hybrid` hoàn tất các kênh xếp hạng ứng viên (`case_bm25`, `passage_bm25`, `dense_passage` + RRF), nhưng mốc M3 vẫn còn 5 hạng mục cần hoàn thiện trước khi đóng M3 sang M4: (1) `search_case` & helpers đọc án truy vấn (`case_map`/`case_anchors`), (2) `search_phrase` trên raw stream xuyên ranh giới chunk với ánh xạ char-to-byte chính xác, (3) `search_identity` cho party/citation leads có provenance, (4) `open_source` giao ngữ cảnh parent + neighbors và phân trang byte UTF-8 (đọc thẳng JSON M2 đã seal thay vì gọi lại tokenizer trong `PassageReader._case()`), và (5) 1 lượt kiểm tra query embedding thật qua Modal. |

---

## 2. Kiểm toán Fingerprints, Seals & Lịch sử Ledger Ingestion ([`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/recomputed_metrics.json))

1. **Tính bất biến của mã nguồn và 39 tệp upstream:**
   - Mã nguồn mới của `m3_sparse`:
     - [`pipeline_v2/m3_sparse.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/m3_sparse.py): `b26f817d1abbc8ee11585d7ec63803d14cf11558a45d767414e62d60fee16b4f`
     - [`pipeline_v2/sparse_bm25/__init__.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/sparse_bm25/__init__.py): `a30002c62f6ae8a6a7959fc8f20a355571e4b9fec33a9eec4b45a007de0a79f7`
     - [`pipeline_v2/sparse_bm25/index.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/sparse_bm25/index.py): `0b6ad4035ade3f0604cb7f1187d6cd839aec858e0122d0dbb5a2954ced9f18c8`
     - [`pipeline_v2/configs/m3_sparse.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/configs/m3_sparse.json): `ed8ef9650fe80fe18cd9525208076c952883024c3ec7909d3ef309a22eca8dc4`
   - Toàn bộ `39/39` tệp mã nguồn trước đó trong [`prior_state.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_validation_v1/prior_state.json) (`full_corpus`, `full_search/lexical.py`, `full_search/hybrid.py`, `navigation`, `passages`, `retrieval`, `source`, `optimization_v2`) đều khớp tuyệt đối SHA-256 (`prior_state_mismatches = []`).
2. **Kiểm toán Seal và Cấu trúc Mảng của `m3_sparse_20261110_v1`:**
   - Tổng cộng `11/11` tệp được niêm phong trong [`seal.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_sparse_20261110_v1/seal.json) (`403,896,521` bytes = `385.186 MiB`) khớp 100% kích thước và SHA-256:

| Tệp trong `m3_sparse_20261110_v1` | Kích thước (`bytes` / `MiB`) | Kiểu / Hình dạng (`dtype` / `shape`) | Nội dung & Bất biến đã xác minh |
|---|---:|---|---|
| `manifest.json` | `5,383` B (`0.005 MiB`) | JSON | Khóa `database_sha256 = 6ad1f818...03fa`, `elapsed_seconds = 228.26s`, thống kê 2 kênh. |
| `case.catalog.json` | `1,406,819` B (`1.342 MiB`) | JSON | `7,708` `ids` tăng dần, `7,708` `cases` tăng dần, `112,492` `terms` tăng dần. |
| `case.cases.npy` | `30,960` B (`0.030 MiB`) | `uint32`, `(7708,)` | Mã án `0..7707` cho từng tài liệu kênh `case`. |
| `case.indptr.npy` | `900,072` B (`0.858 MiB`) | `uint64`, `(112493,)` | `offsets[0] = 0`, `offsets[-1] = 7,368,370`, $\text{df} \in [1, 7708]$, median $\text{df} = 2.0$. |
| `case.indices.npy` | `29,473,608` B (`28.108 MiB`) | `uint32`, `(7368370,)` | Ordinal tài liệu `0..7707` tăng nghiêm ngặt trong mọi lát cắt từ khóa. |
| `case.values.npy` | `58,947,088` B (`56.216 MiB`) | `float64`, `(7368370,)` | Điểm đóng góp BM25 tiền tính $\in [4.82 \times 10^{-5}, 21.1393]$, hữu hạn dương. |
| `passage.catalog.json` | `15,448,515` B (`14.733 MiB`) | JSON | `415,693` `ids` tăng dần, `7,708` `cases` tăng dần, `113,404` `terms` tăng dần. |
| `passage.cases.npy` | `1,662,900` B (`1.586 MiB`) | `uint32`, `(415693,)` | Mã án `0..7707` của `415,693` passages. |
| `passage.indptr.npy` | `907,368` B (`0.865 MiB`) | `uint64`, `(113405,)` | `offsets[0] = 0`, `offsets[-1] = 24,592,796`, $\text{df} \in [1, 359820]$, median $\text{df} = 4.0$. |
| `passage.indices.npy` | `98,371,312` B (`93.814 MiB`) | `uint32`, `(24592796,)` | Ordinal đoạn văn `0..415692` tăng nghiêm ngặt trong mọi lát cắt từ khóa. |
| `passage.values.npy` | `196,742,496` B (`187.628 MiB`) | `float64`, `(24592796,)` | Điểm đóng góp BM25 tiền tính $\in [0.0761, 27.7450]$, hữu hạn dương. |
| *Phụ trợ ngoài `seal.json`:* `seal.json` (`1,250` B) & `build_progress.json` (`88` B) | `1,338` B | JSON | Biên bản niêm phong và trạng thái checkpoint cuối (`completed = 31,961,166`). |

3. **Bảo toàn lịch sử Ledger Ingestion (`m3_full_train_20261108_v1/ledger.sqlite3`):**
   - Kiểm tra trực tiếp bảng `attempts` xác nhận lịch sử chạy Modal hoàn toàn nguyên vẹn:
     - `6,496` attempts có `status = 'success'`, `requests = 6,496`, tổng `tokens = 55,346,360` (`0` dòng `null`), tổng `elapsed = 16,753.736s`.
     - `1` attempt bị ngắt kết nối lịch sử được giữ nguyên: **`id = 4293` (`batch = 'full-documents-4292'`, `phase = 'v2_document'`, `status = 'started'`, `requests = 1`, `tokens = null`, `elapsed = null`)**.
     - Tất cả các phép đo `m3_sparse` và `m3_hybrid` trong đợt này đều có **`model_requests = 0`**.

---

## 3. Kiểm chứng Độc lập Tính Đúng đắn, Mảng Mmap & Tiêm lỗi (`test_m3_sparse_independent_ag.py`)

Bộ kiểm thử độc lập [`test_m3_sparse_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/test_m3_sparse_independent_ag.py) (`6/6 PASS` trong `26.71s`, kết quả tại [`independent_test_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/independent_test_results.json)) cùng với kiểm toán trên corpus thật đã chứng minh:

1. **Công thức `float64` tiền tính và IDF riêng từng kênh (`test_01`):**
   - Trong [`build_from_database()`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/sparse_bm25/index.py#L112-L209), builder duyệt tuần tự `SELECT kind,term,id,tf FROM postings NOT INDEXED ORDER BY rowid` theo lô `fetchmany(8192)` (tránh tra cứu B-tree ngẫu nhiên), tính $\text{idf}(t) = \ln(1 + \frac{N - \text{df}(t) + 0.5}{\text{df}(t) + 0.5})$ riêng cho từng kênh và lưu `values = idf * tf * (k1 + 1) / (tf + norm)` ở định dạng `np.float64`.
   - Đối chứng trực tiếp 30 từ khóa kênh `case` (`39,533` postings) và 30 từ khóa kênh `passage` (`1,553,945` postings, bao gồm 5 từ có $\text{df}$ lớn nhất tới `359,820` postings/từ) giữa mảng `.npy` và công thức tính lại từ `lexical.sqlite3` cho **`spotcheck_max_abs_formula_diff = 0.0`**.
   - Đối chứng với oracle `float32` cho thấy sai lệch `> 1e-8`, khẳng định toàn bộ đường ống tính điểm giữ chuẩn `float64`.
2. **Loại trừ `exclude_case` trước Top-$K$ và Chọn Passage Đại diện Không cộng dồn điểm (`test_02`):**
   - Tại [dòng 324–326](file:///e:/Git/coliee-case-retrieval/pipeline_v2/sparse_bm25/index.py#L324-L326), `scores[channel['cases'] == excluded] = 0` được thực thi ngay sau vòng lặp cộng điểm từ khóa, trước khi đếm `positive_count` và trước cả hai nhánh `unique_cases=True/False`.
   - Khi `unique_cases=True` ([dòng 330–337](file:///e:/Git/coliee-case-retrieval/pipeline_v2/sparse_bm25/index.py#L330-L337)):
     - `np.maximum.at(best, channel['cases'], scores)` tìm điểm đoạn văn cao nhất của từng án (tuyệt đối không cộng tổng điểm các đoạn văn cùng án).
     - `candidates = np.flatnonzero((scores > 0) & (scores == best[channel['cases']]))` lọc các đoạn văn đạt điểm tối đa của án đó, rồi `np.minimum.at(representatives, channel['cases'][candidates], candidates.astype(np.uint32))` chọn đúng đoạn văn có ordinal nhỏ nhất (tức `passage_id` nhỏ nhất theo thứ tự từ điển vì `catalog['ids']` được sắp xếp tăng dần).
     - Cuối cùng `ranked_cases = sorted(np.flatnonzero(best > 0), key=lambda code: (-best[code], int(representatives[code])))[:limit]` xếp hạng các án theo điểm giảm dần và tie-break giữa hai án đồng điểm bằng ordinal của đoạn văn đại diện (vốn là song ánh giữ nguyên thứ tự với `passage_id`, hoàn toàn tương đương với tie-break trong `FastBM25` và oracle scalar).
3. **Chứng minh chỉ đọc Postings từ Mảng Mmap và chỉ mở Metadata cho Hits Giữ lại (`test_03`):**
   - `SQLSpyConnection` bọc kết nối SQLite của `SparseBM25`: khi chạy `search_detailed(..., limit=2, unique_cases=True)`, số câu lệnh SQL gửi tới SQLite là **đúng `1` câu lệnh duy nhất**: `SELECT id,metadata FROM documents WHERE kind=? AND id IN (?,?)` với 3 tham số (`'passage'` và 2 ID giữ lại). Bảng `postings` và `terms` **không bao giờ được truy vấn** trong lúc tìm kiếm; khi truy vấn OOV/rỗng, có **`0` câu lệnh SQL** nào được gọi.
4. **Tiêm lỗi trên Bản sao Tạm có Tính lại Seal (`test_04`, `test_05`, `test_06`):**
   - Toàn bộ 11 kịch bản tiêm lỗi trên bản sao tạm đều bị chặn bởi `M3Error`:
     - Trùng ordinal tài liệu trong một từ khóa (`indices[start+1] = indices[start]`, đã tính lại `seal.json`),
     - Đảo ngược thứ tự ordinal tài liệu trong một từ khóa (đã tính lại `seal.json`),
     - Từ khóa rỗng `offsets[1] == offsets[0]` hoặc `offsets[0] != 0` (đã tính lại `seal.json`),
     - Điểm đóng góp `values <= 0` (`0.0`, `-1.5`) hoặc `np.inf` (đã tính lại `seal.json`),
     - `catalog.json` có danh sách `ids` không tăng dần nghiêm ngặt (đã tính lại `seal.json`),
     - Dư hoặc thiếu mục trong `seal.json`,
     - Bảng `documents` trong bản sao SQLite chứa trường `"text"` cấm, lệch `case_id` so với mảng `cases.npy`, hoặc bị xóa dòng metadata,
     - Đột biến mã nguồn trong lúc phiên đang mở khiến `SparseSession.guard()` khóa cứng phiên (`session.invalidated = True`), và đảm bảo đóng sạch `sqlite3.Connection` + `np.memmap` khi `__init__` ném ngoại lệ.

---

## 4. Phân rã Độ trễ Từng Pha (8 Truy vấn Khóa `Q01..Q08`) & Phân tích Bộ nhớ / Mmap Thực tế

### 4.1. Phân rã Thời gian Kênh `passage` và `case` trên 8 Truy vấn (`Q01..Q08`)

Bảng dưới đây đối chiếu trực tiếp thời gian từng pha của `SparseBM25` (`m3_sparse`) với `FastBM25` (`m3_lexical` warm steady-state) và oracle scalar SQLite ([`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/recomputed_metrics.json#L65502-L66027)):

| Query (`Terms` / `Postings` / `Matched Passages`) | Kênh `case` `Unique-100` Nội tại (`ms`) [Scoring / Top / Meta] | Kênh `passage` `Unique-100` Nội tại (`ms`) [Scoring / Top / Meta] | Kênh `passage` `Unique-100` Có `2×guard` (`s`) | `FastBM25` SQLite Warm `Unique-100` (`s`) | Oracle Scalar SQLite (`s`) | **Tăng tốc `Unique-100` Nội tại vs `FastBM25` Warm** | **Tăng tốc `Unique-100` Outer vs Oracle Scalar** | Kênh `passage` `Raw-4096` Nội tại (`s`) [Meta `4096`] |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`Q01`** (`4` / `245k` / `181.7k`) | **`10.41 ms`** [`0.33` / `8.95` / `1.08`] | **`36.81 ms`** [`14.07` / `19.76` / `2.59`] | `0.127s` | `1.580s` | `33.928s` | **`42.9x`** (`46.6x` score+top) | **`266.4x`** | `1.213s` [`1.205s` meta] |
| **`Q02`** (`6` / `480k` / `365.6k`) | **`10.40 ms`** [`0.75` / `8.64` / `0.97`] | **`38.52 ms`** [`8.67` / `26.02` / `3.54`] | `0.165s` | `2.963s` | `48.996s` | **`76.9x`** (`85.3x` score+top) | **`297.2x`** | `1.207s` [`1.190s` meta] |
| **`Q03`** (`8` / `863k` / `374.7k`) | **`10.77 ms`** [`0.66` / `8.66` / `1.37`] | **`24.45 ms`** [`6.86` / `15.25` / `2.17`] | `0.168s` | `4.997s` | `99.834s` | **`204.4x`** (`225.8x` score+top) | **`595.9x`** | `1.240s` [`1.217s` meta] |
| **`Q04`** (`12` / `1.39M` / `394.7k`) | **`10.84 ms`** [`1.06` / `8.71` / `1.02`] | **`37.21 ms`** [`15.84` / `18.61` / `2.31`] | `0.201s` | `43.774s` | `110.993s` | **`1,176.5x`** (`1,268.7x` score+top) | **`553.1x`** | `0.955s` [`0.931s` meta] |
| **`Q05`** (`14` / `1.16M` / `372.4k`) | **`13.32 ms`** [`1.40` / `10.41` / `1.45`] | **`36.96 ms`** [`17.65` / `16.76` / `2.30`] | `0.166s` | `6.939s` | `75.595s` | **`187.7x`** (`201.4x` score+top) | **`454.6x`** | `0.884s` [`0.855s` meta] |
| **`Q06`** (`18` / `1.87M` / `379.9k`) | **`21.62 ms`** [`2.21` / `18.24` / `1.11`] | **`32.72 ms`** [`15.58` / `14.79` / `2.19`] | `0.156s` | `11.500s` | `137.725s` | **`351.4x`** (`378.3x` score+top) | **`885.3x`** | `1.021s` [`0.975s` meta] |
| **`Q07`** (`35` / `2.34M` / `400.3k`) | **`12.81 ms`** [`2.28` / `9.55` / `0.93`] | **`42.27 ms`** [`22.31` / `17.27` / `2.44`] | `0.160s` | `15.206s` | `47.702s` | **`359.7x`** (`383.9x` score+top) | **`297.3x`** | `0.775s` [`0.742s` meta] |
| **`Q08`** (`47` / `3.64M` / `406.6k`) | **`16.09 ms`** [`3.04` / `11.84` / `1.16`] | **`70.31 ms`** [`45.08` / `18.06` / `6.75`] | `0.172s` | `22.790s` | `50.707s` | **`324.1x`** (`360.7x` score+top) | **`294.9x`** | `0.238s` [`0.174s` meta] |
| **Median qua 8 Queries** | **`11.82 ms`** [`1.23` / `9.25` / `1.10`] | **`37.09 ms`** [`15.71` / `17.67` / `2.38`] | **`0.166s`** | **`9.219s`** | **`63.151s`** | **`264.3x` (`293.3x` score+top)** | **`381.4x`** | **`0.988s`** [`0.953s` meta] |

**Nhận xét kỹ thuật quan trọng từ bảng phân rã:**
- Ở chế độ `unique_cases=True, limit=100` (chế độ thực tế dùng trong hybrid search), việc cộng tới `3.64 triệu` postings trên kênh `passage` chỉ mất **`6.86 ms – 45.08 ms` (median `15.71 ms`)**, chọn 100 án đại diện mất **`14.79 ms – 26.02 ms` (median `17.67 ms`)**, và lấy 100 dòng metadata từ SQLite chỉ mất **`2.17 ms – 6.75 ms` (median `2.38 ms`)**.
- Ở chế độ `limit=4096, unique_cases=False`, bản thân bước cộng mảng và chọn top-4096 cũng chỉ mất **`14.46 ms + 10.59 ms = 25.05 ms` median**, nhưng việc đọc `4,096` dòng metadata từ bảng `documents` (`667 MiB`) trong SQLite chiếm **`953.28 ms` median (`96.5%` thời gian)**. Do đó, việc `SparseHybridSession` gọi `unique_cases=True, limit=100` đã loại bỏ hoàn toàn nút thắt đọc metadata này.

### 4.2. Phân rã Bộ nhớ (`tracemalloc` Heap vs OS `WorkingSetSize` / `PrivateUsage` & Mmap Views)

Kết quả đo từ 2 tiến trình con độc lập trong [`audit_and_recompute_sparse.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/audit_and_recompute_sparse.py) và [`hybrid_memory.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_validation_v1/hybrid_memory.json):

| Giai đoạn Đo (Clean OS Subprocess & Hybrid Run) | Python Heap (`tracemalloc` Current / Peak) | OS `WorkingSetSize` (Resident RAM) | OS `PeakWorkingSetSize` | OS `PrivateUsage` (Commit Charge) | Số Page Faults | Giải thích Kỹ thuật & Các Nhánh Cấp phát Mảng |
|---|---:|---:|---:|---:|---:|---|
| **1. Trước khi mở `SparseBM25`** | `0.007 MiB` | `40.109 MiB` | `40.109 MiB` | `414.160 MiB` | `10,517` | Nền runtime Python + NumPy. |
| **2. Ngay sau `SparseBM25.__init__` (`8.07s` không hash DB)** | **`86.350 MiB`** / Peak `110.355 MiB` | **`505.969 MiB`** (`+465.86 MiB`) | `505.969 MiB` | **`511.414 MiB`** (`+97.25 MiB`) | `276,294` | `PrivateUsage` chỉ tăng **`+97.25 MiB`** (chứa `86.35 MiB` Python heap của `catalog.json` lists/dicts). `WorkingSetSize` tăng thêm `~369 MiB` là do vòng lặp kiểm tra `225,896` từ khóa lúc mở chạm vào toàn bộ `369.105 MiB` trang `np.memmap` chỉ đọc. |
| **3. Sau `Q01` kênh `case` (`unique_cases=100`)** | `86.507 MiB` | `507.281 MiB` | `507.281 MiB` | `513.418 MiB` (`+2.00 MiB`) | `276,630` | Mảng `scores` kênh `case` chỉ tốn `7,708 × 8 B = 60.2 KiB`. |
| **4. Sau `Q01` kênh `passage` (`unique_cases=100`)** | `87.065 MiB` | `508.867 MiB` | `514.043 MiB` | `515.027 MiB` (`+1.61 MiB`) | `278,966` | Cấp phát tạm thời mảng `scores` (`3.17 MiB`), `best` (`60.2 KiB`), `representatives` (`30.1 KiB`) và mảng boolean/index `candidates` (`~2.0 MiB`). Không sao chép mảng postings (`indices[offset:stop]` chỉ tạo view trên `memmap`). |
| **5. Sau `Q08` kênh `passage` (`raw limit=4096`)** | `110.052 MiB` / Peak `116.564 MiB` | `565.742 MiB` | `568.914 MiB` | `572.023 MiB` (`+57.00 MiB`) | `298,352` | Bộ đệm `32 MiB` của SQLite nạp các trang B-tree bảng `documents` khi lấy `4,096` metadata + `4,096` dicts kết quả. |
| **6. Sau `Q08` kênh `passage` (`unique_cases=100`)** | `110.722 MiB` | `566.812 MiB` | `572.992 MiB` | `572.980 MiB` (`+0.96 MiB`) | `300,559` | Bộ nhớ hoàn toàn ổn định, không rò rỉ qua các truy vấn lớn. |
| **7. Sau `reader.close()`** | — | **`165.773 MiB`** (`-401.04 MiB`) | `572.992 MiB` | `539.898 MiB` | `300,577` | Đóng `_mmap.close()` và `db.close()` giải phóng ngay `~401 MiB` khỏi `WorkingSetSize`. |
| **8. Trong phiên `SparseHybridSession` (`V01 -> V03`)** | — | Mở: `514.35 MiB` $\rightarrow$ **`211.76 – 288.72 MiB`** | **`522.71 MiB`** | Mở: `518.27 MiB` $\rightarrow$ `604.42 – 615.00 MiB` | — | Khi chạy cùng Qdrant và nạp `_ScheduleVectors` shards (tối đa `32` shards $\approx 20\text{ MiB}$), Windows tự động thu hồi các trang `mmap` không dùng của `.npy`, kéo `WorkingSetSize` thực tế của tiến trình Python xuống chỉ còn **`212 – 289 MiB`**. |

---

## 5. Kiểm toán Tích hợp Hybrid (`SparseHybridSession`) trên 3 Truy vấn Chẩn đoán (`V01`, `V02`, `V03`)

Đối chiếu độc lập giữa [`m3_sparse_validation_v1/qdrant_cached_benchmark.jsonl`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_validation_v1/qdrant_cached_benchmark.jsonl), [`m3_hybrid_validation_v1/qdrant_cached_benchmark.jsonl`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_hybrid_validation_v1/qdrant_cached_benchmark.jsonl), [`offline_cached_benchmark.jsonl`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_hybrid_validation_v1/offline_cached_benchmark.jsonl) và [`dense_reference.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_hybrid_validation_v1/dense_reference.json):

| Truy vấn (`Query Case` / `Passage ID` / Số từ khóa) | Khớp Kênh & Top-20 RRF (`SQLite` vs `Sparse` vs `Offline`) | Sai lệch Cosine Tối đa vs Cache Đã Seal (`atol=1e-5`) | Coverage `case_bm25` / `passage_bm25` / `dense_passage` | **Tổng BM25: `SQLite` $\rightarrow$ `Sparse` [Tăng tốc]** | **Riêng `passage_bm25`: `SQLite` $\rightarrow$ `Sparse` [Tăng tốc]** | `dense_query` + `dense_val` (`Sparse`) | **Tổng Hybrid: `SQLite` $\rightarrow$ `Sparse` [Tăng tốc]** | Top-3 Án Xếp hạng RRF (`case_id` : `score`) |
|---|---|---:|---|---|---|---|---|---|
| **`V01`** (`095448.txt` / `095448:88b488d43fde1389756a8dd7` / `19` từ) | **`100% Exact Match`** | `1.538e-7` | `100` / `100` / `100` (`raw_hits=4096`, `eligible=415,653`, `tie_possible=False`) | **`73.04s` $\rightarrow$ `0.413s` [`177.0x`]** | **`64.77s` $\rightarrow$ `0.205s` [`316.1x`]** | `26.59s` + `5.04s` | **`90.64s` $\rightarrow$ `32.79s` [`2.76x`]** | `1.` `028038.txt` (`0.04918033`)<br>`2.` `038425.txt` (`0.04383013`)<br>`3.` `004125.txt` (`0.04185520`) |
| **`V02`** (`041666.txt` / `041666:b5120463c47e98934ef7bde9` / `61` từ) | **`100% Exact Match`** | `1.284e-7` | `100` / `100` / `100` (`raw_hits=4096`, `eligible=415,138`, `tie_possible=False`) | **`196.56s` $\rightarrow$ `0.611s` [`321.9x`]** | **`187.61s` $\rightarrow$ `0.409s` [`459.0x`]** | `5.80s` + `4.35s` | **`216.65s` $\rightarrow$ `11.46s` [`18.90x`]** | `1.` `057494.txt` (`0.04511454`)<br>`2.` `000393.txt` (`0.04402951`)<br>`3.` `008666.txt` (`0.04389437`) |
| **`V03`** (`000713.txt` / `000713:3a2a0520d60f55dd1d773c75` / `111` từ) | **`100% Exact Match`** | `8.899e-8` | `100` / `100` / `100` (`raw_hits=4096`, `eligible=415,510`, `tie_possible=False`) | **`337.55s` $\rightarrow$ `0.537s` [`628.4x`]** | **`334.15s` $\rightarrow$ `0.348s` [`959.3x`]** | `1.90s` + `4.07s` | **`346.96s` $\rightarrow$ `7.37s` [`47.07x`]** | `1.` `074684.txt` (`0.04814747`)<br>`2.` `097676.txt` (`0.04210584`)<br>`3.` `093486.txt` (`0.03992988`) |

- **Xác minh độc lập RRF, Exclusion & Coverage:**
  - Trên cả 3 truy vấn, án truy vấn (`095448.txt`, `041666.txt`, `000713.txt`) đều bị loại trừ hoàn toàn khỏi cả 3 kênh trước khi lấy top-100 án duy nhất.
  - Phép tính lại RRF độc lập bằng `math.fsum(1 / (60 + rank))` khớp từng bit (`float64` exact equality) với `response['hits']`.
  - Toàn bộ `101` điểm dense được kiểm tra mỗi truy vấn (`100` passage đại diện của 100 án + `1` hit cuối ở biên `4,096`) đều khớp payload với `lexical.sqlite3` và khớp điểm cosine với các shard `.npz` đã seal trong `m3_full_train_20261108_v1/vectors/`.

---

## 6. Ghi nhận Kỹ thuật Không Chặn (`0` Blocking Bugs) & Phạm vi M3 Còn lại

Chi tiết lưu tại [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/findings.json):

1. **`F-M3SPARSE-01` (`low`, không chặn — Khởi tạo `SparseBM25.__init__()` hash `~385 MiB` và quét `225,896` từ khóa mất `~8.1s`, nạp `~369 MiB` trang mmap vào `WorkingSet` ban đầu):**
   - Thiết kế này giúp bắt mọi lỗi hỏng mảng ngữ nghĩa ngay khi mở reader (kể cả khi `seal.json` bị giả mạo), nhưng khiến mỗi lần mở mới `SparseSession` tốn `~35–39s` (gồm cả `load_plan` hash `4.36 GB` SQLite) và đưa các trang mmap vào `WorkingSet` cho tới khi OS thu hồi. Do đó, trong M4/M5 harness cần giữ đúng nguyên tắc tái sử dụng một `SparseHybridSession` cho toàn bộ phiên chạy.
2. **`F-M3SPARSE-02` (`low`, không chặn — Chi phí băm 42 tệp mã nguồn trong `guard()` [`~50.9 ms`/lần] hiện lớn hơn thời gian chấm điểm BM25 thuần túy [`11.8 ms` case, `37.1 ms` passage]):**
   - Mỗi lệnh `SparseSession.search()` gọi `guard()` 2 lần (`~101.8 ms`), và mỗi lệnh `SparseHybridSession._search()` gọi `guard()` tổng cộng 7 lần (`~356.2 ms`). Vì tổng thời gian BM25 trong hybrid chỉ còn `0.41s–0.61s` (nhanh hơn `177x–628x` so với SQLite), chi phí này không ảnh hưởng tới nghiệm thu M3 nhưng có thể rút gọn còn 1 lần kiểm tra ở đầu mỗi request cấp cao khi sang M4.
3. **`F-M3SPARSE-03` (`info`, không chặn — `SparseSession.revalidate()` mở tạm phiên thứ hai trước khi đóng):**
   - `revalidate()` tạo `fresh = SparseSession(...)` rồi gọi `fresh.close()`, tạm thời nhân đôi `~86.35 MiB` catalog heap trong vài giây trước khi giải phóng. Không ảnh hưởng tới luồng tìm kiếm.
4. **`F-M3SPARSE-04` (`info` — Phân định rõ phạm vi M3 đã đạt và phần việc còn lại của M3):**
   - **Đã hoàn thành và đạt nghiệm thu kỹ thuật:** Full corpus ingestion (`415,693` passages, `7,708` cases), chỉ mục BM25 sparse hai kênh (`m3_sparse`), tích hợp Qdrant exact dense + RRF fusion + query-case exclusion (`m3_hybrid`), và kiểm chứng toàn diện bằng vector cache.
   - **Phần việc còn lại để khép kín mốc M3 (theo [`PROGRESS.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/PROGRESS.md) và [`plan/M3_FULL_SEARCH.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/plan/M3_FULL_SEARCH.md)):**
     1. Triển khai `search_case` (tìm kiếm trong phạm vi một bản án, bao gồm cả án truy vấn) và các hàm đọc cấu trúc án truy vấn (`case_map`/`case_anchors`).
     2. Triển khai `search_phrase` (tìm cụm từ chính xác/không phân biệt hoa thường trên raw stream xuyên qua ranh giới chunk/heading, kèm kiểm tra ánh xạ offset char-to-byte UTF-8).
     3. Triển khai `search_identity` (truy tìm party/citation leads quan sát được từ bề mặt văn bản kèm raw provenance, không suy diễn thực thể ẩn).
     4. Triển khai & kiểm thử `open_source` / giao ngữ cảnh (`parent` + `previous/next` neighbors, hợp nhất khoảng chồng lấp, phân trang byte UTF-8 tối đa `64 KiB`, đọc thẳng JSON M2 đã seal thay vì gọi lại tokenizer trong `PassageReader._case()`).
     5. Thực thi đúng 1 lượt kiểm tra query embedding thật qua Modal (`m3_sparse search-hybrid` / `m3_hybrid search`) khi người dùng cho phép.

---

## 7. Danh mục Bàn giao trong `pipeline_v2/reviews/m3_sparse_ag_review_v1/`

- [`REPORT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/REPORT.md): Báo cáo kiểm thử và nghiệm thu độc lập đầy đủ với 6 kết luận tách biệt.
- [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/findings.json): Các phán quyết phân tách, bảng kiểm 8 hạng mục kỹ thuật và 4 ghi nhận (`F-M3SPARSE-01..04`, `0` lỗi chặn).
- [`commands_and_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/commands_and_results.json): Nhật ký toàn bộ các lệnh kiểm thử và kiểm toán đã chạy (bao gồm cả các lượt chạy sửa script kiểm thử `CMD-02-ATTEMPT-1/2`, `CMD-03-ATTEMPT-1/2`), exit code và thời gian thực thi.
- [`test_m3_sparse_independent_ag.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/test_m3_sparse_independent_ag.py) & [`independent_test_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/independent_test_results.json): Bộ kiểm thử độc lập và tiêm lỗi trên bản sao tạm (`6/6 PASS`).
- [`audit_and_recompute_sparse.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/audit_and_recompute_sparse.py) & [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_sparse_ag_review_v1/recomputed_metrics.json): Script kiểm toán toàn corpus và biên bản số liệu tính lại độc lập (fingerprints, seals, ledger history, invariants mảng mmap, đối chứng công thức float64, phân rã RAM `tracemalloc` vs OS `WorkingSet`/`PrivateUsage`, phân rã độ trễ 8 truy vấn lexical và 3 truy vấn hybrid).
