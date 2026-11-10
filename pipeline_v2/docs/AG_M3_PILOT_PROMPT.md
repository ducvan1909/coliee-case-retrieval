# AG kiểm thử độc lập và chạy thử M3 pilot

**Phân công đã được người dùng sửa:** Codex triển khai và sửa production code M3. AG chỉ review, bổ sung code kiểm thử độc lập và chạy thử trên bản đã đóng băng khi cần. Không triển khai hoặc tự sửa production để làm test PASS.

Repo `E:/Git/coliee-case-retrieval`, namespace `pipeline_v2/`, Windows/PowerShell, `.venv/Scripts/python.exe`. Đọc AGENTS.md; checkout E: và namespace mới do user chốt thay đường dẫn G:/scope V1 cũ.

## 0. Trạng thái bàn giao hiện tại — tiếp tục từ preflight L4 đã PASS

Codex đã kiểm file thật, không chỉ dựa log chat:
- Run hiện hành `pipeline_v2/artifacts/m3_pilot_20261106_l4_v1/`:1.024passages từ916án; **không dùng run A10 cũ**.
- Deploy/model GPU thực đã hoạt động: `preflight.json` status `PASS`, GPU `NVIDIA L4`, BF16,2560dimensions, đúng revision; code/profile/input fingerprints khớp manifest.
- Embedding fingerprint `d945329fa49e2f4b4f83d530df03fb4897babd5345562cbeaebd3b21499649bf`; production code aggregate `ade771e2d328b974d12421b5fa48b2b90632b10eb8422166f82b9f960d9add63`.
- Preflight baseline6requests thành công/988inputtokens, max singleton-vs-batch cosine deviation0.0003707408905029297; Qdrant1.20.0. Chưa có `run_result.json` lúc bàn giao; chưa chạy pilot1.024documents.

**Nhiệm vụ lượt này: review/test độc lập, sau đó chạy pilot1.024 thật nếu không có lỗi chặn.** Dùng lại run và preflight hợp lệ ở trên; kiểm trạng thái hiện tại khi bắt đầu vì user có thể đã chạy tiếp. Không redeploy, replan hoặc gọi lại preflight chỉ để lặp kết quả đã đạt. Nếu code/profile/source thay đổi, preflight mất hiệu lực hoặc phát hiện vấn đề cần kiểm lại thì ghi evidence và lý do; không sửa manifest/checksum để vượt guard.

`.env` chỉ helper local đọc; không mở/in/copy credentials vào review artifacts. Mọi lệnh cần auth/inference dùng `pipeline_v2.deploy_modal` để nạp cấu hình nhất quán. Trước chạy remote lưu baseline ledger/cache/DB; sau chạy báo phần tăng thêm, không bỏ6requests/988tokens preflight khỏi tổng accounting.

## 1. Đầu vào và điều kiện bắt đầu

Đọc `docs/M3.md` và `docs/M3_LOCAL_TEST_REPORT.md` để xác định code/profile đã freeze, CLI thực và trạng thái nào đã kiểm/chưa kiểm. Nếu tài liệu hoặc code chưa sẵn sàng, báo thiếu và dừng phần phụ thuộc; **không tự viết production thay Codex**. Các tên CLI trong báo cáo cuối là căn cứ chạy, không tự bịa lệnh.

Đọc `docs/M2_PASSAGES.md`, `docs/plan/SOURCE_CHUNK_INDEX.md`, `docs/M3_QDRANT_DOCKER.md`, profiles M3, tokenizer lock và manifest M2.
- M2 passages: `artifacts/m2_passages_20261106_v1/`, seal SHA256 `0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6`.
- M2 navigation: `artifacts/m2_navigation_20261106_v3/`.
- Model/tokenizer `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`.

Production code, configs, Docker compose, raw sources, M0-M2 modules, sealed bundles, V1 và báo cáo lịch sử chỉ đọc. Không đọc nhãn/gold/evaluator/test sources; không tune bằng holdout.

## 2. Chỗ được ghi và cách báo lỗi

