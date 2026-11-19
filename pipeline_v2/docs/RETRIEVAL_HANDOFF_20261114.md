# Tiếp tục tối ưu retrieval trên máy còn lại

## Checkpoint bàn giao mới — 19/11/2026

**Đọc mục này trước các mục ngày 14/11 phía dưới.** Đây là checkpoint chuyển tiếp công việc đang làm, chưa phải nghiệm thu selector, CM4 live hoặc chất lượng COLIEE. Base trước commit bàn giao: `19283dc`, nhánh `main`. Ngày 19/11 đã fetch và xác nhận base local/remote khớp. Không ghi đè các sửa độc lập trên máy đích.

### Code đi cùng lần push này

- `agent_harness/selection.py`, `ledger.py`, `harness.py`, `m6.py`, `m6_live.py`: nối selector vào M6 live; tổng hợp assessment theo candidate; kiểm assessment còn active, không pending, evidence đã giao và khớp catalog/hash/source trước khi chốt prediction, kể cả khi raw đã rời payload. Selector mặc định yêu cầu citation A khớp identifier quan sát được trong header B. Đây là heuristic bảo thủ, không phải gold hoặc bộ nhận diện mọi loại citation.
- `adaptive_policy.py`, `m6.py`: tùy chọn `explicit_leads`, tool `open_retrieved_passage` mở đúng lead đang hiển thị và đúng source need. `read_case_passages` dùng focus cho tìm nội bộ khi bật chế độ này. Lead thường giữ handle đầu tiên thay vì âm thầm ghi đè bằng hit sau.
- `m6_hybrid.py`: M6 cho phép output đến 50 cases, tái tính cùng case-rank RRF từ channels hiện có khi yêu cầu hơn 20; không thêm lượt backend/embedding để mở rộng output. Default M6 config và mặc định CM4 khác nhau: CM4 không truyền settings riêng thì dùng search limit 50; settings truyền rõ vẫn được giữ.
- `assessment.py`: từ chối evidence A/B chỉ có whitespace; bổ sung mode `model_attribution` dùng trong thử nghiệm. `evidence.py`: chuẩn hóa tuple khi sort spans hỗn hợp list/tuple.
- `modal_qwen.py`: function pin local đang là `fu-JifUyUWll3lk5ctQEedpCW`. Pin này được chuyển nguyên trạng, **chưa xác minh deployment hiện tại trong đợt bàn giao**. Máy đích kiểm metadata trước inference, giữ function-ID guard.
- Chuyển toàn bộ source, tests, settings và tài liệu trong `experiments/uncapped_probe/`, `experiments/context_manager_v1/`, `experiments/context_manager_v2/`. Không chuyển bytecode hoặc run/cache. CM4 hiện là `cm4-anchor-flow-v23`; đọc `experiments/context_manager_v2/CM4.md`, `MODEL_CONTEXT_FLOW.md` và code hiện tại. Các tài liệu v1–v22 là checkpoint lịch sử, không phải chỉ dẫn resume run cũ với code v23.

### Trạng thái CM4 và khác biệt với M6 thường

CM4 nối source gate, đọc toàn query nếu vừa payload (không vừa thì điều hướng vùng), model view dùng mã ngắn, đọc lead/continuation theo cặp need–candidate, phản hồi pending và tool repair, search reuse, draft `issue/source_proposition/anchor_quote` có đường sửa hoặc xác nhận nguyên văn. Anchor khớp duy nhất được ánh xạ về raw offsets; trường hợp nhiều vị trí hoặc gần giống trả các đoạn nguyên văn để xác nhận trước retrieval. Chỉ `issue` đi vào retrieval; `source_proposition` là model annotation.

CM4 bật `model_attribution=True` và `model_support=True`: attribution/identity support dựa đánh giá model trên evidence; host vẫn kiểm refs, raw và phía A/B. Vì vậy không được mô tả CM4 là đã qua cùng heuristic citation/header của selector M6 mặc định. `supported`/`accepted` trong ledger không chứng minh nhãn COLIEE đúng.

Theo các tài liệu thử nghiệm, người dùng trước đó đã cho phép nhánh uncapped/RT4/RT5 và nối CM4; điều đó không nghiệm thu các gate RT3/context còn ghi ở dưới. Lần bàn giao này chỉ kiểm local và chuyển code, không inference/deploy. CM4 giữ cap mỗi lượt input 8.500/output 512; cumulative caps mặc định rất lớn (`2**60`), có loop guard, STOP và tùy chọn max-turns. Không xem profile này là pilot ngân sách nhỏ. `live.py` CM4 không nhận profile RT5 bounded.

