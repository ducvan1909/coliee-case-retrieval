# Hai phép thử local: ưu tiên chung rồi context theo dependency

## Mục tiêu và ranh giới

Thử theo đúng thứ tự hai thay đổi đã được duyệt: (1) một danh sách ưu tiên chung thay multi-queue, giữ feature/context; (2) khóa danh sách đó và chỉ bổ sung context theo dependency hint. Chạy toàn nguồn năm án KOS-5 trước model. Không inference, Modal, tải model, train, NER/encoder mới hoặc sửa runtime/default/.env/source/spec04/05. Không mở reranker, NN–AU joining hay toàn corpus.

Tập đối chiếu vẫn là 18 artifact AU KOS, không phải gold/exhaustive. Hai án query không có AU KOS vẫn được xử lý; denominator 0 ghi NA. Không dùng query/candidate role, KOS kind/Claim/Evidence/Issue/gold để chọn vùng. Không tuning policy sau khi xem kết quả KOS-5.

## Đầu vào và bằng chứng trước thử

- [Kế hoạch 19](19_host_region_priority_offline_plan.md) và [kết quả trước](../../pipeline_v1/outputs/region_priority_offline_20261013/RESULT.md).
- `pipeline_v1/region_priority_offline/{core,features,scheduler}.py`: source-only features và region renderer/cost đã kiểm tra; không sửa các file này.
- `pipeline_v1/manifests/selected_kos_manifest.v1.json` và `G:/Legal-AI/kos_sample`: 61 file khóa hash, 18 AU alignment duy nhất.
- `pipeline_v1/outputs/source_store_v1`, manifests/policy Plan03/04: 431 block, 1.240 atom, 206.853 ký tự.
- `pipeline_v1/outputs/region_priority_offline_20261013/report.json`: baseline đối chiếu. Cost exhaustive cùng renderer mặc định là 247.339 token **ước lượng** bytes/4, không provider tokens.

Tạo module riêng `pipeline_v1/region_priority_variants/`, test riêng `tests/test_region_priority_variants.py`. Output mới `outputs/region_priority_variants_20261013/order/` rồi `context/`; giữ báo cáo/snapshot cũ và không ghi đè.

## Phương án 1 — Chỉ đổi scheduler

Giữ nguyên source/target inventory, toàn bộ feature và packet TARGET/CONTEXT, renderer/scaffold/cost. Chỉ thay thứ tự region bằng một danh sách chung; không ép luân phiên từng kênh và không xếp theo benefit/cost.

Khóa rule thứ tự trước khi tính coverage:

1. Tier 3 nếu có review cue; hoặc duty kết hợp rights/standard/qualification; hoặc fact + consequence + rationale.
2. Tier 2 nếu không đạt tier3 nhưng doctrine lane >=2, application lane >=3 hoặc reported authority >=2 theo feature có sẵn.
3. Tier 1 nếu chỉ có tín hiệu lane khác; tier0 nếu chưa có tín hiệu.
4. Trong cùng tier, dùng cue-control score có sẵn (citation + standard + duty + reporting đã saturation), rồi case ID/source offset để tie-break tái lập.

Các tier chỉ là heuristic để sắp thứ tự, không confidence đã hiệu chuẩn và không nhãn AU. Mọi block vẫn tồn tại; hết ngân sách giữ not_assessed. Không thêm diversity penalty hoặc semantic dedup. Khóa policy/feature/source/order SHA trước khi nạp KOS evidence và lưu báo cáo phương án1 trước khi chạy phương án2.

Đối chứng `source_order`, `cue_control`, `multi_queue` giữ packet baseline. So cùng **ngân sách tuyệt đối** được tính từ exhaustive baseline tại 10/25/50/75/100%, không lấy tỷ lệ exhaustive riêng của từng phương án.

## Phương án 2 — Khóa thứ tự, chỉ đổi context

Nhận snapshot/report phương án1; kiểm tra input identity, target spans, feature identity và thứ tự đầy đủ. Không xếp lại khi context làm packet dài hơn. Ghi selected IDs tại từng budget riêng, vì cùng thứ tự nhưng cost khác có thể mở ít target hơn.

Context mới được tạo từ raw-source features, không từ KOS audit:

