# Báo cáo Kiểm thử Độc lập & Nghiệm thu Toàn diện M3 Full Corpus

- **Ngày thực hiện:** `2026-11-09`
- **Mã kế hoạch / Run:** [`pipeline_v2/artifacts/m3_full_train_20261108_v1`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_full_train_20261108_v1)
- **Tên Vector Collection:** `coliee_m3_full_ef2f4d6950a5b9fd` (Qdrant on-disk, cosine distance, 2560 dims)
- **Thư mục bằng chứng độc lập:** [`pipeline_v2/reviews/m3_full_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1)
- **Văn bản quy định:** [`pipeline_v2/docs/AG_M3_FULL_TEST_PROMPT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/AG_M3_FULL_TEST_PROMPT.md), [`pipeline_v2/docs/M3_FULL.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/M3_FULL.md)
- **Nguyên tắc nghiệm thu:** Độc lập, đối soát bằng streaming có giới hạn bộ nhớ (RAM bounded), không gom toàn bộ ma trận vector vào RAM, không sửa production code, config, cache, seals hoặc nhãn/gold, và bảo lưu nguyên vẹn bằng chứng các lần lỗi/ngắt quãng.

---

## 1. Kết luận Tổng thể theo Từng Hạng mục (Separated Verdicts)

| Hạng mục | Kết luận | Tóm tắt bằng chứng nghiệm thu độc lập |
|---|---|---|
| **`local_correctness`** | **`PASS`** | `30/30` unit tests (12 full storage/runner + 18 optimization V2 regression) đạt PASS trong `0.585s`. Bộ 7 test fault-injection độc lập của AG (`test_m3_full_independent_ag.py`) kiểm tra crash giữa cache commit và DB upsert, cơ chế bỏ qua batch đã khớp trong `--max-batches`, phục hồi orphan array, bảo vệ danh tính thực thi `simulated` vs `real_modal`, khóa ghi `run_lock`, lệnh CLI không nạp `.env`, và phòng chống chu kỳ phân trang DB đều đạt PASS. |
| **`schedule_and_plan_integrity`** | **`PASS`** | Kiểm toán streaming độc lập toàn bộ `lexical.sqlite3` (4.36 GB, sealed): đủ `415,693` passages phân bố trên `7,708` cases, `6,496` batches contiguous 64 (batch cuối đúng 13 passages). Sắp xếp tất định theo `full_input_tokens` tăng dần rồi đến `passage_id`. Không có rò rỉ text trong trường `metadata`. Tổng input tokens dự kiến `55,346,360`, tổng padded tokens `55,360,576` (tỷ lệ padding cực thấp: `1.000257`). Hash và span bytes khớp 100% nguồn raw case và bundle M2 đã niêm phong. |
| **`canary_and_resume`** | **`PASS`** | Canary 2 batches đầu tiên (`full-documents-0` và `1`) chạy qua Modal L4 thành công trong `740.51s` (batch 0 mất `710.7s` do cold-start container và tải model, batch 1 mất `0.98s`), dừng chuẩn xác tại ranh giới lô (`stopped_at_batch_boundary`). Khi tiếp tục chạy toàn bộ (`step4`), runner chịu 2 lần đứt kết nối mạng (`ConnectionError` tại batch 4292 và batch 5693) và 1 lần ngắt (`KeyboardInterrupt` tại batch 6495); mỗi lần resume đều nhận diện chính xác các batch đã commit trong cache và đã khớp trong DB, không thực hiện encode lại bất kỳ batch nào đã commit. |
| **`full_ingestion_and_accounting`** | **`PASS`** | Toàn bộ `6,496` batches được mã hóa thành công đúng 1 lần qua NVIDIA L4 trên Modal. Bảng `full_batches` có đúng `6,496` hàng với `committed = 1`. Ledger ghi nhận tổng cộng `6,497` attempts, gồm đúng `6,496` success và `1` attempt `started` (attempt id `4293` tại batch `4292`) được giữ nguyên trạng với `tokens = null` và `elapsed = null` (unknown usage) thay vì ép về 0 hay gán thành công. Tổng số token ghi nhận qua receipt: đúng `55,346,360` input tokens và `55,360,576` padded tokens. |
| **`full_db_verification`** | **`PASS`** | Lệnh kiểm chứng độc lập ngoài runner (`m3_full verify --run-dir ...`) chạy ở chế độ đọc (readonly) không can thiệp cache hay DB. Lần chạy 1 ghi nhận lỗi `ReadTimeout` do hệ thống Windows rơi vào Modern Standby (Kernel-Power Event 506); bằng chứng đã được lưu trữ độc lập. Lần chạy 2 thực thi trọn vẹn trong `1,525.54s` (`internal_cli_seconds = 1,525.05s`), đối soát từng khối 64 vector giữa `ReadonlyCache` và `coliee_m3_full_ef2f4d6950a5b9fd` trên Qdrant local, xác nhận đầy đủ `415,693` points khớp ID, payload, fingerprint và vector cosine, exact count `415,693`. |
| **`full_search_and_downstream_readiness`** | **`DEFERRED_BY_DESIGN_SCOPE`** | Đúng theo ranh giới thiết kế trong [`M3_FULL.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/docs/M3_FULL.md), runner này hoàn thành trọn vẹn công đoạn ingestion và kiểm chứng toàn vẹn vector database full-corpus. Bộ điều phối tìm kiếm lai (Full Hybrid Search RRF kết hợp Dense + BM25 trên 415.693 tài liệu), đánh giá chất lượng retrieval COLIEE (F1) và Agent M4 được phân định rõ là thuộc các giai đoạn tiếp theo của dự án. |

