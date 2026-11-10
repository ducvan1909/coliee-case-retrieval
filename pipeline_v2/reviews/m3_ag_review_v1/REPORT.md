# Báo cáo kiểm thử độc lập & thực thi M3 Pilot (L4) — AG Review v1

- **Ngày thực hiện:** 2026-11-06
- **Repo / Checkout:** `E:/Git/coliee-case-retrieval`
- **Thư mục review:** `pipeline_v2/reviews/m3_ag_review_v1/`
- **Run pilot hiện hành:** `pipeline_v2/artifacts/m3_pilot_20261106_l4_v1/`
- **Phạm vi sửa đổi của AG:** Chỉ tạo test/script/evidence/report trong `pipeline_v2/reviews/m3_ag_review_v1/` và chạy CLI chính thức ghi kết quả vào `pipeline_v2/artifacts/m3_pilot_20261106_l4_v1/`. **Không sửa bất kỳ dòng code production, config, manifest hoặc bundle M0–M2 nào.** Không truy cập gold/labels/test sources, không in credentials và không chạy full corpus.

---

## 1. Kết luận theo hai trục độc lập

| Trục đánh giá | Kết luận | Giải thích |
|---|---|---|
| `code_review` | `pass_with_documented_limits` | Toàn bộ 8 nhóm bất biến M3 được xác minh độc lập từ code thực, dữ liệu gốc M2/raw và bộ test độc lập của AG (`9/9 PASS`) cùng bộ unit test hiện có (`51/51 PASS`). Không có lỗi chặn hoặc lỗi production cần sửa cho phạm vi pilot. |
| `real_pilot_execution` | `pass_with_documented_limits` | Toàn bộ 1.024 passages (64 batches × 16) từ 916 án đã được embed thực tế trên GPU **NVIDIA L4** (Modal), kiểm tra đầy đủ `stop-after-batches 1` → `resume` (không embed lại batch đã commit), nạp Qdrant v1.20.0 (`1.024 points`), kiểm `verify --restore-test` (`coliee_m3_pilot_99e66b7f9bbf4be4_restore`), `stop/start` container Qdrant và `verify` lại sau khởi động lại, chạy 3 truy vấn `m3 search` (gồm loại trừ `--query-case`), `m3 literal` và `m3 open`. |

---

## 2. Dấu vân tay (Fingerprints), Hashes & Môi trường thực tế

- **Aggregate M3 implementation SHA-256:** `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63`
  - `pipeline_v2/m3.py`: `20a338b562a0b918f59efd80be44d3855fd530786c0efa00133cbfb9dadd00f7`
  - `pipeline_v2/retrieval/__init__.py`: `500a0e5966957f75abaaa2fec71954162c067d54ee9a50fdc0e3e7a289455225`
  - `pipeline_v2/retrieval/bm25.py`: `92ec81469a8574c4724e890daada3983cdd40a22915f31cc48b3e37e85f6cfa5`
  - `pipeline_v2/retrieval/cache.py`: `f79f6b510708737472621c62fdd215556eb923846f0fb91452ede2cbb3579759`
  - `pipeline_v2/retrieval/common.py`: `ea18ae1f7201a7578d7a318085a1d5c5be464a4e946ba64afbb9839bfb60de00`
  - `pipeline_v2/retrieval/corpus.py`: `b02a3680602f186aee56c7f301612a3a35d75f56d921a52fdfcb7baed1155e72`
  - `pipeline_v2/retrieval/pilot.py`: `d2c3cebf651b0e81f8240fbaf05d90c33ddc41649a1f1e8a8d5eb64cc9a87bea`
  - `pipeline_v2/retrieval/qdrant.py`: `daf48cc546053ada9938051e8262f3a18d97889987a7725db4da39d37cbf6e51`
  - `pipeline_v2/retrieval/runtime.py`: `4a2eebd1d88b1f9e3c0ebdaca52cc1064989bdf52664867cadb7e01174d569e1`
  - `pipeline_v2/deployments/modal/engine.py`: `1ec94f4dcd666bd3a368bb36b59b62ec524bcc1d6ccd543f70c3aeda11b3e19c`
  - `pipeline_v2/deployments/modal/qwen3_embed.py`: `a93350fb45b914e2cf6e64c4b87a053cd1766d0c9293a9be560729a3e1740633`
