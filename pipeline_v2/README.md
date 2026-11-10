# Pipeline V2 — COLIEE Task 1

**Tiến độ hiện hành ngày 10/11/2026** nằm trong [bảng M0–M7](docs/PROGRESS.md). M3 đã có full ingestion và kết quả hybrid trên Qdrant. Chỉ mục BM25 sparse đã qua đối chiếu trên toàn corpus. Các đoạn trạng thái cũ bên dưới mô tả checkpoint lịch sử.

Namespace triển khai mới, độc lập tại root repo: `E:/Git/coliee-case-retrieval/pipeline_v2/`.

**Trạng thái:** M0 đã khóa; M1 Revision 2 được chấp nhận về nguồn/ranh giới marker với giới hạn đã ghi. **M2 local hoàn tất:** navigation hiện hành `artifacts/m2_navigation_20261106_v3/`, token passages `artifacts/m2_passages_20261106_v1/`. Có **7.708 nguồn, 382.343 parents, 415.693 passages**, tối đa **448 full-input tokens**; 65/65 tests, validator và audit raw/token độc lập toàn corpus PASS. Child mở đúng full parent + previous/next theo nguồn; giữ nguyên M1/navigation. Không coi protocol PASS là semantic/retrieval quality. Tokenizer agent/payload budget và endpoint preflight chưa ready; tiếng Pháp giữ nguyên chưa xử lý riêng. Các bundle/báo cáo cũ giữ nguyên. **M3 code pilot do Codex triển khai**, local tests 104/104 PASS, plan 1.024 passages từ M2 thật đã tạo; chưa deploy/inference, chạy DB thật hoặc full index/embedding. M4–M7 chưa triển khai.

**Embedding:** `Qwen/Qwen3-Embedding-4B`, tự host Modal; revision/tokenizer assets đã pin cho M2. Raw body không instruction/prefix/chat template; tính một token cuối do tokenizer chính thức thêm. Các profile null trong bundle navigation là checkpoint cũ giữ nguyên. Local token-valid không có nghĩa endpoint/runtime embedding đã ready; tokenizer agent vẫn chưa chọn.

**GPU hiện hành: L4**, run pilot `artifacts/m3_pilot_20261106_l4_v1/`. Plan/audit local PASS, 20/20 kiểm thử liên quan PASS; plan A10 cũ giữ nguyên làm lịch sử. Dùng [hướng dẫn deploy](docs/MODAL_DEPLOY.md) cho lệnh hiện hành. Chưa gọi GPU trong bước đổi cấu hình.