### Kiểm lại ngày 19/11 và lỗi còn lại

Các lệnh đều dùng `.venv/Scripts/python.exe`; các lượt kiểm là local/offline, không chủ động chạy inference/deploy hoặc embedding mới.

- `-m unittest pipeline_v2.tests.test_source_selection pipeline_v2.tests.test_m6_hybrid -q`: **14 tests PASS**.
- `-m unittest discover -s pipeline_v2/experiments/context_manager_v1/tests -p 'test_*.py' -q`: **19 tests PASS**.
- `-m unittest discover -s pipeline_v2/experiments/uncapped_probe/tests -p 'test_*.py' -q`: **25 tests PASS**, có replay dựa dữ liệu/tokenizer/run local.
- `-m unittest discover -s pipeline_v2/tests -p 'test_m6*.py' -q`: **82 tests, FAILED (errors=6)**. Tất cả lỗi báo `AttributeError: 'AdaptiveHarness' object has no attribute 'explicit_leads'` trong `test_m6_v15_regression.py` (có hai subtest). Fixture tạo harness bằng `__new__` và không khởi tạo thuộc tính mới. Chưa sửa trong công việc bàn giao. Máy đích cần sửa fixture hoặc thiết kế default tương thích sau khi review; chạy lại đúng suite. Không báo M6 regression xanh từ kết quả 14 tests chọn lọc.
- `-m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q`: **109 tests PASS**, 69,210 giây. Đây là kiểm offline; chưa kiểm inference/deployment hoặc chất lượng ngữ nghĩa mới.

### Việc tiếp theo trên máy đích

1. Pull `main` sau khi cất/commit sửa local nếu có; đọc `AGENTS.md`, mục này và CM4.md. Review diff selector/evidence với công việc độc lập ở máy đích trước khi merge. Không reset hoặc chép đè cả module.
2. Sửa lỗi fixture M6 nói trên, chạy lại tests liên quan. Review sâu progress từng pair, draft cũ sau đổi focus/need và ambiguity của normalized anchor; tests PASS chỉ bao phủ tình huống đã kiểm, chưa đủ kết luận các invariants này đúng mọi đường.
3. Dùng raw/artifacts/tokenizer/vector cache/Qdrant máy đích đã có. Các `cache/...` và `pipeline_v2/reviews/...` chưa tracked ở máy nguồn không nằm trong push. Replay CLI, offline_acceptance và một số tests có dependency vào run local lịch sử; thiếu fixture thì ghi rõ thiếu/skip, không tạo receipt thay thế. Các báo cáo local cũ trong thư mục experiments giữ như tài liệu lịch sử và có thể trỏ tới evidence không chuyển.
4. Khi cần preflight CM4 mới, dùng namespace mới. Plan bind root/code/config/source nên không resume plan từ máy cũ hay version khác. `prepare` kiểm local, chưa gọi inference:

```powershell
$cmRun = 'cache/cm4-handoff-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $cmRun
```

5. Chỉ người dùng/AG chạy `live run --run-dir $cmRun` sau khi review preflight và deployment metadata. Codex không tự inference/deploy. STOP đặt tại `$cmRun/STOP`, chỉ có hiệu lực safe boundary; đang chờ call thì poll cùng call, không gửi trùng. Run/admission unknown phải giữ nguyên accounting, không reset để retry. Không dùng lệnh run namespace lịch sử trong tài liệu v1–v22 như lệnh chạy tiếp trên máy mới.
6. Chỉ mở rộng đánh giá sau gate tương ứng; giữ gold ngoài solver, không tự đổi model/chunk/reranker hoặc tune holdout. Báo retrieval → mở nguồn → assessment → selection riêng, cùng request/token/latency và errors/unknown.

### Prompt tiếp tục hiện hành

> Đọc AGENTS.md, CODEX_HANDOFF.md và checkpoint 19/11 trong pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md trước phần lịch sử. Pull/merge cẩn thận với sửa local. Tiếp tục selector M6 và thử nghiệm CM4 cm4-anchor-flow-v23; chưa coi đây là nghiệm thu live/semantic. Trước tiên xử lý 6 errors của fixture test_m6_v15_regression do thiếu explicit_leads, kiểm lại tests và review pair progress/draft/anchor ambiguity. Dùng code, settings và fixtures có thật; không yêu cầu hoặc dựng lại run cũ không chuyển. Giữ nguồn/hash/offset/provenance và unknown accounting. Codex chỉ code, local checks và chuẩn bị lệnh; người dùng/AG chạy inference/deploy. Không tự mở pilot hoặc mốc tiếp theo.

