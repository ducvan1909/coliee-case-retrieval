# Đối chiếu thiết kế khác để tối ưu pipeline — đề xuất, chưa đổi kiến trúc

Ngày kiểm tra: 2026-10-13. Đọc toàn văn hai bài Lynx và code/docs primary của
LangExtract, SGLang, Ray Data, vLLM. Không cài thư viện, deploy hoặc chạy inference.
Không chỉnh spec04, schema AU, nguồn/KOS hoặc checkpoint lịch sử.

## Bằng chứng hiện tại

C4 trên 30 target: 191,750 giây, 30/30 protocol PASS; tốc độ 2,66x C1, không chứng
minh semantic quality. Probe tuần tự10: wall184,516 giây; tổng thời gian backend
được gateway báo91,725 giây; phần còn lại92,791 giây (~50,29%). Đây không phải phép
đo GPU kernels, không được suy có thể giảm50% thời gian C4. Prefix cache đã hit
1472 token ở8 request; hai request thiếu counter theo định dạng sparse của SGLang.

## Các thiết kế và phần lấy được

| Thiết kế | Bằng chứng primary đã đọc | Ý tưởng áp dụng, không phải lợi ích đã đo |
|---|---|---|
| Lynx 2019 | §4, tr.62; Camunda/RabbitMQ, queue orchestration | Host lập task và worker độc lập; chỉ truyền tham chiếu nguồn/annotation giữa các bước |
| Lynx 2020 | §4.3.1–4.3.3, tr.2336–2337; DAG, worker pool, shared objects | Tách stage CPU/inference/persistence, chạy song song phần không phụ thuộc |
| LangExtract | annotation.py:343–398; mỗi chunk tạo prompt riêng rồi infer danh sách | Batch transport/model scheduling không đồng nghĩa multi-target prompt; giữ identity và grounding từng target |
| SGLang | Offline Engine API; generate(prompts, sampling_params), async API | Corpus runner ở GPU host, giảm lượt HTTP/poll; engine scheduling vẫn giữ output riêng |
| Ray Data LLM | concurrent batches, tasks in flight; checkpoint theo ID | Tách GPU concurrency khỏi prefetch/queue depth; checkpoint theo item ID và sink đã ghi |
| vLLM APC | Limits: cache tối ưu prefill, không decode | Đừng tăng kỳ vọng prefix cache; hiện đã hit, cần giảm output/overhead có đo |

Nguồn:

- [Lynx 2019 full text](https://aclanthology.org/W19-2207.pdf).
- [Lynx 2020 full text](https://aclanthology.org/2020.lrec-1.284.pdf).
- [LangExtract annotation](https://github.com/google/langextract/blob/main/langextract/annotation.py),
  [chunking](https://github.com/google/langextract/blob/main/langextract/chunking.py),
  [resolver](https://github.com/google/langextract/blob/main/langextract/resolver.py).
- [SGLang Offline Engine](https://docs.sglang.io/docs/basic_usage/offline_engine_api),
  [Engine code v0.5.19](https://github.com/sgl-project/sglang/blob/v0.5.19/python/sglang/srt/entrypoints/engine.py).
- [Ray Data LLM](https://docs.ray.io/en/latest/data/working-with-llms.html).
- [vLLM prefix caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/).

Lynx không đánh giá token/cost AU extraction với Qwen/COLIEE. LangExtract hiện có
multi-pass và fuzzy alignment, không phải bằng chứng AU đúng. Không sao chép cách
cắt theo max_char_buffer thay SourceBlock P2; không dùng fuzzy match làm exact
evidence, không dùng overlap/first-pass-wins để loại AU khác cùng evidence.
Không tăng extraction_passes toàn corpus: nhân số lượt đọc, chưa chứng minh cần.
Không cần thêm Camunda/RabbitMQ/Ray chỉ để học cách tổ chức workflow.

## Ưu tiên được đề xuất lại

1. **Bulk admission + aggregate progress trên gateway hiện tại.** Host gửi manifest
   nhóm8–16 request, server giữ tối đa4 inference; mỗi prompt vẫn một target, không
   đổi contract. GET tiến độ nhóm và lấy phần kết quả mới bằng cursor. Số8–16 là
   giả thuyết queue depth, không phải8–16 GPU concurrency.
2. **Tách pending queue khỏi archive, pipeline host CPU/GPU/writer.** Không scan toàn
   bộ file job đã hoàn tất ở mỗi lần claim. Chuẩn bị catalog/prompt trước trong
   hàng đợi giới hạn, không tích cả corpus trong RAM. Giữ commit-before-dispatch;
   không bớt durability để tạo số đo đẹp.
3. **Corpus-mode server runner / Offline Engine arm.** Nếu transport vẫn là nút
   thắt, gửi workload artifact một lần rồi xử lý/lưu receipt trên GPU host. Engine
   trực tiếp là lựa chọn đối chứng sau; phải giữ chat template, thinking false,
   EBNF per-request, EOS sync và exact normalization, không đổi runtime tùy tiện.
4. **Multi-target prompt B2, rồi B4.** Mới đổi schema/prompt, gộp atom chung và
   ownership per target. Batch ở tầng suy luận khác batch transport; phải đo thêm
   omission, attribution và điều kiện. Dùng token/output budget, không ghép cứng4
   đoạn dài. Giữ C4 làm cấu hình vận hành đối chứng.
5. **Nhiều GPU/replica** khi một GPU đã đủ hiệu quả; shard và jobstore riêng hoặc
   lease/store có giao dịch. Mutex Python hiện tại chỉ bảo vệ trong một process.

## Phép thử để quyết định

- A: C4 hiện tại; B: bulk/aggregate C4, cùng target/prompt/schema/output caps;
  C: offline corpus runner chỉ khi B cho thấy cần. Fresh IDs và cache-hit accounting
  tách khỏi server job response reuse; không đổi enrichment/retrieval khi so.
- Đo wall/throughput, HTTP count/bytes, queue/persist/commit/backend time, tổng
  input/output/reasoning và retry, GPU utilization/VRAM nếu thu được.
- Kiểm tra source/offset/hash/grammar/ownership/coverage và resume giữa receipt
  write/commit/ack. Kết quả lỗi phải được tính; không bỏ sót target để báo nhanh.
- Sau đó thử B2 trên cùng source spans; so với B1+C4, chứ không so workflow khác
  cả model/source rồi quy hiệu quả cho batching. Không có cam kết speedup trước đo.

Đây là review và ưu tiên đề xuất. Chưa implement bulk/offline/B2, chưa sửa kế
hoạch14 hoặc kiến trúc chính để chốt thay đổi thay người dùng.