- **Helper `pipeline_v2/deploy_modal.py` SHA-256:** `bb42e06aa7302594b088285beb29120bdf035f1a10de602642712b5679a299a0`
- **Embedding fingerprint:** `d945329fa49e2f4b4f83d530df03fb4897babd5345562cbeaebd3b21499649bf`
- **Pilot manifest SHA-256 (`manifest.sha256.json`):** `2069968b6735e291afc81c7eb615121fc4da1c86dce566f46ebe5bfddadd18db`
- **Accepted M2 passages seal SHA-256:** `0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6` (`pipeline_v2/artifacts/m2_passages_20261106_v1`)
- **M2 navigation seal SHA-256:** `43ca58589704e94754be3ed6b343ffa73f806a0c757c752abffa1fdb4942234c` (`pipeline_v2/artifacts/m2_navigation_20261106_v3`)
- **Tokenizer lock SHA-256 / Fingerprint:** `2ce6b78aefd3415e1a06ab1fc5fe3e88b3a565e175227b7ee055054db3382dd8` / `1588b3e70f144e9ced344f840fdd68ab75034ecb8f8bb573a74dcd0bcaa29885`
- **Model / Revision:** `Qwen/Qwen3-Embedding-4B` @ `5cf2132abc99cad020ac570b19d031efec650f2b` (`torch.bfloat16` weights, `float32` 2.560-d L2-normalized outputs)
- **Modal Runtime:**
  - App: `coliee-pipeline-v2-embed-m3-pilot-v1` (`Embedder`)
  - Volume: `coliee-pipeline-v2-qwen3-4b-cache-v1`
  - GPU thực tế: `NVIDIA L4` (preflight instance `5aa40e33-c0b8-4c33-b654-c0f0d91297e1`; pilot run & search instance `1e76ed58-8f38-47ae-8d37-3d5a9f8c6ca3`)
  - Package versions trên Modal: `torch==2.8.0`, `transformers==4.57.1`, `tokenizers==0.22.2`, `modal==1.5.3`, `numpy==2.5.4`, `huggingface_hub==0.36.2`, `safetensors==0.8.0`
- **Qdrant Docker Local:**
  - Docker Client / Engine: `28.5.1` (Docker Desktop `4.49.0`, Linux containers)
  - Compose project / container: `coliee-pipeline-v2` / `coliee-pipeline-v2-qdrant` (`f185ac853749`)
  - Image & Digest: `qdrant/qdrant:v1.20.0` (`qdrant/qdrant@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2`)
  - Server version / commit: `1.20.0` / `222b2e44ab1c3f17e8246396ead6558e45041df7`
  - Named volumes: `coliee_pipeline_v2_qdrant_storage_v1`, `coliee_pipeline_v2_qdrant_snapshots_v1`
  - Primary collection: `coliee_m3_pilot_99e66b7f9bbf4be4` (`1.024 points`)
  - Restored collection: `coliee_m3_pilot_99e66b7f9bbf4be4_restore` (`1.024 points`, snapshot `coliee_m3_pilot_99e66b7f9bbf4be4-7169271234645582-2026-11-06-11-30-35-0.snapshot`, `25.849.344 bytes`)

---

## 3. Kiểm thử độc lập Local (Section 3)

