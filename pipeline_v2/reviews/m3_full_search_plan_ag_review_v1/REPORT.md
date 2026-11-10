# Báo cáo AG Review Thiết kế Kế hoạch M3 Full Search (Chưa Triển khai)

- **Ngày thực hiện:** `2026-11-09`
- **Tài liệu được review:** [`pipeline_v2/docs/plan/M3_FULL_SEARCH.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/plan/M3_FULL_SEARCH.md) (giữ nguyên read-only)
- **Tài liệu quy định & đối chiếu:** [`AG_REVIEW_M3_FULL_SEARCH_PLAN_PROMPT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/AG_REVIEW_M3_FULL_SEARCH_PLAN_PROMPT.md), [`SOURCE_CHUNK_INDEX.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/plan/SOURCE_CHUNK_INDEX.md), [`AGENT_AND_EVALUATION.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/plan/AGENT_AND_EVALUATION.md), [`README.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/plan/README.md), [`M3_FULL.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/M3_FULL.md), [`AG_REVIEW_ACCEPTANCE.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_validation_v1/AG_REVIEW_ACCEPTANCE.md)
- **Thư mục bằng chứng review:** [`pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1)
- **Tuân thủ giới hạn thực thi:** Chỉ đọc đối với toàn bộ code production, cấu hình, nguồn raw, `m3_full_train_20261108_v1` và Qdrant; không đọc `.env`, không gọi Modal, không truy cập gold/labels/evaluator.

---

## 1. Kết luận Tổng thể (Verdict)

- **Verdict:** **`approve_with_changes`**
- **Tóm tắt đánh giá:**
  Kiến trúc tổng thể của [`M3_FULL_SEARCH.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/plan/M3_FULL_SEARCH.md) (tách namespace `pipeline_v2/full_search/`, 3 kênh retrieval độc lập, loại trừ `query_case` trước khi cắt ngọn, hợp nhất RRF ở mức unique-case thay vì cộng dồn phiếu đoạn văn, tìm kiếm nguyên văn vắt qua ranh giới chunk trên luồng raw, và mở ngữ cảnh `parent + neighbors` có phân trang byte kèm provenance) là **đúng đắn và nhất quán với hợp đồng M1–M3**.
  Tuy nhiên, qua kiểm tra thực nghiệm chỉ đọc trên dữ liệu thật (`415,693` passages / `7,708` cases trong `lexical.sqlite3`, collection Qdrant `coliee_m3_full_ef2f4d6950a5b9fd` và bundle M2) cùng bộ 11 counterexamples độc lập ([`test_plan_counterexamples.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/test_plan_counterexamples.py)), AG phát hiện **6 điểm nghẽn kỹ thuật/đặc tả (`F-PLAN-01` đến `F-PLAN-06`)** cần được Main chốt và cập nhật vào bản kế hoạch revision ở mốc **S0** trước khi giao code **S1–S5**. Lưu ý: đây là các khoảng trống đặc tả trong bản nháp kế hoạch hoặc điểm không tương thích nếu bê nguyên các hàm helper từ bản pilot (`1,024` passages) sang quy mô full (`415,693` passages), **không phải** lỗi của đợt ingestion M3 Full đã nghiệm thu.

---

## 2. Các Blocker Thiết kế Cần Chốt ở Mốc S0 Trước Khi Code