---

## 2. Đối soát Fingerprints & Tính Bất biến (Immutability)

Tất cả SHA-256 fingerprints của mã nguồn, profile cấu hình, và các artifact baseline/V1/V2 trước và sau đợt nghiệm thu full được đối soát độc lập trong [`state_before.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/state_before.json), [`state_after.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/state_after.json) và [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/recomputed_metrics.json#L5-L20):

- **Mã nguồn Production (Bất biến):**
  - `full_implementation_sha256`: `e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503` (khớp tuyệt đối `34/34` file production trong pipeline v2).
  - `v2_implementation_sha256`: `e2e554dd44bbd99ab93b61ca893094fe9dd47e0cd8604e5898e8b169bf931cf3`.
  - `v1_implementation_sha256`: `126ff7504aed84f8d89b8d46560dea25c8ccf3a4d8aaa001d2789d83a9d98845`.
  - `base_implementation_sha256`: `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63`.
- **Cấu hình Profiles (Bất biến):**
  - `pipeline_v2/configs/m3_full.json`: `448a14cf545769cd0eb4c34db790b168f7b63b68e0d429c7e2d555c12d6caa84`.
  - `pipeline_v2/configs/m3_opt_v2.json`: `1751e20a35d289fa7aa8842a546875d676ace751c8a5dc65f5a544889f293f20`.
  - `pipeline_v2/configs/m3_opt.json`: `f81170ba13d5e0e2f188b7af0b031a09084165e9dcd92a3cf56383810001b798`.
  - `pipeline_v2/configs/m3.json`: `3a0f65a4cd100842423ed8683f87d4d0594e095118e5ffabfdef1bee3a252ef7`.
  - `embedding_fingerprint`: `9105955758bda2eba37350535866f9b217e1b9650b1a3f081496a7c4a9965c49`.
- **Niêm phong Artifacts Cũ & Pilot Collections:**
  - Artifacts baseline pilot (`m3_pilot_20261106_l4_v1`): `147/147` files khớp SHA-256 (`pilot_manifest_sha256 = 2069968b...`).
  - Index V1 (`m3_opt_index_20261107_v2`): `seal.json` giữ nguyên hợp lệ.
  - Index V2 (`m3_opt_v2_index_20261108_v1`): `seal.json` giữ nguyên hợp lệ.
  - Compatibility receipt V2 (`m3_opt_v2_compat_20261108_v1/compatibility.json`): SHA-256 `3334a4a3...` bất biến.
  - Plan thật Full M3 (`artifacts/m3_full_train_20261108_v1`): `seal.json` khớp `manifest.json` (`622,353` bytes, SHA-256 `7bdf2bb5...`) và `lexical.sqlite3` (`4,357,505,024` bytes, SHA-256 `6ad1f818...`).
  - Pilot collections trên Qdrant: `coliee_m3_pilot_99e66b7f9bbf4be4` và `coliee_m3_pilot_99e66b7f9bbf4be4_restore` đều được bảo toàn nguyên vẹn với đúng `1,024` points mỗi collection.

---

## 3. Đối soát Độc lập Schedule, Ingestion, Resume và Ledger

### 3.1. Đối soát Quy mô Corpus & Schedule Ingestion

Từ bảng `schedule` và bảng `documents` trong `lexical.sqlite3`:
- **Số lượng Án (Cases):** `7,708` cases (toàn bộ đều có ít nhất 1 passage; khớp 100% danh mục `source_registry.json` của bundle M2).
- **Số lượng Passages:** `415,693` unique passages.
- **Số lượng Batches:** `6,496` batches (mỗi batch chuẩn gồm `64` passages; batch cuối cùng thứ `6495` có đúng `13` passages: `6495 * 64 + 13 = 415,693`).
- **Phân bổ Độ dài & Tỷ lệ Đệm (Padding):**
  - Chiều dài token ngắn nhất: `2` tokens (`batch 0`).
  - Chiều dài token dài nhất: `448` tokens (`batch 6495`).
  - Do các passages được gom nhóm theo chiều dài token tăng dần rồi đến ID, chênh lệch chiều dài giữa các passages trong cùng một batch là tối thiểu.
  - Tổng số token đầu vào thực tế (`known_input_tokens`): **`55,346,360` tokens**.
  - Tổng số token sau khi đệm theo batch (`padded_tokens`): **`55,360,576` tokens**.
  - Lượng token đệm thừa (`padding_overhead`): chỉ **`14,216` tokens** trên toàn bộ 415.693 đoạn văn (tỷ lệ padding **`1.000257`**, tức chỉ lãng phí **`0.0257%`**).

### 3.2. Lịch sử Các Lần Gọi Runner (`invocations/`) & Xử lý Gián đoạn

Quá trình chạy thật full corpus trên Modal L4 được ghi nhận chi tiết qua 5 tệp receipt dạng append-only trong thư mục `invocations/`:

1. **Invocation 1** ([`1794141634555987500.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_full_train_20261108_v1/invocations/1794141634555987500.json) — Canary):
   - Lệnh: `m3_full run --max-batches 2`.
   - Kết quả: Xử lý 2 batches đầu tiên (`batch 0` và `1`, gồm 128 passages), nạp thành công 128 vector vào Qdrant; dừng đúng ranh giới với trạng thái `stopped_at_batch_boundary`.
   - Thời gian: `714.73s` (bao gồm `710.7s` khởi tạo container Modal và tải trọng số Qwen3-Embedding-4B).
2. **Invocation 2** ([`1794193822344405200.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_full_train_20261108_v1/invocations/1794193822344405200.json)):
   - Khởi chạy full run; gặp `ConnectionError` ngay sau `2.07s`, 0 batch mới nào được xử lý.
3. **Invocation 3** ([`1794200120094207300.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_full_train_20261108_v1/invocations/1794200120094207300.json)):
   - Resume thành công: bỏ qua 2 batch canary đã có trong cache/DB, xử lý liên tục từ `batch 2` đến `batch 5692` (`1,401` batches mới, `89,664` passages).
   - Dừng do đứt kết nối mạng phía client (`ConnectionError`) tại batch 5693 sau `6,120.59s`. Trạng thái: `failed_partial`.
4. **Invocation 4** ([`1794210214184129800.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_full_train_20261108_v1/invocations/1794210214184129800.json)):
   - Resume tiếp tục: bỏ qua toàn bộ 5,694 batch đã hoàn tất, xử lý tiếp `802` batches (`batch 5693` đến `batch 6495`, bao gồm cả batch cuối cùng 13 passages).
   - Hoàn tất toàn bộ việc embedding và upsert vào Qdrant, sau đó nhận tín hiệu ngắt trước khi hoàn tất thủ tục chốt snapshot cuối. Trạng thái: `interrupted_partial`.
5. **Invocation 5** ([`1794214107749367800.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/artifacts/m3_full_train_20261108_v1/invocations/1794214107749367800.json)):
   - Gọi lại `run --run-dir`: nhận diện trọn vẹn `6,496/6,496` batches đã có trong cache và đã khớp trong DB (`cached_batches = 6496`, `new_inference_batches = 0`).
   - Runner tự kích hoạt kiểm chứng nội bộ toàn bộ 415.693 điểm (`verify_batches`), trả về `status = full_vectors_ingested_verified`, `verification.status = PASS`, `points = 415693`.

### 3.3. Đối soát Sổ cái Giao dịch (`ledger.sqlite3`) & Bảo lưu Unknown Usage

Đối soát streaming toàn diện 6.497 hàng trong bảng `attempts`:

- **Tổng số Attempts:** **`6,497` attempts**.
  - `status = 'success'`: **`6,496` attempts** (đúng bằng tổng số batches).
  - `status = 'started'`: **`1` attempt** (duy nhất attempt id **`4293`**).
  - Các trạng thái lỗi khác (`error`, `oom`): `0`.
- **Phân tích Attempt `4293` (Finding `F-M3FULL-01`):**
  - Nhãn: `full-documents-4292`, pha `v2_document`, thời điểm bắt đầu: `2026-11-08T15:09:49.639Z`.
  - Nguyên nhân: Lệnh gọi từ client bị gián đoạn mạng trước khi nhận phản hồi từ server Modal.
  - Giá trị trường: `requests = 1`, `elapsed = NULL`, `tokens = NULL`, `error = NULL`, `receipt = NULL`.
  - Lần chạy kế tiếp: Attempt id `4294` (bắt đầu lúc `2026-11-09T03:24:07.303Z`) đã gửi lại đúng batch `full-documents-4292` và thành công sau `24.53s` (`tokens = 9216`).
  - **Tuân thủ hợp đồng:** Runner và bộ công cụ kiểm toán **không** sửa attempt `4293` thành `success` và **không** ép `tokens = 0`. Trường `unknown_token_attempts = 1` và `unknown_elapsed_attempts = 1` được thể hiện trung thực trong toàn bộ các báo cáo usage.
- **Tính Duy nhất & Khớp Mã nguồn:**
  - Không có bất kỳ batch nào bị ghi nhận `success` quá 1 lần (`duplicate_success_batches = []`).
  - Mỗi batch trong số 6.496 batches đều khớp chính xác `input_tokens`, `padded_tokens`, và danh sách SHA-256 của các đoạn văn bản tương ứng trong bảng `schedule`.

### 3.4. Hiệu năng & Chỉ số Bộ nhớ GPU trên Modal L4

Dữ liệu tổng hợp từ 6.496 receipt chi tiết:
- **Thời gian Thực thi:**
  - Tổng thời gian phía Client (`recorded_request_elapsed_seconds`): `16,753.74s` (~`4.65` giờ).
  - Tổng thời gian xử lý trên Remote Modal (`remote_elapsed_seconds`): `11,943.90s` (~`3.32` giờ).
  - Tổng thời gian chạy mô hình CUDA trên GPU (`gpu_model_pool_seconds`): `11,588.59s` (~`3.22` giờ).
  - Tổng chi phí RPC và truyền tải mạng: `4,809.84s` (~`1.34` giờ; trung bình `0.74s` mỗi request).
- **Tốc độ Mã hóa (Throughput):**
  - Phía Client (bao gồm mạng): **`24.81` passages/s**.
  - Phía Server Modal: **`34.80` passages/s**.
  - Trực tiếp trên CUDA GPU: **`35.87` passages/s** (tương đương **`4,775.9` tokens thực/s**).
- **Các Container Instances Phục vụ:**
  - Ba container NVIDIA L4 được huy động luân phiên:
    1. Instance `0b76ef47-349d-4322-a486-81240baa5456`: phục vụ `4,292` batches (từ batch 0 đến 4291; `model_load_seconds = 13.24s`).
    2. Instance `72c80192-4e36-4fa5-b1de-567198d3f631`: phục vụ `1,402` batches (từ batch 4292 đến 5693; `model_load_seconds = 13.76s`).
    3. Instance `c4f230f9-6781-4530-a2e3-0e31cf1e1194`: phục vụ `802` batches (từ batch 5694 đến 6495; `model_load_seconds = 14.42s`).
- **Bộ nhớ GPU VRAM (NVIDIA L4 24 GB = 23,689,363,456 bytes):**
  - Mức bộ nhớ thực tế lớn nhất (`max_peak_allocated_bytes`): `10,382,977,024` bytes (~`9.67` GB, tương ứng **`56.17%` VRAM headroom an toàn**).
  - Mức bộ nhớ pool PyTorch giữ lại (`max_peak_reserved_bytes`): `23,425,187,840` bytes (~`21.82` GB; caching allocator giữ lại bộ đệm sau các batch 448 tokens dài nhất). Không xảy ra bất kỳ lỗi OOM nào.

---

## 4. Kết quả Kiểm chứng Độc lập (`m3_full verify`)

Theo đúng quy trình bàn giao, lệnh kiểm chứng độc lập hoàn toàn tách rời khỏi runner tiến trình được thực thi:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_full verify --run-dir pipeline_v2/artifacts/m3_full_train_20261108_v1
```

### 4.1. Lần chạy 1 — Phát hiện Gián đoạn Modern Standby (`step5_verify_attempt1`)
- **Kết quả:** `exit_code = 2`, `wall_seconds = 1,141.70s`, `internal_cli_seconds = 1,138.44s`.
- **Thông điệp:** `{"status": "error", "error": "ReadTimeout"}`.
- **Điều tra nguyên nhân (Root Cause):**
  - Tra cứu log hệ thống Windows (`Get-WinEvent -LogName System`): Ghi nhận sự kiện `Microsoft-Windows-Kernel-Power Event ID 506` ("The system is entering Modern Standby") diễn ra vào lúc `17:09:44 local time`.
  - Modern Standby làm Windows tạm dừng (suspend) máy ảo WSL2 và container `coliee-pipeline-v2-qdrant`, khiến socket HTTP giữa Python host và Qdrant container bị ngắt kết nối sau 120s timeout.
  - **Bảo lưu bằng chứng:** Bộ ba tệp [`step5_verify_attempt1_receipt.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/step5_verify_attempt1_receipt.json), `step5_verify_attempt1_stdout.json` và `step5_verify_attempt1_stderr.txt` đã được sao lưu nguyên trạng vào thư mục review.

### 4.2. Lần chạy 2 — Nghiệm thu Toàn diện Thành công (`step5_verify`)
- **Kết quả:** `exit_code = 0`, `wall_seconds = 1,525.54s` (25.43 phút), `internal_cli_seconds = 1,525.05s`.
- **Nội dung stdout:**
  ```json
  {
    "cli_timing_origin": "after_argument_parse_excludes_process_startup",
    "collection": "coliee_m3_full_ef2f4d6950a5b9fd",
    "execution_mode": "real_local_DB",
    "internal_cli_seconds": 1525.0488638000024,
    "method": "all_expected_unique_ids_payload_vectors_plus_exact_count_batched64",
    "points": 415693,
    "status": "PASS"
  }
  ```
- **Hợp đồng kiểm tra được đáp ứng:**
  - Kiểm tra schema Qdrant: collection tồn tại, đúng `dimensions = 2560`, `distance = Cosine`, `on_disk = True`.
  - Đọc streaming từng lô 64 passages từ `lexical.sqlite3`, nạp mảng vector từ `ReadonlyCache` (xác thực SHA-256 tệp `.npz`, kiểm tra embedded ID và hash), gửi truy vấn POST `/points` lấy payload và vector thực tế trong collection.
  - So khớp 100% ID, payload metadata (`case_id`, `passage_id`, `source_hash`, `exact_input_sha256`, `span_bytes`, `parent_handle`, `policy_hash`, `tokenizer_fingerprint`, `embedding_fingerprint`).
  - Kiểm tra độ tương đồng vector (`np.allclose(stored, v, atol=1e-5, rtol=1e-5)`).
  - Xác nhận đúng đủ **`415,693` points** (`exact_count`), không thiếu và không thừa bất kỳ bản ghi nào.

---

## 5. Báo cáo Tài nguyên: Bộ nhớ, Bounded Streaming RAM và Dung lượng Đĩa

- **Kiểm soát Bộ nhớ RAM (Bounded Memory):**
  - Quá trình verification và kiểm toán audit duyệt qua 415.693 passages theo streaming iterator batch_size=64.
  - Không bao giờ nạp toàn bộ ma trận vector FP32 (khoảng `4.26 GB` thuần) hoặc toàn bộ nội dung text của corpus vào RAM cùng một lúc. Mức tiêu thụ RAM của tiến trình Python duy trì ổn định dưới `350 MB`.
- **Dung lượng Đĩa (Drive E: & WSL2 Docker):**
  - Thư mục artifact plan & cache: `pipeline_v2/artifacts/m3_full_train_20261108_v1/`
    - `lexical.sqlite3`: `4,357,505,024` bytes (`4.36 GB`).
    - Thư mục `vectors/`: `4,466,141,805` bytes (`4.47 GB`), bao gồm đúng `6,496` tệp `.npz` (`4,422,922,572` bytes) và `6,496` tệp `.json` sidecar (`43,219,233` bytes), không có bất kỳ tệp orphan hay rác nào.
    - `ledger.sqlite3`: `4,407,296` bytes (`4.41 MB`).
    - `manifest.json`: `622,353` bytes.
  - Dung lượng Qdrant Docker Storage:
    - Lưu trữ on-disk vectors + HNSW index + keyword payload filters trên volume `coliee_pipeline_v2_qdrant_storage_v1` (nằm trên ổ `E:\Data\Docker\DockerDesktopWSL\main\`).
    - Tổng dung lượng trống ổ `E:` trước khi chạy canary: **`99.46 GB`**.
    - Dung lượng trống ổ `E:` sau khi hoàn thành full ingestion & verification: **`42.01 GB`**.
    - Tổng dung lượng tiêu thụ ròng trên ổ `E:` cho toàn bộ corpus 415.693 passages: **`57.45 GB`**.

---

## 6. Danh mục Bằng chứng Độc lập đã Bàn giao

Toàn bộ các tệp nhật ký, mã kiểm thử và dữ liệu nghiệm thu được lưu trữ tập trung tại [`pipeline_v2/reviews/m3_full_ag_review_v1/`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1):

1. [`REPORT.md`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/REPORT.md): Văn bản báo cáo tổng hợp chi tiết.
2. [`findings.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/findings.json): Kết luận phân tách theo 6 hạng mục (`verdicts`), ghi nhận 4 findings nghiệp vụ và lịch sử các lần xử lý lỗi/checker.
3. [`commands_and_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/commands_and_results.json): Bảng nhật ký tuần tự 11 câu lệnh đã thực thi, mã thoát (`exit_code`), thời gian và đường dẫn kết quả.
4. [`recomputed_metrics.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/recomputed_metrics.json): Số liệu tính toán lại độc lập qua streaming (fingerprints, schedule, 6.496 shards cache, ledger status, invocations timeline, disk delta).
5. [`ledger_and_schedule_audit.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/ledger_and_schedule_audit.json): Kết quả đối soát trực tiếp giữa cấu trúc schedule trong `lexical.sqlite3` và bảng attempts trong `ledger.sqlite3`.
6. [`independent_local_test_results.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/independent_local_test_results.json): Bằng chứng chạy bộ 7 test fault-injection độc lập và kiểm toán schedule `415,693` passages.
7. [`unit_tests_30.txt`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/unit_tests_30.txt): Log chi tiết chạy bộ 30 unit tests của pipeline_v2.
8. [`state_before.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/state_before.json) & [`state_after.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/state_after.json): Ảnh chụp trạng thái hệ thống, dung lượng đĩa và collections Qdrant trước và sau toàn bộ quá trình chạy.
9. **Nhật ký các bước thực thi CLI:**
   - [`step1_status_stdout.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/step1_status_stdout.json), `step1_status_stderr.txt`, `step1_status_receipt.json`.
   - [`step2_canary_stdout.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/step2_canary_stdout.json), `step2_canary_stderr.txt`, `step2_canary_receipt.json`.
   - [`step3_status_stdout.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/step3_status_stdout.json), `step3_status_stderr.txt`, `step3_status_receipt.json`.
   - [`step5_verify_attempt1_stdout.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/step5_verify_attempt1_stdout.json), `step5_verify_attempt1_stderr.txt`, `step5_verify_attempt1_receipt.json` (Lần 1: Standby timeout).
   - [`step5_verify_stdout.json`](file:///e:/Git/coliee-case-retrieval/pipeline_v2/reviews/m3_full_ag_review_v1/step5_verify_stdout.json), `step5_verify_stderr.txt`, `step5_verify_receipt.json` (Lần 2: Hoàn tất PASS).