Script kiểm thử độc lập của AG tại `pipeline_v2/reviews/m3_ag_review_v1/test_m3_independent_ag.py` kiểm tra toàn bộ 8 nhóm bất biến mà không dùng `PassageReader`/`Corpus` làm oracle duy nhất:
1. **Manifest & Provenance (`test_01`, `test_02`):** Kiểm tra trực tiếp 916 file nguồn raw (`data/task1_train_files_2026/cases/*.txt`), 916 file M2 passages và 916 file M2 navigation theo seal SHA-256; tái xác nhận 1.024 `passage_ids` duy nhất, `input_hashes`, `source_hashes`, strata (`105 split_children`, `161 unicode`, `1 no_preview`), tính tất định độc lập thứ tự của `sample_passages` và phát hiện drift manifest/code/profile.
2. **Encoding, EOS 151643 & Cap 448 (`test_03`):** Kiểm tra toàn bộ 1.024 passages với `tokenizers.Tokenizer` gốc: raw document không thêm instruction, đúng 1 token cuối `<|endoftext|>` (`151643`), `full_input_tokens <= 448`. Kiểm tra Unicode/BOM/CRLF/special literals (`<|endoftext|>`, `<|im_start|>`, `<FRAGMENT_SUPPRESSED>`), ranh giới `448` vs `449` tokens, và từ chối query vượt `448` tokens sau khi gắn `Instruct: ...\nQuery:...` trước khi gọi remote (0 request phát sinh).
3. **Last-token Pooling & Vector Validation (`test_04`):** Kiểm chứng biểu thức `(attention_mask * arange(seq_len)).max(dim=1).values` với cả left-padding và right-padding trên độ dài chuỗi khác nhau, đảm bảo giá trị tại vị trí pad không bao giờ rò rỉ vào vector pooled và L2 normalization khớp tuyệt đối.
4. **Cache, Orphan Recovery & Attempt Ledger (`test_05`):** Kiểm chứng lỗi xảy ra trước khi nhận response ghi `tokens=None` (`unknown_token_attempts=1`, không giả `0`), lỗi xảy ra sau khi nhận response (ví dụ vector norm sai) vẫn ghi nhận đúng `input_tokens` từ response.
5. **Qdrant REST Adapter (`test_06`):** Kiểm chứng scroll nhiều trang (`next_page_offset`), từ chối collection có point thuộc `embedding_fingerprint` khác mà không xóa collection, và `restore_test()` từ chối ghi đè khi collection `_restore` đã tồn tại.
6. **BM25, Tie-aware Dense Reference & RRF (`test_07`):** Kiểm chứng `rank_cases` gộp nhiều passage/split child cùng case thành đúng 1 vote mỗi kênh, và `verify_pilot` chấp nhận hoán vị hợp lệ khi có đồng hạng (ties) tại ngưỡng top-k.
7. **Mở Context M2 (`test_08`):** Kiểm chứng mở context thực trên các đại diện split middle child, `quoted`, `unknown`, `unnumbered`, và `no_preview` trong tập 1.024 pilot: `previous_context -> parent -> next_context` đúng thứ tự byte nguồn, `hit_span_bytes` nằm trong `parent`, `diagnostic_only=True`, `M4_delivery_recorded=False`, và CLI `m3 open` từ chối passage ngoài pilot.
8. **Bảo mật Credential & Cô lập Scope (`test_09`):** Kiểm chứng `deploy_modal check` che (`[redacted]`) nếu secret vô tình bị dán vào `MODAL_PROFILE`/`MODAL_ENVIRONMENT`, và CLI `m3.py` chỉ in tên lớp ngoại lệ (`type(exc).__name__`) cho lỗi ngoài `M3Error`.

- **Ghi chú tự sửa checker của AG (`local_test_attempts.json`):** Attempt 1 lỗi ở chính script test của AG (`test_02` lấy `size=16` trên 18 risk tags; `test_08` đọc `opened["parent"]` thay vì `opened["components"]`). Attempt 2 lỗi do `common.write_json` mặc định `replace=False` trên file temp của `test_02`. Sau khi sửa script test của AG, Attempt 3 đạt **9/9 PASS** (`74,014s`). Bộ unit test targeted M3 + `deploy_modal` của Codex đạt **51/51 PASS** (`4,862s`).

---

## 4. Kết quả thực thi Pilot 1.024 Passages trên NVIDIA L4 (Section 4)

### 4.1. Kiểm tra Stop / Resume tại ranh giới Batch
1. **Baseline trước khi AG chạy (`baseline_state.json`):**
   - `preflight.json`: `status = PASS`, `model_requests = 6`, `known_input_tokens = 988`, `padded_tokens = 2.305`, `max_batch_cosine_deviation = 0.0003707408905029297` (ngưỡng `0.001`).
   - `vectors/`: `0` shards; Qdrant collection `coliee_m3_pilot_99e66b7f9bbf4be4`: `0 points`.
2. **Dừng sau 1 batch (`m3 run --stop-after-batches 1`):**
   - Kết quả: `status = stopped_at_batch_boundary`, `completed_batches = 1`, `local_elapsed_seconds = 167.676s`.
   - Ghi nhận 1 request mới (`id=7`, `batch="documents-0"`, `input_tokens=2.097`, `padded_tokens=6.352`, `remote_elapsed_seconds=1.920s`, cold load từ volume cache `model_load_seconds=17.301s`).