| Mã Finding | Mức độ | Vấn đề cốt lõi & Bằng chứng thực nghiệm / Counterexample | Thay đổi cần cập nhật vào Kế hoạch (S0) |
|---|---|---|---|
| **`F-PLAN-01`** | **High (Blocker)** | **RRF chưa chặn trần `100` unique cases/kênh trước khi cộng điểm & sai lệch mẫu số coverage (`CE01`, `CE02`, `CE05`):** Hàm `fuse_case_ranks` hiện có ([`retrieval/bm25.py:45-53`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/retrieval/bm25.py#L45-L53)) gọi `rank_cases(hits, limit=None)`. Nếu một kênh quét `2,048` raw hits thu được `300` unique cases còn kênh kia thu được `100`, các hạng `101..300` vẫn đóng góp `1/(60+r)` vào RRF, gây đảo hạng top-1 (`CE05`). Ngược lại, [`optimization_v2/index.py:211`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization_v2/index.py#L211) lại cắt danh sách từng kênh theo `limit=20` thay vì `100`. Ngoài ra, khi loại trừ `query_case` thuộc tập train, mẫu số vũ trụ hợp lệ là **`7,707` (`N - 1`)**, không phải `7,708`. | Quy định rõ: (1) mỗi kênh dedup theo best-hit và **cắt đúng `<= channel_case_budget (100)` unique cases trước khi đưa vào `fuse_case_ranks`**; (2) giữ danh sách `100` unique cases mỗi kênh trong response metadata, chỉ áp `limit=20` lên danh sách sau fusion; (3) mẫu số `eligible_case_universe = 7,707` (trừ chế độ diagnostic ngoài tập); (4) tách bạch `universe_exhausted` vs `scan_capped` vs `budget_shortfall`. |
| **`F-PLAN-02`** | **High (Blocker)** | **Timeout nội bộ 60s của Qdrant khi chạy `exact=True` lần đầu (cold), lãng phí nếu gọi lặp 5 vòng `exact=True`, và chi phí đọc `2,860` shards `.npz`:** Thực nghiệm ([`probe_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_results.json)) cho thấy truy vấn `exact=True` đầu tiên bị lỗi HTTP 500 tại **`60.0s`** (`Operation 'Search' timed out after 59.99978s`) vì `QdrantStore.search` thiếu tham số URL `?timeout=120`. Khi đã warm, `exact=True` chỉ mất **`2.42s`** ở `limit=4096` và **`2.65s`** ở `limit=256` (bằng nhau vì `exact=True` luôn quét đủ `415,693` vectors). Ngoài ra, `4,096` raw hits trải rộng trên **`2,860` shards `.npz`**; nếu kiểm tra vector từ `ReadonlyCache` cho cả `4,096` raw hits sẽ mất **`~31.1s` I/O**, trong khi kiểm tra các passage leads được giữ lại của `100` unique cases chỉ chạm **`97` shards (`~1.0s` cold, `<0.1s` với LRU)**. | Quy định rõ: (1) truyền `?timeout=120` vào URL `/points/query` của Qdrant; (2) với `exact=True`, truy vấn Qdrant 1 lần ở `limit=scan_cap` (`4096`, hoặc tối đa 2 bước `256 -> 4096`) rồi thực hiện bước nhảy adaptive `256 -> 512 -> 1024 -> 2048 -> 4096` trong RAM; (3) chỉ đối soát vector trên `ReadonlyCache` (kèm LRU shard cache và tra cứu `schedule` `passage_id -> batch`) cho các passage leads được giữ lại (`<= 100 * max_leads_per_case`) và điểm biên. |
| **`F-PLAN-03`** | **Medium (Blocker)** | **Độ trễ `PersistentBM25.search('passage')` (`104s–121s`) và nguy cơ gọi lặp 5 lần:** Trên `lexical.sqlite3` (`4.36 GB`), câu lệnh `JOIN documents` trong [`optimization_v2/index.py:80`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/optimization_v2/index.py#L80) thực hiện hàng trăm nghìn phép tra cứu B-tree ngẫu nhiên vào bảng `documents` (chứa JSON metadata lớn) với cache SQLite mặc định chỉ `2 MB`, mất **`121.5s` cold / `104.2s` warm** ([`probe_deep_dive_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_deep_dive_results.json)). Hơn nữa, `PersistentBM25` đã tính `scores` cho **toàn bộ** passages khớp trong 1 lần quét. | Quy định rõ: (1) `case_bm25` có `raw_hits == unique_cases` nên chỉ lấy `limit=100`, không lặp adaptive scan; (2) `passage_bm25` nạp trước bảng `(passage_id -> length)` vào RAM (`~25 MB`) khi mở session, bật read-only `PRAGMA mmap_size/cache_size`, bỏ `JOIN documents` khỏi vòng lặp từ khóa (giảm 50% thời gian với kết quả khớp 100%), duyệt danh sách `scores` đã sắp xếp **1 lần duy nhất** tới `scan_cap=4096`, và chỉ gọi `get_many` cho các passage leads được giữ lại. |
| **`F-PLAN-04`** | **Medium (Blocker)** | **Hàng nghìn passages trùng hệt văn bản giữa các án gây đồng hạng điểm (exact score ties) hàng loạt trên Qdrant (`CE03`):** Thực nghiệm phát hiện các đoạn văn ngắn/khuôn mẫu có mặt giống hệt nhau ở tới **`1,898` án** (`2,459` điểm có cùng `score = 1.0000001` trong top-4096). Qdrant cắt đồng hạng theo UUID5 nội bộ chứ không theo `(passage_id, case_id)`. | Cụ thể hóa quy tắc tie-break Section 5: phát hiện và gắn cờ `boundary_tie_detected = True` khi điểm của hit cuối cùng tại biên `channel_case_budget` hoặc `scan_cap` bằng điểm của hit kế tiếp (trong ngưỡng `tie_atol`), và không tuyên bố tập ID tại biên đồng hạng là duy nhất tuyệt đối khi bị chặn bởi `scan_cap`. |
| **`F-PLAN-05`** | **High (Blocker)** | **Lệch byte offset khi dùng `.casefold()` trực tiếp và mất cụm từ vắt qua heading/đoạn văn (`CE08`):** Trong M2, `48,990` headings và khoảng trắng giữa các đoạn không nằm trong `passages`. Khi quét raw stream ở chế độ `case_insensitive`, các ký tự như `'ß'` (`"Straßenbahn"`), `'İ'`, `'ﬁ'` nở thành 2–3 ký tự sau `.casefold()`, làm lệch toàn bộ `span_bytes` phía sau nếu gọi thẳng `Utf8Map.char_to_byte()` (`CE08`). | Quy định rõ trong Section 6: `search_phrase` quét trên raw stream toàn bộ 7.708 án; chế độ `case_insensitive` bắt buộc dùng bảng ánh xạ từng ký tự `fold_char_idx -> orig_char_idx -> byte_offset` và kiểm chứng bất biến `raw[a:b].decode('utf-8').casefold() == needle.casefold()` cho mọi kết quả. |
| **`F-PLAN-06`** | **High (Blocker)** | **Phân trang `open_source` `64 KiB` với hit nằm giữa parent lớn, biên UTF-8, metadata `quoted/unknown` và độ trễ `PassageReader._case()` (`CE10`):** Quét toàn bộ 7.708 án phát hiện **5 parents** và **13 cửa sổ `prev+parent+next` vượt `64 KiB`** (lớn nhất là `041666.txt` `p000416` dài `85,392` bytes, `p000417` dài `84,205` bytes). Nếu hit nằm giữa `p000417` và trang 1 giao cửa sổ quanh hit, phần chưa giao của parent tách thành **2 khoảng rời nhau** (đầu + đuôi). Ngoài ra, `PassageReader.open_context` hiện mất **`2.46s/lần`** trên `055641.txt` vì tokenize lại toàn bộ án, và `NavigationReader.open_context` làm rơi `paragraph_role` (`quoted`/`unknown`) cùng các đơn vị `unnumbered` xen giữa. | Quy định rõ trong Section 7: (1) cursor lưu danh sách khoảng byte (`requested_spans`, `delivered_spans`, `pending_spans`) thay vì 1 offset đơn; (2) lùi điểm cắt byte về biên UTF-8 codepoint hợp lệ qua `Utf8Map`; (3) cho phép caller truyền `byte_budget <= 65536`; (4) đọc trực tiếp JSON M2 đã xác thực `seal.json` (`<2ms`) thay vì gọi `PassageReader._case()`; (5) giữ đủ `paragraph_role`, `uncertainties`, `observed_marker` và liệt kê rõ các đơn vị `unnumbered` xen giữa trong `components`. |

*(Chi tiết thêm về `F-PLAN-07` — bảo vệ read-only tuyệt đối cho `ledger.sqlite3` / `execution_state.json` của `m3_full_train_20261108_v1` và bổ sung mỏng API đọc bản đồ query case `case_map`/`case_anchors` — được ghi đầy đủ trong [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/findings.json)).*

---

## 3. Phân tách Quyết định Đã Khóa vs Giá trị Đang Đề xuất & Chống Overengineering

### 3.1. Các quyết định đã khóa (Bất biến, không mở lại)
- **Nguồn & Cấu trúc M1/M2:** `7,708` train cases, `382,343` navigation units (`356,973` paragraphs + `25,370` unnumbered), `48,990` headings, `415,693` token-validated passages; M2 seal `0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6`.
- **Embedding & Index:** `Qwen/Qwen3-Embedding-4B` (revision `5cf2132...`, 2560-dim FP32, cap 448 tokens, app `coliee-pipeline-v2-embed-m3-opt-v2` trên L4); BM25 `lexical.sqlite3` (`4.36 GB`, sealed); Qdrant collection `coliee_m3_full_ef2f4d6950a5b9fd` (`415,693` points, verified PASS); cache `6,496` shards `.npz` (`4.47 GB`).
- **Nguyên tắc:** Không re-embed corpus, không sửa code/config/artifact đã niêm phong, không nạp toàn bộ ma trận vector 4.26 GB vào RAM, không dùng gold/nhãn trong runtime.

### 3.2. Các giá trị đang đề xuất trong bản nháp (Starting Engineering Profile)
- `channel_case_budget = 100`, `initial_raw_scan = 256`, `max_raw_scan = 4096`, `final_output_limit = 20`, `rrf_k = 60`, `byte_cap = 64 KiB` (`65,536` bytes), và `6` câu truy vấn thực tế cho bước nghiệm thu S5.
- **Đánh giá của AG:** Các con số này hoàn toàn hợp lý làm cấu hình kỹ thuật khởi đầu sau khi bổ sung các quy tắc chặn biên ở Mục 2. Không cần và không được dùng gold labels ở bước M3 để "tối ưu" các con số này; việc đánh giá độ nhạy/ablation thuộc về giai đoạn Discovery (M5–M6).

### 3.3. Các phần KHÔNG cần sửa / chưa cần làm (Tránh Overengineering)
1. **Không rebuild `lexical.sqlite3` (4.36 GB):** Không cần tạo lại tệp SQLite hay thêm bảng mới trên đĩa; chỉ cần nạp bảng ánh xạ `(id -> length)` vào RAM (`~25 MB`) lúc mở session chỉ đọc và bỏ phép `JOIN documents` trong vòng lặp tính điểm BM25.
2. **Không xây dựng persistent semantic/vector query cache trong M3 baseline:** Giữ đúng thiết kế đơn giản: tái sử dụng vector trong bộ nhớ cho cùng một lệnh `search_corpus`; mỗi lệnh gọi tool có bản ghi ledger riêng.
3. **Không xây dựng bộ phân tích thực thể/citation graph phức tạp cho `search_identity`:** Chỉ cần tra cứu trên trường `metadata` sẵn có của M1 (`case_name`, `neutral_citation`, `court`, `date`) kết hợp tìm kiếm cụm từ/lexical kèm `source_hash` và `span_bytes`.
4. **Không làm tính năng snapshot/restore cho collection Qdrant 48.6 GB:** Đã có `6,496` tệp `.npz` đã verify làm bản lưu trữ chuẩn trên đĩa.

---

## 4. Bằng chứng Thực nghiệm & 11 Counterexamples Đã Kiểm chứng

Toàn bộ các phép thử chỉ đọc đã được chạy và lưu kết quả tại [`pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1):

1. **[`probe_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_results.json) & [`probe_deep_dive_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_deep_dive_results.json):**
   - Đo trực tiếp Qdrant `exact=True` và `exact=False` ở `limit = 20, 256, 1024, 4096`.
   - Ghi nhận lỗi HTTP 500 timeout 60s của Qdrant khi cold scan không có `?timeout=120`, và độ trễ ổn định `2.42s – 3.71s` khi đã có `?timeout=120` và OS cache ấm.
   - Đo độ phân tán shard (shard fan-out): `256` hits chạm `240` shards; `1,024` hits chạm `881` shards; `4,096` hits chạm `2,860` shards; nhưng `100` best hits của `100` unique cases chỉ chạm `97` shards.
   - Đo so sánh `PersistentBM25.search` có `JOIN documents` (`104.22s`) vs bỏ `JOIN documents` (`52.18s`, khớp 100% thứ tự `4,096` hits).
2. **[`probe_mmap_and_open_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/probe_mmap_and_open_results.json):**
   - Quét toàn bộ `7,708` tệp JSON trong `m2_navigation_20261106_v3/sources` trong `17.50s`: xác định chính xác `5` parents và `13` cửa sổ `prev+parent+next` vượt `64 KiB` (lớn nhất: `041666.txt` `p000416` = `85,392` bytes, `p000417` = `84,205` bytes).
   - Phát hiện thực tế trên `055641.txt`: đơn vị đầu tiên là `u000001` (`unnumbered`), đoạn văn đánh số đầu tiên có handle `p000351` (không phải `p000001`), và `PassageReader.open_context` mất `2.4576s` cho 1 lần mở do tokenize lại toàn bộ 1.140 passages.
3. **[`test_plan_counterexamples.py`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/test_plan_counterexamples.py) & [`counterexample_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/counterexample_results.json) (`11/11 PASS`):**
   - `CE01_same_case_flood`: 3 án dài chiếm 1.200 raw hits làm pilot `scan_cap=1024` chỉ trả về 3 unique cases; adaptive expand lên `2,048` lấy đủ 100 unique cases; 5 án chiếm 4.250 raw hits kích hoạt đúng `budget_shortfall=True` ở `4,096`.
   - `CE02_query_case_exclusion`: Lọc hậu kỳ sau `topK=256` trả về `0` kết quả khi `query_case` tự khớp 300 đoạn đầu; lọc trước `topK` trả đủ kết quả và mẫu số hợp lệ là `N - 1`.
   - `CE03_dense_ties`: 150 ứng viên đồng điểm cosine `0.85` cắt qua ranh giới `100` unique cases kích hoạt `boundary_tie_detected=True`.
   - `CE04_cached_query_vector_reuse`: Tái sử dụng vector trong 5 vòng mở rộng của cùng 1 request chỉ tốn 1 RPC; khóa cache tách biệt `real_modal` và `simulated`.
   - `CE05_rrf_channel_cap_bug`: Chứng minh lỗi đảo hạng giữa `CASE_X.txt` và `CASE_Y.txt` nếu không cắt `rank_cases(hits, limit=100)` trước khi gọi `fuse_case_ranks`.
   - `CE06_source_and_db_drift`: Chứng minh điểm mù khi 1 điểm bị sửa vector làm tụt hạng ngoài top-$K$ trả về mà tổng số điểm `415,693` không đổi.
   - `CE07_simulated_to_real`: Chặn dùng receipt/state `simulated` cho phiên `real_modal` và bảo vệ read-only thư mục ingestion.
   - `CE08_phrase_casefold_offset`: Chứng minh cụm từ vắt qua heading bị mất trên bảng `passages` và lỗi lệch byte span khi gặp ký tự `'ß'` (`"Straßenbahn"`) nếu không có bảng ánh xạ `fold_to_orig_char`.
   - `CE09_case_bm25_no_pinpoint`: Ứng viên chỉ khớp ở `case_bm25` trả `matched_passages=[]`, không bịa `p000001`.
   - `CE10_utf8_and_interval_pagination`: Cắt byte ở vị trí lẻ `51` trên chuỗi tiếng Pháp `'é' * 50` làm nổ `Utf8Map.byte_to_char` nếu không lùi về biên `50`; mở phần giữa của parent `100,000` bytes để lại 2 khoảng pending rời nhau `[[0, 20000], [85536, 100000]]`.
   - `CE11_m4_token_budget_deferred`: Chứng minh `64 KiB` tương đương `~16,000` tokens nên chỉ là trần vận chuyển host, cần cho phép caller truyền `byte_budget` nhỏ hơn.

---

## 5. Các Quyết định Cần Main Phân xử & Chốt ở Mốc S0

1. **Chính sách quét Qdrant `exact=True` và xác thực shard (`F-PLAN-02`):**
   - Chốt truyền `?timeout=120` vào Qdrant query API.
   - Chốt việc truy vấn Qdrant `exact=True` (1 lần ở `4096` hoặc 2 nấc `256 -> 4096`) rồi cắt cửa sổ adaptive trong RAM, và chỉ xác thực vector từ `ReadonlyCache` cho các passage leads được giữ lại của `<= 100` unique cases (ví dụ tối đa `max_leads_per_case = 3` passages/case) thay vì toàn bộ `4,096` raw hits.
2. **Chính sách cắt trần `100` unique cases/kênh trước RRF và cấu trúc response (`F-PLAN-01`):**
   - Chốt mỗi kênh chỉ đóng góp tối đa `100` unique cases vào `fuse_case_ranks`, đồng thời giữ danh sách `100` unique cases của từng kênh trong response để phục vụ kiểm toán recall trước/sau cap.
3. **Tối ưu đọc `PersistentBM25` không sửa file index (`F-PLAN-03`):**
   - Chốt nạp bảng `(passage_id -> length)` vào RAM khi mở session chỉ đọc và bỏ `JOIN documents` trong vòng lặp tính điểm BM25.
4. **Hợp đồng cursor khoảng byte (`interval-set cursor`) và fast M2 load cho `open_source` (`F-PLAN-06`):**
   - Chốt biểu diễn `delivered_spans` / `pending_spans` dạng danh sách khoảng `[start_byte, end_byte]`, lùi biên cắt về UTF-8 codepoint hợp lệ, trả đủ metadata `paragraph_role`/`uncertainties` + `unnumbered` xen giữa, và đọc thẳng JSON M2 đã kiểm `seal.json` thay vì gọi `PassageReader._case()` trong đường nóng.
5. **Quy tắc chọn trước 6 câu truy vấn thực tế ở S5 và tách thư mục runtime (`F-PLAN-07`):**
   - Chốt ghi mọi log/ledger của `full_search` ra ngoài `m3_full_train_20261108_v1`, và sinh 6 câu truy vấn kiểm thử S5 một cách tất định từ nguồn query cases theo seed cố định trước khi chạy Modal.

---

## 6. Phần Đã Đủ Bằng chứng vs Phần Chưa Đủ Bằng chứng

- **Đã đủ bằng chứng thực nghiệm:**
  - Tính toàn vẹn của `lexical.sqlite3` (`4.36 GB`), `6,496` shards vector cache (`4.47 GB`) và Qdrant collection `coliee_m3_full_ef2f4d6950a5b9fd` (`415,693` points).
  - Tính khả thi về độ trễ và bộ nhớ của `exact=True` trên Qdrant (`~2.4s – 3.7s` khi warm, RAM bounded) và tính khả thi của việc đối chiếu exact reference bằng streaming dot-product trên `6,496` shards `.npz` mà không cần nạp ma trận 4.26 GB vào RAM.
  - Phân phối thực tế của các trường hợp biên trong tập train (`671` án có `>100` passages, `2,459` điểm đồng hạng cosine, `13` cửa sổ ngữ cảnh vượt `64 KiB`).
- **Chưa được chứng minh ở bước này (và không được suy diễn quá mức):**
  - Chưa triển khai code `pipeline_v2/full_search/` và chưa chạy thử nghiệm end-to-end 6 câu truy vấn thực tế qua Modal (thuộc mốc S1–S5 sau khi Main chốt S0).
  - **Không suy diễn chất lượng COLIEE F1 hay độ chính xác dự đoán `noticed` từ thiết kế kỹ thuật M3:** Việc truy hồi đúng ứng viên và mở đúng nguồn nguyên văn chỉ là điều kiện cần về hạ tầng; chất lượng phát hiện quan hệ trích dẫn pháp lý phụ thuộc vào bộ điều phối M4, chiến lược đọc nguồn và bộ chọn cuối (M5–M7).
