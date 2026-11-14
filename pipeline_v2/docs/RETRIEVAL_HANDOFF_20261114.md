# Tiếp tục tối ưu retrieval trên máy còn lại

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