3. **Resume toàn bộ run (`m3 run`):**
   - Kết quả: `status = vectors_ingested_verified_not_full_pilot_acceptance`, `passages = 1024`, `local_elapsed_seconds = 145.398s`.
   - Batch `documents-0` được đọc từ local shard cache và upsert idempotent vào Qdrant, **không gọi lại Modal inference** (`documents-0` chỉ xuất hiện đúng 1 lần trong `ledger.sqlite3`).
   - 63 batches còn lại (`documents-1`..`documents-63`) chạy liên tục trên cùng container L4 đang ấm (`instance_id = 1e76ed58-8f38-47ae-8d37-3d5a9f8c6ca3`).

### 4.2. Kiểm tra Numerical, Qdrant, Snapshot/Restore & Container Restart
Kết quả đối chiếu độc lập trong `pilot_execution_audit.json`:
- **64 local vector shards (`vectors/*.npz` + `.json`):** Đủ 1.024 vectors × 2.560 dimensions (`float32`), hữu hạn 100%, độ lệch chuẩn L2 `|norm - 1.0|` tối đa `1.192e-7`, trung bình `2.171e-8` (ngưỡng cho phép `0.002`).
- **Độ khớp giữa local `.npz` cache và Qdrant (`coliee_m3_pilot_99e66b7f9bbf4be4`):** `max_primary_vs_cache_abs_diff = 0.0` (khớp tuyệt đối từng phần tử `float32` trên cả 1.024 vectors).
- **Snapshot & Restore (`m3 verify --restore-test`):** Tạo snapshot `25.849.344 bytes`, khôi phục sang `coliee_m3_pilot_99e66b7f9bbf4be4_restore` (`1.024 points`, `status = PASS`). Độ lệch giữa collection `_restore` và collection chính: `max_restored_vs_primary_abs_diff = 0.0`.
- **Container Restart Persistence:** Chạy `docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml stop` và `start`, sau đó chạy lại `m3 verify` (không flag) và `audit_real_pilot_execution.py`. Cả hai collection (`coliee_m3_pilot_99e66b7f9bbf4be4` và `coliee_m3_pilot_99e66b7f9bbf4be4_restore`) giữ nguyên `1.024 points`, payload/hashes và vectors với độ lệch `0.0`.
- **Exact NumPy Cosine Reference vs Qdrant Dense Search:**
  - `m3 verify` kiểm 3 mốc (`0`, `512`, `1023`): `3/3 tie_aware PASS`.
  - AG kiểm độc lập 10 mốc trải đều (`0, 17, 128, 256, 384, 512, 640, 768, 896, 1023`) có lọc `must_not: case_id`: khớp top-10, độ lệch điểm cosine tối đa giữa Qdrant và `vectors @ query` là `1.540e-7` (ngưỡng `1e-4`).

### 4.3. Kiểm tra Search, Eligibility Filter, RRF & Mở Context từ Hit
1. **Truy vấn 1 (`--query "standard of review" --limit 10`):**
   - `case_bm25` top 1: `079659.txt`; `passage_bm25` top 1: `000447:ef6699dc3552227474523d45`; `dense_passage` top 1: `008522:e35e6861cb1b7e51d43e3851`.
2. **Truy vấn 2 (`--query "standard of review" --query-case 079659.txt --limit 10`):**
   - Án `079659.txt` bị loại trừ hoàn toàn trước cap trên cả 3 kênh (`case_bm25`, `passage_bm25`, `dense_passage`) và kết quả hợp nhất `results` (`case_bm25` top 1 chuyển sang `083342.txt`).
3. **Truy vấn 3 (`--query "décision n'est pas raisonnable under s. 97(1)" --limit 10`):**
   - Kiểm tra tiếng Pháp có dấu, phủ định và số hiệu điều luật: `case_bm25` top 1 `098083.txt`, `passage_bm25` top 1 `027247:941b009c4949b7c127fa52ad`, `dense_passage` top 1 `048242:108e8f947a524d072825986d`.
   - Điểm RRF hợp nhất trên cả 3 truy vấn khớp tuyệt đối công thức $\sum c \frac{1}{60 + \text{rank}_c}$ với đúng 1 phiếu cho mỗi case trên mỗi kênh.
4. **Mở Context (`m3 open` & `opened_search_hits`) và Literal Search (`m3 literal`):**
   - Mở context cho các top hit (`008522:e35e6861cb1b7e51d43e3851`, `000447:ef6699dc3552227474523d45`, `048242:108e8f947a524d072825986d`, `027247:941b009c4949b7c127fa52ad`, `000031:018547a62831b1cdec3cb655`): tất cả đều trả đầy đủ `previous_context`, `parent`, `next_context` khớp byte nguồn M2, `diagnostic_only=True`, `M4_delivery_recorded=False`.
   - `m3 literal --text "Federal Court" --ignore-case` trả đúng byte spans `[a, b]` trên raw bytes của các án thuộc pilot.

