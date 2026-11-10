# M3 — Runner toàn bộ train

Phạm vi được giao: Codex triển khai code, kiểm local và chuẩn bị lệnh; AG review/test rồi chạy các lệnh Modal do người dùng chủ động giao. Chat Codex không gọi Modal. Namespace mới `full_corpus/`, CLI `m3_full.py`, profile `configs/m3_full.json`; giữ nguyên pilot, optimization V1/V2 và các artifacts đã niêm phong.

## Contract triển khai

- Toàn bộ bundle M2 đã khóa: 415.693 passages từ 7.708 án. Không truy cập gold hoặc nhãn. Nguồn/hash/offset/tokenizer được giữ nguyên; không chunk lại hoặc đổi model.
- Sắp xếp theo full token length rồi passage ID, batch64, phần dư thành batch cuối; mỗi ID đúng một lần. Lưu batch schedule và metadata không có raw text. Case BM25 và passage BM25 tạo từ nguồn bằng streaming postings. Không nạp toàn corpus text hoặc ma trận vector vào RAM.
- Dùng app `coliee-pipeline-v2-embed-m3-opt-v2`, NVIDIA L4, fingerprint embedding V2 đã đo. Batch64 là cấu hình khởi đầu từ pilot, không phải cam kết tối ưu full. Không tự deploy hoặc thay package/model/template.
- Real compatibility receipt của pilot là điều kiện mở inference; full plan buộc đúng code/profile/model/app/receipt đã kiểm. Mocks không cấp quyền chạy thật.
- Collection full riêng; không ghi đè collection pilot. Vector/cache/ledger nằm local, vector DB là Qdrant Docker local. Vector on-disk và verify theo trang, không scroll toàn bộ vectors vào một list.
- Cache commit trước DB upsert; resume dùng cache và upsert idempotent. Lưu ledger mọi request kể cả lỗi hoặc lần chết giữa chừng; unknown processed tokens giữ unknown. Không coi progress là bằng chứng đủ cache/DB; cache đã commit bị thiếu/hỏng phải fail thay vì tự re-embed.
- Chỉ một writer/run; lệnh dừng theo batch cho phép canary và fault/restart test. Không retry vô hạn, không tự đổi batch size sau OOM, không xóa cache/collection để che lỗi.
- Verify riêng kiểm đủ membership, payload và vectors so cache bằng RAM bounded. Kết quả partial hoặc mới ingest xong chưa được gọi là full M3/quality PASS. Gold COLIEE, M4 agent và F1 nằm ngoài lượt này.

## Trạng thái

Production đã freeze tại `e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503`. Bộ kiểm thử độc lập30/30PASS (12tests mới và18regressionV2), dùng temp/mocks; xem [báo cáo kiểm thử](M3_FULL_TEST_REPORT.md). Main đã dựng và audit plan thật PASS, chưa gọi Modal hoặc full ingestion.

Build local đã hoàn tất: `artifacts/m3_full_train_20261108_v1/`,415.693passages/7.708cases,6.496batches, collection dự kiến `coliee_m3_full_ef2f4d6950a5b9fd`. SQLite4.357.505.024bytes; walltime1.177,82s (19,63phút),0modelrequests. Status smoke với.env không tồn tại PASS, trảplanned/0requests; internalCLI31,18s do fullhash/provenance, không phải latency retrieval. Vì vậy không poll status liên tục.

Audit riêng trên toàn bộ nguồn PASS trong193,67s: đủ7708rawcases/415693passages, hash/UTF-8spans/metadata/seals khớpM2; thứ tựtokens+ID và mỗiID đúng1lần;6496batches, batchcuối13. Tổng55.346.360inputtokens,55.360.576paddedtokens, paddingratio1,000257. Đây là lịch dự kiến chưa encode, không phải billed/model-processed usage. Không vector/cache/ledger/runtime hoặc collectionfull nào được tạo ở bước này. Code/profile baseline/V2 giữ nguyên. Evidence: [audit thực tế](../reviews/m3_full_validation_v1/real_full_plan_audit.json), [nghiệm thu local](../reviews/m3_full_validation_v1/local_acceptance.json).

## Lệnh và vận hành

CLI: `python -m pipeline_v2.m3_full {plan,run,status,verify,open}`. Các đường dẫn output/run phải nằm trong `pipeline_v2/artifacts/`. Chỉ `run` đọc.env và có thể gọi Modal; `plan/status/verify/open/help` không inference. `verify` cần DB đã có nhưng không tự tạo hoặc sửa DB/cache; kết quả chỉ in stdout để caller lưu evidence.

Lệnh `plan --output TEN_MOI` tạo BM25 và schedule local, cần output chưa tồn tại. CPU build này chưa hỗ trợ resume: thư mục bị ngắt chưa có finalseal sẽ bị chặn chạy; giữ để audit, chọn suffix mới khi được giao rebuild. Embedding `run --run-dir TEN_DA_PLAN` có resume: giữ nguyên run-dir, code/profile/seal/receipt; không replan để tiếp tục inference.

`run --max-batches 2` xử lý tối đa2batches cần inference hoặc upsert trong invocation; cached batches đã khớp DB được skip và không tính vào giới hạn. Sau canary, `run` không max-batches tiếp tục phần còn lại. Mỗi lần gọi có append-only receipt trong `invocations/`; progress/run_result là latest snapshot, ledger giữ cả attempts lỗi hoặc gián đoạn. Failure đầu tiên dừng, không auto-retry/auto-downsize.

`status` lấy checkpoint gần nhất và cumulative ledger, không chứng minh process còn sống hoặc DB vẫn đúng. `verify` đọc từng64vectors, kiểm đủIDs/payload/norm/cachevectors và exactcount. Nên chạy khi writer đã dừng. Cần xem kết quả chứ không chỉ exit shell. Toàn bộ lệnh/giới hạn giao AG: [AG_M3_FULL_TEST_PROMPT.md](AG_M3_FULL_TEST_PROMPT.md).

## Giới hạn của lần bàn giao

## Cập nhật nghiệm thu09/11/2026

Full ingestion đã hoàn tất và AG verify độc lập PASS415.693points. Main đối chiếu ledger:6.496successfulbatches/6.496committed,1startedgiữunknownusage; successfulinput55.346.360,padded55.360.576. Cachethật4.466.141.805bytes; code/profile khớp snapshot. Không cần chạy lại inference. Xem [nghiệm thu Main và đính chính số liệu cache](../reviews/m3_full_validation_v1/AG_REVIEW_ACCEPTANCE.md), [báo cáo AG](../reviews/m3_full_ag_review_v1/REPORT.md).

Phần chưa gọiModal/fullingestion ở trên là checkpoint trước bàn giao, hiện đã được thay bằng kết quả thực tế này. Chưa có fullhybridsearch/COLIEEF1/M4. Progress ở cachedskip/verify cuối chưa có cập nhật theo giai đoạn; giữ thành việc sửa cho revision kế tiếp, không thay code đã bind artifacts.

Runner này chưa có full hybrid search adapter và chưa hoàn tất toàn bộ M3. `open` giữ contract hit→parent+neighbors từ M2; không thay M4 agent hoặc selector. Chưa có full snapshot/restore theo streaming, COLIEE gold/F1 hoặc kiểm semantic quality. Không dùng snapshot/restore helper pilot cho fullDB vì helper cũ có thể gom vectors/bytes vào RAM. Vector FP32 thuần toàn corpus khoảng4,26GB, chưa gồm cache metadata, DB và BM25; không suy throughput full bằng ngoại suy pilot.