- [M0: lệnh tái hiện, artifact và giới hạn](docs/M0.md).
- [M1 Revision 2 hiện hành: marker độc lập, cách chạy và giới hạn](docs/M1_REVISION2.md).
- [M1 v1 lịch sử](docs/M1.md).
- [Kiểm thử M1 Revision 2 độc lập](docs/M1_REVISION2_TEST_REPORT.md).
- [Prompt giao AG review lại](docs/AG_REVIEW_M1_REVISION2_PROMPT.md).
- [M2 navigation: lệnh chạy, mapping và giới hạn](docs/M2.md).
- [Embedding đã chốt: Qwen3-Embedding-4B tự host Modal](docs/EMBEDDING_SELECTION.md).
- [Kiểm thử M2 độc lập](docs/M2_TEST_REPORT.md).
- [Prompt AG review rộng navigation/preview M2](docs/AG_REVIEW_M2_NAVIGATION_PROMPT.md).
- [M2 preview Revision 2 hiện hành và bundle v3](docs/M2_PREVIEW_REVISION2.md).
- [Kiểm thử/audit bản sửa preview](docs/M2_PREVIEW_REVISION2_TEST_REPORT.md).
- [Prompt AG review lại bản sửa preview](docs/AG_REVIEW_M2_PREVIEW_REVISION2_PROMPT.md).
- [M2 passages hoàn tất: profile, bundle, counts, lệnh và giới hạn](docs/M2_PASSAGES.md).
- [Kiểm thử và audit token passages](docs/M2_PASSAGES_TEST_REPORT.md).
- [Prompt AG review M2 passages](docs/AG_REVIEW_M2_PASSAGES_PROMPT.md).
- [M3: cấu hình Qdrant local bằng Docker](docs/M3_QDRANT_DOCKER.md).
- [M3 code pilot: CLI và phân công Codex/AG](docs/M3.md).
- [Deploy Modal: file deployment, .env và lệnh chạy](docs/MODAL_DEPLOY.md).
- [Kiểm thử M3 local độc lập](docs/M3_LOCAL_TEST_REPORT.md).
- [Tối ưu M3: persistent BM25, length batching và benchmark L4](docs/M3_OPTIMIZATION.md).
- [M3 optimization V2: bản sửa sau review và nghiệm thu local](docs/M3_OPTIMIZATION_V2.md).
- [Kiểm thử M3 optimization V2](docs/M3_OPT_V2_TEST_REPORT.md).
- [Prompt AG review/test và lệnh chạy Modal V2](docs/AG_M3_OPT_V2_TEST_PROMPT.md).
- [Runner M3 toàn corpus: contract và trạng thái](docs/M3_FULL.md).
- [Kiểm thử độc lập runner full](docs/M3_FULL_TEST_REPORT.md).
- [Prompt AG review/test và lệnh chạy full](docs/AG_M3_FULL_TEST_PROMPT.md).
- [Draft kế hoạch M3 full search để review](docs/plan/M3_FULL_SEARCH.md).
- [Prompt AG review thiết kế full search](docs/AG_REVIEW_M3_FULL_SEARCH_PLAN_PROMPT.md).
- [Reader BM25 local tối ưu](docs/M3_LEXICAL.md).
- [Hybrid search trên full train và lệnh kiểm thử](docs/M3_HYBRID.md).
- [Chỉ mục BM25 sparse dạng mảng](docs/M3_SPARSE.md).
- [Kiểm thử sparse reader](docs/M3_SPARSE_TEST_REPORT.md).
- [Prompt AG review sparse](docs/AG_REVIEW_M3_SPARSE_PROMPT.md).
- [Kiểm thử reader BM25](docs/M3_LEXICAL_TEST_REPORT.md).
- [Prompt AG review reader BM25](docs/AG_REVIEW_M3_LEXICAL_PROMPT.md).
- [Prompt AG kiểm thử, review và chạy thử M3 trên code Codex](docs/AG_M3_TEST_PROMPT.md).

## Kế hoạch dùng cho triển khai

- [Kế hoạch tổng thể và các mốc M0–M7](docs/plan/README.md).
- [Nguồn, paragraph/chunk và BM25 + embedding](docs/plan/SOURCE_CHUNK_INDEX.md).
- [Agent, trạng thái, final selection và đánh giá](docs/plan/AGENT_AND_EVALUATION.md).

## Bố cục dự kiến

```text
pipeline_v2/
  source/       # raw source registry, cấu trúc, metadata, offsets
  passages/     # token-valid passage views, embedding inputs và parent/context refs
  retrieval/    # BM25, dense, hybrid và search adapters
  agent/        # controller, tools, delivery và state
  selection/    # evidence scorer và policy chọn án
  evaluation/   # evaluator và freeze protocol
  contracts/    # schemas/interfaces
  configs/      # profiles có version
  tests/        # local invariants và integration tests
  docs/         # kế hoạch, hướng dẫn và báo cáo mới
  artifacts/    # indices, vectors/cache, receipts và run outputs
```

Đã có `m0.py`, cấu hình M0, tests và manifest M0; các thư mục runtime khác sẽ tạo ở mốc tương ứng.

## Ranh giới

- Corpus và labels chuẩn tiếp tục đọc từ `../data/`; solver không được cấp labels.
- Không sửa pipeline cũ, artifact V13–V15 hoặc kết quả lịch sử.
- Logic cũ có thể được tham khảo/port có kiểm tra vào V2; không mặc định phụ thuộc runtime V1.
- Toàn bộ code/config/test/artifact mới cho lần triển khai này nằm dưới `pipeline_v2/`. Kế hoạch cũ được bảo toàn; bản trong `docs/plan/` là bản dùng để triển khai.
- Việc chọn namespace không tự mở quyền chạy paid inference, deploy hoặc workload ngoài scope được giao.