---

## 5. Accounting Token, Requests, Retries & Latency

| Giai đoạn | Số requests Modal | Known Input Tokens | Padded Tokens | Padding Overhead | Lỗi / Retries | Unknown Token Attempts |
|---|---:|---:|---:|---:|---:|---:|
| **Baseline Preflight (Codex bàn giao)** | 6 | 988 | 2.305 | 1.317 | 0 / 0 | 0 |
| **Pilot Batch 0 (`--stop-after-batches 1`)** | 1 | 2.097 | 6.352 | 4.255 | 0 / 0 | 0 |
| **Pilot Batches 1..63 (Resume)** | 63 | 130.746 | 332.176 | 201.430 | 0 / 0 | 0 |
| **Tổng Document Batches (0..63)** | **64** | **132.843** | **338.528** | **205.685** | **0 / 0** | **0** |
| **Search Queries (3 truy vấn)** | 3 | 118 | 118 | 0 | 0 / 0 | 0 |
| **Phần tăng thêm trong lượt AG** | **67** | **132.961** | **338.646** | **205.685** | **0 / 0** | **0** |
| **TỔNG CỘNG TOÀN RUN (gồm Preflight)** | **73** | **133.949** | **340.951** | **207.002** | **0 / 0** | **0** |

- **Development-chat tokens:** `unknown` (`null`).
- **Chi tiết Latency & Throughput trên NVIDIA L4 (`pilot_execution_audit.json`):**
  - **Cold model load:** Preflight lần đầu `43,730s` (tải/kiểm tra từ volume); Pilot batch 0 (`documents-0`) khi container khởi động lại từ volume cache mất `17,301s` load model, tổng client elapsed `135,708s`, remote GPU encode `1,920s`.
  - **Warm batches (`documents-1`..`documents-63`, 63 batches × 16 passages):**
    - Remote GPU encode time: min `0,563s`, median `1,090s`, mean `1,119s`, max `1,544s`, tổng `70,471s` (cả 64 batches là `72,392s`).
    - Client RPC elapsed time: min `1,000s`, median `1,537s`, mean `1,691s`, max `5,528s`, tổng `106,550s`.
  - **Throughput GPU thực tế (trên 72,392s GPU encode của 64 batches):** `14,15 passages/s` (`1.835,06 input tokens/s`; `4.676,34 padded tokens/s`).
  - **Search query latency (3 queries trên warm container):** Remote GPU encode `[0,104s, 0,063s, 0,066s]`; client RPC `[4,318s, 4,437s, 4,715s]`; tổng thời gian CLI local `[67,331s, 66,326s, 66,169s]` (do kiểm tra lại 916 raw cases và dựng BM25 in-memory mỗi lệnh).

---

## 6. Giới hạn đã ghi nhận & Danh sách lỗi cần Codex sửa

- **Lỗi chặn / Lỗi production cần sửa cho M3 Pilot:** **Không có (`0` lỗi).**
- **Giới hạn đã ghi nhận (Documented Limits — xem `findings.json`):**
  1. `M3-OBS-01`: `search_pilot` dựng lại BM25 trên 916 raw cases và scroll kiểm tra toàn bộ Qdrant mỗi lần gọi CLI (~66s local). Phù hợp và an toàn cho pilot 1.024 passages, nhưng khi mở sang full corpus (415.693 passages / 7.708 cases) cần chỉ mục BM25 bền vững trên đĩa và tách bước full verify khỏi mỗi câu query.
  2. `M3-OBS-02`: Gom batch 16 theo thứ tự `passage_id` cố định tạo `338.528` padded tokens trên `132.843` input tokens (~2,55×). Khi chạy full corpus có thể cân nhắc gom batch theo độ dài token gần nhau nếu vẫn giữ đầy đủ provenance ID/hash.
  3. `M3-OBS-03`: Pilot vận hành đạt (`pass_with_documented_limits`) chỉ chứng nhận tính đúng đắn kỹ thuật của pipeline M3 pilot (provenance, token parity, pooling, cache/resume, Qdrant persistence, snapshot/restore, hybrid RRF & mở context nguồn). Chưa đánh giá ngữ nghĩa pháp lý, ownership, M4 context budgeting/delivery hay điểm F1 COLIEE trên gold.