---

Cập nhật ngày 14/11/2026. Theo yêu cầu người dùng: chỉ chuyển code, tests và hướng dẫn cần thiết qua Git; **không cần chuyển các run/evidence thử nghiệm cũ**. Người dùng tiếp quản bước chạy và nghiệm thu tiếp theo.

## 1. Bắt đầu trên máy đích

1. Pull commit bàn giao, đọc `AGENTS.md`, `CODEX_HANDOFF.md`, file này và `pipeline_v2/docs/plan/M6_RETRIEVAL_OPTIMIZATION.md`.
2. Giữ các thay đổi selector/evidence đang làm trên máy kia. Merge/review theo diff, không copy đè cả module hoặc reset working tree.
3. Dùng `.venv/Scripts/python.exe`, dependencies đã pin. Dùng raw data, artifacts M0–M3 và vector cache máy đích đã có. Không embed lại hoặc sửa seals/hashes để vượt guard.
4. Chuẩn bị tokenizer local nếu thiếu:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m4_live prepare-tokenizer --tokenizer-dir cache/tokenizers/qwen36_27b_fp8
```

Code/profile/scripts cần thiết đi cùng commit; `.env`, tokenizers, vector cache, runtime artifacts và các run thử trước không đưa lên Git. Không cần các `local_verification.json`, acceptance receipts hoặc inventory cũ để khởi động công việc mới. Những đường dẫn run/receipt lịch sử trong PROGRESS/kế hoạch có thể chỉ tồn tại ở máy nguồn, không phải dependency cho run mới. Không tạo receipt thành công thay thế cho evidence không chuyển.

## 2. Trạng thái và quyết định hiện hành

| Phần | Trạng thái |
|---|---|
| RT1: lưu raw kết quả từng kênh ngoài prompt, link/hash và verifier | Đã nghiệm thu engineering cached corpus trên máy nguồn |
| RT2: tìm theo issue từ phần paragraph A bị cắt, giữ đúng visible span/hash | Đã nghiệm thu engineering scripted corpus trên máy nguồn |
| RT3: bản đồ A phân cấp, đọc/mở rộng mọi cấp, coverage qua receipts | Code/local PASS; còn cần review độc lập cuối |
| Context input 8.500 | Profile/source đã chuẩn bị; AG báo deploy v2 thành công nhưng canary unknown, chưa nghiệm thu live |
| RT4: mệnh đề debug và hướng dẫn query | Chưa triển khai |
| RT5: 5 embedding và pilot discovery | Chưa triển khai |

Hiện tại dùng profile **`pipeline_v2/reviews/m6_retrieval_rt3_ctx8500_v1/settings.json`**: input cap 8.500, context engine source 12.288, output 384, 8 request/actions, input tổng 68.000, total 71.072. Output contract tối đa 512; việc áp output 512 thuộc RT4, khi đó total 72.096 nếu vẫn 8 lượt. Embedding budget tách riêng.

Map allocation 2.400 trong tổng cap input, fanout tối đa 6, leaf target 1.024 byte, snippet target 96 ký tự. Chỉ heading/snippets literal có nguồn; không tóm tắt ngữ nghĩa trước. Không thêm ba nhóm đầu mối chọn đoạn vào prompt (đang để sau). Không thêm nhánh literal/identity mới đã bỏ khỏi kế hoạch; giữ tool citation cũ.

## 3. Canary chưa rõ: thông tin tối thiểu để tiếp quản

AG đã báo deploy app `coliee-qwen36-27b-fp8-l40s` version v2 exit 0 (5,515 giây). Deploy thành công chưa chứng minh engine GPU nhận context mới hoặc inference thành công.

Một canary được gửi với input đã đếm 8.500, output cap 64, retry 0, embedding 0:

- Call ID: `fc-01M7CBMZWGZDPFSPB4BBT9WB94`.
- Request ID: `527d2d3aa978649b7fb270847c11c96608e4942a4c887f65745e5b94be8adfc6`.
- Client hết chờ sau khoảng 18 phút 23 giây, `TimeoutError` → `modal_result_uncertain`, `cancel_requested=true`, trạng thái `unknown`.
- Actual model execution count/input tokens/output tokens/provider latency và cancel completion đều chưa biết; không ghi 0 chỉ vì không có output.

Người dùng không yêu cầu chuyển run cũ. Dùng call ID để đọc metadata/log hoặc thu kết quả của **call hiện có**, không spawn lại call đó. Nếu không còn truy được kết quả thì giữ unknown lịch sử và ghi rõ giới hạn; không dựng lại run cũ hoặc xóa dấu vết admission để gửi trùng. Người dùng tiếp quản quyết định thử canary mới theo ngân sách riêng.

Canary script dùng transport mặc định `wait_seconds=1080`, hết chờ thì yêu cầu cancel; M6 live dùng `wait_seconds=None` để poll cùng call. Cần review khác biệt này cùng startup/GPU/container logs trước khi quy lỗi cho context/OOM. Không có container sau timeout không đủ xác định nguyên nhân. Function ID guard không được bỏ; thay pin phải có metadata đối chiếu.

## 4. Kiểm mới có thể chạy trên máy đích

### RT3: không cần Qdrant/inference

Dùng `pipeline_v2/reviews/m6_retrieval_rt3_v1/AG_CHECK.md`. Các script code được chuyển, không phụ thuộc run lịch sử:

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -p 'test_m6*.py' -q
```

