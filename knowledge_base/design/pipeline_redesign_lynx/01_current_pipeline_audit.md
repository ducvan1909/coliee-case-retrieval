# Audit pipeline hiện tại

## Phạm vi

Audit dựa trên code và artifact V13–V15 trong checkout hiện tại. `knowledge_base/` đang là nội dung untracked, vì vậy kết luận gắn với filesystem snapshot này, chưa gắn với một commit lịch sử. Năm án calibration chỉ dùng để tìm lỗi; KOS, agent review và locked opportunity không được coi là gold.

## Kết luận

“Context quá dài” không phải nguyên nhân duy nhất và cũng không phải chẩn đoán tốt nhất. V15 chia input thành batch nhỏ nhưng gộp candidate discovery với materialization: 205 paragraph tạo 219 item, sau đó một schema toàn case tăng tới khoảng 189.170 ký tự và endpoint trả HTTP 400. Pipeline chuyển điểm nghẽn sang pha review.

Bốn lớp lỗi phải báo cáo riêng:

1. provider/transport;
2. endpoint, constrained decoding và schema;
3. workflow/control state;
4. semantic quality.

`completed` hoặc schema-valid chỉ xác nhận thực thi, không xác nhận coverage hay đúng nghĩa.

## Bảng lỗi

| Triệu chứng | Evidence | Pha | Kết luận | Tác động | Phép kiểm tra |
|---|---|---|---|---|---|
| `099980` V13 hoàn tất rỗng dù source có các cơ hội đã được review nhận diện | `pilot_v13_extract_before_navigate_local_scan/calibration/099980` | reading/selection | Omission ngữ nghĩa được quan sát; nguyên nhân workflow cụ thể còn là giả thuyết | Structured lane không có gì để tìm | Holdout blind review và coverage ledger theo paragraph |
| `013948` có issue question, AU gần trùng và attribution đáng ngờ | V13 final snapshot và review | classification/finalization | Schema-valid nhưng sai loại hoặc thừa | Tăng noise retrieval | AU omission/precision, duplicate và attribution metrics |
| `045155` thiếu current-court response witness cho treatment | V13 checkpoint | treatment | Evidence contract chưa được workflow bảo đảm | Treatment có thể phản ánh lời party/cited court | Bắt buộc authority witness + receiving-court witness hoặc `unknown` |
| Invalid constrained response | Một số run V13 | provider/schema | Lỗi giao thức; chưa xác định model hay schema | Tốn retry, phase không hoàn tất | Replay schema nhỏ và lưu raw response |
| Whitespace tới hết completion budget | V14 anchor/sentence experiments | constrained decoding | Output không hữu dụng; nguyên nhân sâu chưa xác định | Trả token nhưng không có quyết định | Probe schema thật, kiểm tra non-whitespace và fail-fast |
| Paragraph và sentence cùng được chọn | V14 selection diagnostics | schema/host validation | Parent-child dependency không được schema biểu diễn | Duplicate source và payload phình | Chỉ dùng một granularity mỗi request; host canonicalize |
| Small batch tìm đủ locked positives nhưng chọn heading; large batch bỏ reasoning/disposition | V14 diagnostics | selection | Batch size ảnh hưởng hành vi; review set không phải gold | Không chứng minh toàn-case recall/precision | Holdout có positives, negatives và omission review |
| Source/window được gửi lặp qua nhiều pha | V13/V14 journals | workflow | Mỗi item tự mở source, thiếu shared evidence queue | Token tăng mà evidence mới ít | Đo unique/repeated source chars và tokens |
| V15 chọn 202/205 paragraphs vào ít nhất một lớp, không dùng `refine_sentences` | V15 checkpoint | triage | Over-selection được xác nhận | Candidate filter gần như mất tác dụng | Candidate-only output, cap, negative sampling |
| V15 review có schema ~189k chars, endpoint payload ~244k chars và HTTP 400 không body | V15 failure analysis | selection review | Size explosion được xác nhận; size là nguyên nhân 400 vẫn là suy luận | Single-point failure trước classification | Binary search payload, preflight hard cap, paginated fixed schema |
| Heading được chọn `uncertain` dù reasoning nói không phải AU | V15 first triage | triage | Choice và rationale bất nhất | `uncertain` giữ lại rác | Không materialize uncertainty; đo calibration/abstention |
| Navigation dừng theo budget | V13/V14 | control | Budget control không phải coverage guarantee | Có thể complete khi còn source chưa xét | Báo `execution_status` và `coverage_status` riêng |
| Runtime retrieval interface chưa hiện thực | `knowledge_base/README.md` | sau build | Chưa có phép đo AU giúp Recall@K | Không thể khẳng định KB hữu ích | Xây source baseline và đánh giá lane độc lập |

## Bảng chi phí

Token dưới đây lấy từ trường `usage` của provider. Ký tự source/payload là phép đếm cục bộ, không phải token. Khoản reserve USD/request trong README không phải chi phí thực.

### Theo case

| Version/case | Requests thành công | Prompt | Completion | Tổng | Coverage/lặp source | Kết quả |
|---|---:|---:|---:|---:|---|---|
| V13 `013948` | 26 | 111.122 | 9.679 | 120.801 | ~99%; 164.583 source chars qua các pha | Complete, 5 AU; quality chưa đạt |
| V13 `045155` | 16 | 95.725 | 7.537 | 103.262 | ~98%; 163.665 source chars | Incomplete ở treatment |
| V13 `099980` | 11 | 78.950 | 3.835 | 82.785 | ~43%; 144.366 chars do window chồng/lặp | Complete nhưng empty |
| V14 `099980` | 18 | 93.095 | 13.359 | 106.454 | 7/14 window; 151.513 chars trên source 121.985 chars | Host-finalized empty |
| V15 `099980` | 60 + 1 HTTP 400 | 56.149 | 16.978 | 73.127 trước request lỗi | Triage hết source; review mang gần toàn source lần hai | Dừng trước classification |

### Theo experiment, gồm capability probes

| Experiment | Logical HTTP 200 | Transport attempts | Prompt | Completion | Transport latency |
|---|---:|---:|---:|---:|---:|
| V13 local scan | 62 | 82, gồm 20×503 | 290.446 | 23.149 | 128,84 s |
| V14 direct choices | 29 | 87, gồm 58×503 | 99.621 | 16.921 | 89,14 s |
| V15 two-stage | 71 + 1×400 | 102, gồm 30×503 và 1×400 | 58.115 | 19.640 | 162,02 s |

Các 503 là transport retry trong một logical request, không phải semantic repair. V15 dùng ít prompt token hơn V14 trên `099980`, nhưng không phải quality-equivalent saving vì run thất bại trước khi có output cuối.

## Cái đang làm đúng và nên giữ

- Raw source có SHA-256 và paragraph/sentence offsets ổn định.
- Cache identity gồm model, payload, response format và metadata.
- Checkpoint kiểm tra schema/prompt/source versions.
- HTTP 400 không được retry mù; 503 có bounded startup retry.
- Host giữ quyền tạo ID, apply operation và kiểm tra source refs.

## Thay đổi bắt buộc trong thiết kế mới

- Candidate không phải AU và không được materialize trước verification.
- Không sinh schema toàn case hoặc field cho từng source/item.
- Evidence queue dùng chung theo span/gap, tránh mỗi item đọc lại source.
- Execution, structural coverage, semantic quality và retrieval quality có status riêng.
- Raw-source retrieval tồn tại độc lập với mọi enrichment.