- Khi qualification/reporting/open-quote cues yêu cầu, mở các block chứa atom lân cận đã được gợi ý, thay vì chỉ vài atom không đủ mạch văn. Đây là hint, không kết luận dependency semantic.
- Xét reference trong target và context đã mở, đi thêm tối đa một hop cho reference có ownership rõ thuộc cùng án, ví dụ `paragraph N of these reasons`.
- Reference thuộc án được trích, số paragraph chưa rõ ownership hoặc không có địa chỉ duy nhất giữ unresolved; không tự nối nó với `[N]` local.
- Union context trong packet, bỏ overlap TARGET, giữ nguyên TARGET. Dependency có ownership rõ được ưu tiên hơn mở rộng lân cận chung.
- Giữ trần 6.000 context characters/12 intervals như policy prototype trước. Không cắt giữa atom hoặc âm thầm bỏ phần cần mở; quá cap phải ghi residual/unknown.
- Không tạo global semantic graph/LegalUnit partition, không coi similarity là quan hệ dependency đã xác nhận.

Cost tính lại từ packet mới với cùng scaffold/renderer. Source hash/audit metadata không nằm trong packet thì không được cộng nhầm thành model prompt. Context gửi lặp giữa request vẫn được tính; không giả định model nhớ request khác.

## Kiểm tra và metric

### Cấu trúc/giao thức

- Full-source hash/offset/partition, đúng 431 block và KOS-5; không sửa nguồn.
- Phương án1: features, targets, packets/cost phải bằng baseline từng region; chỉ order khác.
- Phương án2: order/features/targets phải bằng snapshot1; chỉ context/cost thay đổi.
- Snapshot bị đổi policy/source/order/feature phải bị từ chối. References ngoài án không được tự resolve.
- Không semantic-dedup vùng khác phủ định/ngoại lệ; preview/name mutation checks không trở thành corpus-wide semantic claims.
- CLI test tự tạo output mới, không cần artifact tạo thủ công.

### Evidence và chi phí

- KOS alignment chỉ sau khi đã khóa selection; exact/whitespace-only, ambiguous/no_match giữ riêng.
- Full TARGET evidence coverage, CONTEXT exposure, partial spans, first-open cost, theo án/kind và diagnostic categories no-marker/application/exception.
- Curves cùng ngân sách tuyệt đối cho cả baseline và hai phương án, sensitivity bytes/3 và bytes/5. Đếm unknown source chars/regions và payload bytes chính xác.
- So bổ sung context trên **cùng tập target**: token/bytes tăng bao nhiêu, context hint nào được mở/không mở; tránh quy lợi ích do target khác thành context tốt hơn.
- Kiểm tra độc lập packet đầu chứa s27 ở source `[21]` có thêm phần điều kiện `[5]` thông qua reference ở `[20]` hay vẫn unresolved; cùng các tail/exception examples đã nêu ở kế hoạch19. Các ví dụ là probe đánh giá, không đầu vào selector.
- Có điều kiện nguyên văn trong packet không chứng minh speaker/treatment/interpretation đúng. Mở đủ KOS excerpt không chứng minh coverage toàn AU trong án.

## Phân công và cổng quyết định

Main khóa kế hoạch, review phép so cùng budget, giữ snapshot và tổng hợp kết quả. Implementer triển khai module riêng, chạy phương án1 rồi phương án2 tuần tự. Tester sở hữu test riêng, kiểm tra code cuối và CLI/report độc lập. Không hai agent sửa cùng file.

Formal PASS chỉ cho phép tin phép đo local. Nếu phương án1 không tốt hơn cue-control, báo không cải thiện; không đổi weights theo KOS. Nếu phương án2 mở đủ context hơn nhưng giảm TARGET coverage/tăng cost, báo cả hai mặt; không gọi đó là tối ưu token. Chưa chọn default/chạy model chỉ từ các kết quả này.

## Trạng thái

Đã triển khai và chạy hai bước local tuần tự trên toàn nguồn KOS-5. Bộ kiểm thử độc lập và lần chạy lại của Main: 22/22 PASS. Artifact nghiệm thu code cuối ở `knowledge_base/pipeline_v1/outputs/region_priority_variants_20261013/order/revision02/` và `context/revision02/`; báo cáo tổng hợp ở `RESULT.md`, hash/code bindings ở `ACCEPTANCE.json` trong thư mục output gốc này. Các báo cáo trước giữ nguyên làm lịch sử.

Ở ngân sách 50% baseline, ưu tiên toàn cục đạt 17/18 excerpt TARGET so với cue-control 15/18 và multi-queue 14/18, nhưng kém cue-control ở 10–25%. Context mới giảm TARGET 17→16/18, tăng CONTEXT 12→14/18 và tăng chi phí cùng tập target khoảng 15%; chi phí đọc hết tăng khoảng 12%. Dependency `[21]` tới điều kiện `[5]` còn unresolved trong packet `[21]`. Đây là phép đo offline trên KOS tham khảo, chưa chứng minh AU đúng ngữ nghĩa hoặc tiết kiệm token thực. Chưa chọn default, chưa gọi model hoặc triển khai hướng tiếp theo.