Tạo thư mục review mới `pipeline_v2/reviews/m3_ag_review_v1/` hoặc suffix mới nếu đã tồn tại. Code test, fixtures riêng, evidence, commands/receipts và reports do AG viết chỉ nằm trong thư mục này. Chạy tests Codex cung cấp được phép nhưng không coi chúng là toàn bộ kiểm độc lập.

Ngoại lệ cho output của CLI production khi chạy thử: được ghi vectors/ledger/progress/receipts vào run M3 đã plan được nêu trong `docs/M3.md`, hoặc một thư mục artifact M3 mới do `m3 plan` tạo. Đây là output test được phép, không phải quyền sửa manifest bất biến, code/config, M2 hay kết quả lịch sử. Không sửa run manifest/checksum để vượt guard code/profile drift. Nếu tạo run mới, ghi tên và lý do, không tự sao chép cache khác fingerprint để làm đủ counts.

Lỗi production phải có ID, severity, bản code/profile/hash, expected/actual, raw evidence, lệnh tái hiện và đề xuất sửa gửi lại Codex. Không sửa production, tự thay model/profile/backend, nâng dependencies để che lỗi hoặc reseal artifact gốc. Có thể sửa lỗi checker của chính AG; giữ attempt lỗi/retry và giải thích.

## 3. Review và tests local trước

Kiểm từ code thật và invariants, không dùng builder làm oracle duy nhất:
1. Pilot manifest deterministic, đúng size/scope, source/M2/tokenizer/model/code profile bound; stale source/config/code bị phát hiện. Không dùng labels/hardness để chọn pilot.
2. Document exact raw body, query instruction riêng; hash/input IDs/count khớp M2. Một processor token `<|endoftext|>`151643 tính vào full tokens, không tự đổi EOS hoặc nhân đôi instruction. No truncation ngầm; Unicode/BOM/CRLF/special literals và cap448.
3. Last-token pooling có mask, finite vectors/full2560dimensions/L2 norms; cache/DB fingerprint đúng input và runtime. Đúng shape chưa chứng minh đúng nội dung.
4. Cache và attempt ledger: committed batch không bị embed lại khi resume; partial write, corrupt shard, missing/duplicate IDs, stale fingerprint và lỗi/retry không bị tính success. Failure trước nhận response ghi usage unknown nếu chưa xác minh; không giả0. Fake faults ghi đúng simulated.
5. Qdrant REST server adapter: stable valid point IDs và passage mapping; collection mismatch không bị xóa/recreate ngầm, ingest idempotent, completeness kiểm ID/hash/profile universe chứ không chỉ counts. Lọc query case/profile trước cap.
6. BM25 giữ Unicode/citation digits/negation; corpus scope case/passages rõ ràng. Dense exact reference NumPy, ties/duplicate vectors xử lý đúng. Hybrid best passage -> unique cases -> RRF, không cộng mỗi overlap/child thành vote độc lập.
7. Search hit mở đúng M2 raw parent+neighbors theo source order, gồm marker nhảy/lặp/quoted/unknown, source boundary và unnumbered xen kẽ. Preview/diagnostic không thành M4 delivery hoặc semantic proof.
8. Không trộn pilot-ready với full-corpus-ready; không lộ credentials trong logs/receipts.

Sau local tests, nếu không có defect chặn thì tiếp tục pilot thật theo Section4. Không chạy lặp workload đã hoàn tất khi không có thay đổi/concern mới. Nếu có defect chặn remote, báo Codex sửa trước; không tự patch production rồi tiếp tục.

## 4. Chạy thử thật nếu cần, trên code Codex đã freeze

User đã cho phép tạo app/volume Modal mới, tải weights đúng revision và inference pilot; không đặt trần USD. Không xin lại quyền chỉ vì phát sinh chi phí pilot. Ghi requests/tokens/latency/retries. **Không embed toàn corpus**, không tự mở M4-M7.