Bản local trước bàn giao đạt 73 tests (1 skip thiếu ledger lịch sử), 159 map pages trên ba nguồn và navigation giả lập 8 bước cộng đọc root trực tiếp. Đây là engineering, không phải recall/semantic model quality.

Review cuối đặc biệt: continuation vẫn tồn tại khi trim context; reload refs không bị xử lý như context dict; paired A/B giữ read routes; map giữ literal text từng vùng; chưa giao payload thì chưa tính đã đọc. Status node cần merge với `status_defaults` cấp trang. Root/internal/leaf phải đọc raw được, không bắt buộc xuống leaf. Stateless refs và resume giữ source/config binding.

### Profile 8.500 và context live

Dùng `pipeline_v2/reviews/m6_retrieval_rt3_ctx8500_v1/AG_CHECK.md`. Hướng dẫn có checkpoint canary unknown; không coi các lệnh ban đầu là yêu cầu tự retry. `prepare` local không gọi model, `context_canary run` là một request thật và phải do người dùng/AG thực hiện. Phối hợp app dùng chung với máy kia, không deploy ngắt call chưa rõ.

Không lặp kiểm hoặc deploy không cần thiết nếu đã có evidence phù hợp. Mỗi lượt mới dùng namespace mới và ghi tokens/request/latency/lỗi/unknown, không chỉnh reports cũ. Không push credential hoặc output chứa credential.

## 5. Sau khi gate RT3/context đạt

Chỉ sau khi người tiếp quản kiểm và nghiệm thu mới mở RT4, rồi dừng để xem kết quả trước RT5:

- **RT4:** thêm `source_proposition` do model diễn đạt, bắt buộc trong JSON action issue search, chỉ để debug; query vẫn từ `issue`, không ghép mệnh đề vào retrieval. Sinh cùng lượt, không thêm lượt model. Output 512; input 8.500/8 lượt thì total 72.096. Thêm hướng dẫn query giữ thuật ngữ phân biệt, tránh quá chung hoặc gộp nhu cầu; giữ tình tiết hữu ích. Kiểm schema/ledger/query/token và AG canary live.
- **RT5:** profile embedding tối đa 5 request, tổng 2.240 input token embedding; kiểm feasibility navigation/read/search trong controller cap. Freeze discovery pilot, chấm từng kênh/RRF/pool qua diagnostic RT1, giữ đủ denominator/lỗi/chi phí. Không đưa gold vào solver hoặc tune holdout.

Đừng đổi model/chunk/reranker/fusion/K/selector đồng thời rồi quy gain cho query/navigation. Giữ provenance raw/hash/UTF-8 spans, trạng thái unread/partial/unknown. Model annotations không phải passage gold. Protocol PASS không chứng minh đúng quan hệ pháp lý hoặc COLIEE recall.

## 6. Prompt tiếp tục

> Đọc AGENTS.md, CODEX_HANDOFF.md và pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md. Người dùng tiếp quản bước tiếp theo, không yêu cầu các run/evidence cũ. Code retrieval RT1/RT2 đã nghiệm thu engineering; RT3 chờ final review, context input 8.500 có deploy báo thành công nhưng call canary fc-01M7CBMZWGZDPFSPB4BBT9WB94 vẫn unknown. Giữ thông tin này, không tự resend. Dùng profile ctx8500, context source 12.288, output hiện 384. Merge với selector/evidence máy này cẩn thận, không ghi đè cả module. Tạo evidence mới khi cần và ghi rõ không tái kiểm được receipt lịch sử không chuyển. Sau nghiệm thu RT3/context mới triển khai RT4 rồi dừng gate, sau đó RT5. Codex chuẩn bị code/lệnh, người dùng/AG chạy deploy/inference; không tự thay model/chunk/holdout policy.
