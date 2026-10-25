# Thử tối ưu tốc độ theo từng bước

## Mục tiêu và phạm vi

Giảm thời gian/án và chi phí toàn corpus, vẫn đọc đủ nguồn và giữ contract AU,
ownership, evidence, offsets/hash. Không thay extraction bằng rule hoặc bỏ đoạn
không có citation. KOS là tham khảo, output cũ không phải gold. Chưa mở toàn corpus.

Checkpoint Mốc1 giữ nguyên. Thử nghiệm ở app, job volume, manifest và output riêng;
không deploy đè endpoint cũ hoặc dùng lại job đã hoàn tất để đo tốc độ mới.

Tài liệu/code đầu vào: `04_pipeline_spec.md`, `13_fast_kos_comparison_plan.md`,
`knowledge_base/pipeline_v1/milestone1/README.md`, manifest
`au_compact_kos5_full_m1.v1.json`, `au_compact/{runner,prompting,decoding,jobs_client}.py`,
deployment `deployments/modal/{qwen35_9b_l40s,job_gateway}.py` và checkpoint Mốc1.

## Bước 1 — Concurrency trên một GPU

- Khóa cùng 30 target bằng phân tầng độ dài trong cả KOS-5, chọn từ source trước
  khi xem kết quả thử. Model Qwen3.5-9B, thinking false, prompt/schema/evidence và
  output cap 800 không đổi. Chỉ request ID quản trị được đặt riêng cho từng arm để
  tránh reuse server job; target/source/context giữ nguyên.
- So C1/C2/C4: lần lượt 1/2/4 request đồng thời. Giữ L40S một GPU, tối đa một
  container, model revision, context và tổng KV budget không đổi. CUDA graph batch
  cap thay theo mức concurrency; ghi rõ đây là cấu hình vận hành đi cùng arm.
- Gateway thử nghiệm dùng worker giới hạn, claim durable trước dispatch, không
  duplicate backend dispatch; synchronous probe/diagnostic phải độc quyền với mọi
  inference. Unknown backend outcome chặn admission/dispatch, không tự retry.
- Client giữ tối đa N job đang chờ, checkpoint từng request, dừng gửi mới khi
  outcome unknown. Resume không tính cached response là inference mới hoặc làm
  bằng chứng throughput. Không thay ledger/cache của Mốc1.
- Local trước: test cap, duplicate, probe exclusivity, recovery, failure, immutable
  identity, source/catalog, checkpoint, không in credentials. Sau PASS mới deploy
  app thử riêng và chạy lần lượt C1 -> C2 -> C4. Nếu C2 lỗi/OOM không chạy tiếp C4.
- Mỗi arm tối đa 30 source dispatch, không repair/retry tự động. Tổng tối đa 90
  source request, reserve output 72.000 token; input reserve tính từ prompt từng
  target. Startup/warmup/capability kiểm tra và token lỗi báo riêng, không giấu.
- Báo wall time, targets/giây, p50/p95, input/output, backend/queue/client overhead,
  cache/resume, formal lỗi, truncation, needs_split, ownership và khác biệt AU.
  CPU/GPU/VRAM không đo được phải ghi unavailable, không coi model local miễn phí.
- Chỉ chọn cấu hình nhanh hơn trên fresh complete run, không tăng formal lỗi hoặc
  thiếu target. Kết quả model khác nhau cần review từ source; protocol PASS không
  đủ để chốt chất lượng. Thử lặp nếu chênh lệch nhỏ/không ổn định.

## Bước 2 — Prefix caching

Chỉ thực hiện sau báo cáo Bước1. Dùng concurrency đã chọn; so prompt hiện tại với
prefix cố định (instructions/few-shot), dữ liệu/ID thay đổi đặt sau. Giữ cùng target,
schema và nội dung evidence. Kiểm tra phiên bản SGLang và Qwen hybrid cache thực tế,
không mặc định cache đã bật hoặc có hit. Đo cold/warm, cache hit/prefill, total token
và thời gian; startup/cache warming báo riêng. KV cache tiết kiệm compute, không
đồng nghĩa provider báo ít input token. Nếu không có lợi hoặc làm sai contract thì
bỏ; chưa thêm session/state model vào KB.

## Bước 3 — Batching target

Chỉ thực hiện sau Bước2. So B1/B2/B4 trên cùng target và cấu hình inference đã khóa;
gộp target liền nhau theo token cap, context/atom trùng chỉ gửi một lần. Mỗi target
có đúng một kết quả, có thể có nhiều AU, giữ ownership/evidence riêng. Host cấp
ID/catalog; output cap theo batch, batch quá lớn chia trước dispatch. Khóa schema/
grammar phiên bản batch mới; không dùng cache single-target làm kết quả batch.
Đo omission, condition/attribution, truncation và token/thời gian. Chọn B2 nếu B4
không đạt, không ép batching để bảo vệ đề xuất. Chưa giảm coverage bằng rule.

## Điều kiện chuyển bước và nghiệm thu

Mỗi bước có manifest khóa, local tests, lệnh deploy/run, report JSON và kết luận
giữ/bỏ/cần đo. Không sửa baseline đang dừng. Không mở bước sau chỉ vì endpoint trả
200: cần complete coverage, số đo fresh và review khác biệt. Hiệu quả chưa đo là
giả thuyết. Chưa thiết kế lại reranker hoặc NN-AU matching.

Hiện triển khai trước công cụ Bước1; Bước2/3 là kế hoạch, chưa được coi đã thực hiện.

## Cập nhật kết quả Bước1

Workload `outputs/concurrency_step1_adapter_fix_20261012`: 30 target fresh/arm,
protocol PASS 30/30 cả C1/C2/C4, không needs_split. Wall C1 510,438 giây,
C2 278,469 giây, C4 191,750 giây; C4 nhanh 2,66x C1. Tổng token lần lượt
70.100/70.308/70.214, chưa tính setup. Đây là một lượt đo/pilot, chưa đủ ngoại suy
corpus hoặc xác nhận ngữ nghĩa. C4 đổi 10 output so C1, decision giữ nguyên nhưng
vẫn có lỗi context-only AU được kiểm tra từ nguồn. Chọn C4 làm tham chiếu vận hành
cho thử tiếp, chưa nâng thành baseline sản xuất. Xem `STEP1_RESULT.md` và
`comparison.json` ở output trên. Bước2/3 chưa triển khai; gate ngữ nghĩa/lặp vẫn mở.

Kiểm tra Bước2 ngày 2026-10-13: prompt đã có prefix cố định đầu tiên (~6.660
ký tự chung/30 prompt), không có bằng chứng cần đổi thứ tự. Cache report chưa
bật, receipt chưa giữ cached_tokens và diagnostic chưa expose cache flags.
GET runtime có giới hạn vẫn503 nên actual cache hit chưa xác nhận. Ưu tiên
instrumentation/report trước thử bật/tắt cache; xem
`outputs/prefix_cache_check_20261012/RESULT.md`. Chưa thay runtime/deploy.

Triển khai instrumentation Bước2 ngày 2026-10-13: app thử thêm enable-cache-report,
diagnostic whitelist cache flags có kiểu và receipt giữ cache_observation riêng
(không đổi _usage/accounting). Package `prefix_cache_probe` khóa 5 target x2 phase
fresh ID, tổng10 request; client tuần tự trên server C4. Không gọi initial là cold,
không flush/tắt cache hoặc đổi prompt/schema. Runtime gate trước dispatch và job
receipt reuse được loại khỏi cache-hit evidence. Preflight local PASS; inference
thật cần chạy script trong README. Bước3 chưa triển khai; actual cache hit chưa đo.