Qdrant Docker local dùng compose đã chuẩn bị, image `qdrant/qdrant:v1.20.0`, REST `http://127.0.0.1:6333`, named volumes riêng. Kiểm server/client/image digest. Không dùng embedded/in-memory DB thay server rồi gọi integration PASS. Không sửa/xóa dịch vụ hoặc data không thuộc pilot. Modal không truy cập localhost máy cá nhân: orchestration local nhận vectors rồi ghi DB.

Chạy bằng CLI Codex trong `docs/M3.md`; không xây client/endpoint production khác. Có thể dùng run dir và collection review riêng theo CLI hỗ trợ; không overwrite run Codex. Collection/profile không khớp thì báo lỗi. Nếu Docker chưa chạy hoặc thiếu đăng nhập Modal, báo đúng thao tác user cần thực hiện; không yêu cầu gửi token trong chat.

Mặc định **tiếp tục run L4 hiện có**, không tạo run/collection mới nếu không có lý do. Nếu chưa có document batch nào, chạy lần lượt để kiểm stop/resume; nếu đã có batch thì kiểm cache/ledger rồi resume, không xóa để chạy lại:

```powershell
Set-Location E:/Git/coliee-case-retrieval
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal check
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal m3 run --run-dir pipeline_v2/artifacts/m3_pilot_20261106_l4_v1 --stop-after-batches 1
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal m3 run --run-dir pipeline_v2/artifacts/m3_pilot_20261106_l4_v1
& .venv/Scripts/python.exe -m pipeline_v2.deploy_modal m3 verify --run-dir pipeline_v2/artifacts/m3_pilot_20261106_l4_v1 --restore-test
```

Nếu collection `_restore` đã tồn tại thì không lặp restore hoặc xóa collection đó; kiểm receipt đã có và dùng `verify` không flag để kiểm tiếp. Tự chọn vài query fixture ngắn không dùng gold để chạy `deploy_modal m3 search`, mở source từ hits, lưu exact-reference results và test eligibility/unique-case. Với container Qdrant thuộc đúng compose project, restart service `qdrant` rồi `verify` lại để kiểm persistence, không restart Docker Engine hoặc dịch vụ khác. Giữ evidence trước/sau trong review và immutable CLI operations.

Các checks thật cần evidence:
- Remote/local token parity và singleton-vs-padded-batch behavior theo numerical tolerance công khai; raw documents không instruction, query prefix đúng một lần.
- Pilot1.024 real document vectors đúng manifest/profile. Nếu chỉ smoke subset thì gọi đúng smoke, không nhận full pilotPASS.
- Stop ở batch boundary rồi resume: không mất/duplicate data, không gọi lại committed inputs. Phân biệt cache reuse, inference retry và DB retry.
- Qdrant exact ID/hash membership, dense-vs-exact comparison, eligibility filters, BM25/hybrid smoke và mở raw context từ hit. Không suy gold F1 từ self-match/synthetic queries.
- Restart đúng container pilot giữ volume và kiểm persistence; nếu CLI/code có snapshot/restore, dùng collection test mới và kiểm ID/vector/profile. Không xóa collection gốc/volume để reset tests.
- Code thiếu tính năng đã cam kết thì ghi defect/limitation gửi Codex; không tự implement.

## 5. Bàn giao

Tạo `REPORT.md`, `findings.json`, `commands_and_results.json`, independent tests/scripts/results và evidence trong review dir. Ghi code/profile/source/image hashes, Modal app/volume, DB collection, run artifacts, counts, numerical checks, requests/input tokens (tách padding), failures/retries/unknown usage, cold/warm latency/throughput. Không lưu secrets. Development-chat tokens không biết thì unknown.

Kết luận tách hai trục `code_review` và `real_pilot_execution`. Dùng `pass_with_documented_limits`, `fixes_required` hoặc `insufficient_evidence` theo evidence; remote chưa chạy ghi `not_run`, không biến local mock PASS thành pilotPASS. Liệt kê lỗi cần Codex sửa theo ưu tiên. Legal semantics/retrieval/agent và COLIEE F1 chưa được chứng minh bởi pilot vận hành.
