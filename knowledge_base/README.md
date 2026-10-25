# Pilot V15: xét đoạn theo nhóm nhỏ, chỉ tách câu khi cần

`run` mặc định dùng `--reading-policy two-stage-candidates`,
`schema_version=15`, prompt `kb-pilot-v15-two-stage-triage-1` và experiment
`outputs/pilot_v15_two_stage_triage`. V14 và các experiment chẩn đoán được giữ
nguyên để đối chiếu.

Mỗi request triage nhận tối đa bốn đoạn nguyên văn và chỉ có khóa đoạn. Model
bắt buộc chọn `skip`, `uncertain`, `brief`, `aus`, `both` hoặc
`refine_sentences` cho từng đoạn. Chỉ các đoạn `refine_sentences` mới đi vào
request thứ hai; request này chỉ có khóa câu và không chứa khóa đoạn cha. Host
từ chối toàn batch nếu một đoạn refine không giữ ít nhất một câu. Do đó schema
không còn chỗ để chọn chồng lấn đoạn cha–câu con.

V15 không tự chạy `source_scan` cho item vừa tạo. Vòng sửa lựa chọn chỉ có thể
yêu cầu `scan_extend` hoặc `scan_reconsider` cho item hiện có. Cửa sổ đã xét
không được đọc lại trong pilot này. Classification, treatment và finalizer chỉ
nhận excerpt của item hiện có; code tiếp tục lấy nguyên văn và quản lý
ID/revision. `completed` chỉ là trạng thái thực thi và mọi kết quả vẫn mang
`quality_status=not_evaluated`.

Trước khi gọi case thật, chạy unit test, `compileall`, kiểm tra whitespace,
`preflight`, rồi `probe-v15 --execute` (11 request). Sau đó chỉ chạy mới
`099980`. Bốn cơ hội đánh giá trong `locked_opportunities.json` là agent review
ngoài pipeline, không phải gold và không được đưa vào prompt. Chỉ tiếp tục bốn
án còn lại khi `099980` giữ đúng ba cơ hội dương, bỏ heading và không có lỗi
kỹ thuật hoặc omission rõ.

# Pilot V14: xét từng ứng viên nguồn với schema ràng buộc

Sau kết quả `099980: completed / empty_output`, đã chạy đối chứng
`diagnose-v14-selection` để kiểm tra riêng lỗi chọn nguồn, không chạy lại
builder. Experiment
`outputs/pilot_v14_selection_diagnostic_contract_fix` khóa trước bốn đoạn thật từ `099980`
trong `locked_opportunities.json`: heading đối chứng âm, quy tắc/điều kiện,
lập luận của tòa và disposition. Nhãn này là **agent review, không phải gold**;
không gửi vào payload model. Bốn request giữ nguyên model, tham số và system
prompt, so nhóm 4 đoạn với nhóm 31 đoạn từ request V14 đầu, mỗi nhóm dùng
schema chỉ chọn đoạn hoặc schema chọn đoạn+câu. Raw response, token,
`finish_reason` và lựa chọn được lưu riêng. `complete` ở đây chỉ xác nhận đủ
bốn response hợp giao thức; không có nghĩa chọn đúng. Trần dự phòng nội bộ
hiện là 1,00 USD cho bốn request ở mức 0,25 USD/request; không phải chi phí
Modal thực tế. Không đưa kết quả đối chứng này vào KB.
Đợt chẩn đoán đầu tiên ở `outputs/pilot_v14_selection_diagnostic` dừng sau
hai request: nhánh đoạn tìm được ba cơ hội dương nhưng chọn nhầm heading;
nhánh đoạn+câu chọn chồng lấn cha–con vì prompt đối chứng thiếu hướng dẫn
quan hệ này. Giữ artifact đó và dùng experiment mới cho phép thử đủ bốn nhánh.
Đợt thứ hai ở `outputs/pilot_v14_selection_diagnostic_contract_fix` vẫn bị
chồng lấn cha–con ở nhánh P/S dù prompt đã nói rõ; hai nhánh nhỏ được giữ.
`diagnose-v14-selection --large-only --execute` chỉ gọi hai nhánh nhóm lớn
trong `outputs/pilot_v14_selection_diagnostic_large_only` với cùng prompt,
schema, nguồn và tham số; không phát lại hai nhánh nhỏ.
Kết quả bốn nhánh: nhóm nhỏ/chỉ đoạn nhận 3/3 cơ hội dương và bỏ đúng heading;
nhóm lớn/chỉ đoạn nhận 1/3, bỏ sót lập luận về chi phí và disposition. Cả hai
nhánh đoạn+câu đều vi phạm quan hệ cha–con; nhóm lớn còn gắn disposition thành
AU. Cả bốn response có `finish_reason=stop`. Đây là một lần chạy có kiểm soát,
không đủ để quy lỗi duy nhất cho kích thước nhóm; schema hiện cũng chưa ràng
buộc được quan hệ cha–con trong lúc sinh. Không đưa kết quả chẩn đoán vào KB.

Trước khi sửa thêm pipeline sau lỗi sinh khoảng trắng ở probe chọn câu, dùng
`python -m knowledge_base diagnose-v14-choices --execute` trong experiment
`outputs/pilot_v14_choice_diagnostic`. Hai request có cùng model, tham số,
system prompt và nguyên văn nguồn; request đầu chọn cả đoạn bằng một khóa,
request sau chọn hai câu bằng hai khóa do code cấp. Đây là phép thử năng lực
endpoint, **không** tạo KB và không thay cổng 11 probe V14. Nếu nhánh câu còn
bị cắt, giữ raw response và không chạy calibration. Chỉ sau khi phép thử đạt
mới thiết kế lại hợp đồng pipeline theo dạng đã chứng minh, tạo fingerprint
mới, chạy đủ cổng 11 probe rồi mới chạy `099980`.

`run` mặc định dùng `--reading-policy audited-candidates`, `schema_version=14`,
prompt `kb-pilot-v14-anchored-triage-3` và experiment
`outputs/pilot_v14_direct_choices_scan_fix`. V13 và các lần thử V14 trước ở
`outputs/pilot_v14_anchor_triage`, `outputs/pilot_v14_sentence_schema_fix`
được giữ nguyên. Hai lần thử trước dừng tại probe chọn câu: model sinh khoảng
trắng đến giới hạn token. Phép thử độc lập tại
`outputs/pilot_v14_choice_diagnostic` cho thấy cùng nguồn, model trả được cả
quyết định đoạn và hai quyết định câu khi mỗi ID là một ô trực tiếp. Bản này
dùng `choices` với khóa P/S do code cấp; host từ chối chọn chồng lấn đoạn–câu.
Lý do chọn nguồn trong audit là mã do host ghi, **không** phải diễn giải pháp lý
của model.
Mỗi request xét nguồn yêu cầu quyết định `skip`, `uncertain`, chọn cả đoạn,
hoặc chọn theo từng câu cho **mọi đoạn vừa cấp**; model không tự viết danh sách
ID hay `new_items`. Code tạo item từ anchor được chọn và trích nguyên văn.
Nguồn đoạn chỉ gửi một lần trong payload; câu mang ID và tọa độ, không lặp
văn bản. Schema động được lưu trong journal và gửi qua `response_format`,
không lặp trong nội dung prompt gửi model.

Điều hướng chỉ nhận catalogue gọn của cửa sổ còn chọn được; nguồn chưa đọc
được ghi là chưa biết. Rà nguồn phân biệt `extend` và `reconsider`, gom các
item dùng chung nguồn vào một request và giữ trần 24 request rà/án. Khi không
có item, host bỏ qua phân loại, treatment và chốt; output rỗng hay `uncertain`
vẫn phải được đánh giá omission ngoài pipeline. Kết quả xây xong luôn mang
`quality_status=not_evaluated`.

Trước khi chạy Modal: unit test, `compileall`, kiểm tra khoảng trắng,
`preflight`, rồi `probe-v14 --execute` (11 request gồm nhánh câu và cửa sổ
lớn). Chạy mới `099980` trước;
chỉ tiếp tục bốn án còn lại nếu kết quả kỹ thuật đạt và không có omission rõ.
Trần an toàn là 45 request/án cộng 11 probe. Với 0,25 USD/request, trần năm án
là 59 USD **dự phòng nội bộ**, không phải chi phí Modal thực tế. Chưa mở 20 án
hoặc triển khai retrieval.

# Pilot V13: xét nguồn rồi mới quyết định đọc tiếp

Nhánh V13 dùng `--reading-policy candidate-separated`, `schema_version=13`
và experiment `outputs/pilot_v13_extract_before_navigate_local_scan`.
Lần thử đầu của V13 được giữ tại `outputs/pilot_v13_extract_before_navigate`:
reader tạo năm AU nhưng lượt rà nguồn bị bác do chọn cả đoạn và câu con.
Trong lần sửa này, host chỉ đưa các địa chỉ cùng độ hạt trong một đoạn văn
cho mỗi lượt rà; đoạn chưa có nguồn đã chọn được đưa dưới dạng đoạn văn để
giảm số request. Các nguồn đã chọn trước đó vẫn nằm trong tập ứng viên.
Lần thử trung gian `outputs/pilot_v13_extract_before_navigate_overlap_fix`
giữ log 5 AU và lỗi ghi sổ ngân sách trên Windows.
Lần thử `outputs/pilot_v13_extract_before_navigate_compact_scan` giữ log
HTTP 400 khi schema phân loại tăng theo bình phương số nguồn. Schema mới
gán vai trò cho từng nguồn bằng một bảng; host kiểm tra đúng một `primary`.
Lần thử `outputs/pilot_v13_extract_before_navigate_linear_classification`
dừng đúng trần 24 lượt rà: mỗi AU cũ được đề nghị rà gần toàn bộ nguồn mới mở.
Lượt sửa V13 hiện chỉ cấp các đoạn liền kề nguồn của AU đó; nội dung xa được
xem xét như một mục mới.
Mỗi nhóm nguồn mở
được xét để tạo/sửa brief và AU bằng anchor; sau khi các nhóm `source_scan`
hoàn tất, một request riêng quyết định đọc tiếp hay kết thúc pha. Response xét
nguồn bắt buộc ghi `batch_assessment` kể cả khi không tạo mục. Quyết định điều
hướng không có quyền tạo mục.

Lượt sửa lựa chọn đầu tiên được cấp lại nhóm nguồn vừa xét gần nhất cùng ngữ
cảnh của các mục hiện có. Điều này giữ nguồn để xem xét omission ngay cả khi
reader chưa tạo mục nào. Nguồn được gửi theo nhóm tối đa hai cửa sổ, không gửi
lại toàn bộ lịch sử. `case.json` và report ghi riêng số nhóm nguồn đã cấp và
đã xử lý; `completed` vẫn mang `quality_status=not_evaluated`.

Trước khi chạy án, dùng `probe-v13 --execute` để kiểm tra chín cấu trúc schema
trên endpoint. Trần với sáu bước mở rộng và 24 lượt rà nguồn là 45 request/án,
cộng chín probe. Năm án tương ứng 234 request hay 58,50 USD dự phòng nội bộ
ở mức 0,25 USD/request; đây không phải chi phí Modal đo được. Chạy `013948`
trước và xem trực tiếp các mục cùng log, sau đó mới tiếp tục năm án calibration.

# Pilot V12: chọn nguồn theo từng nhóm ứng viên

Nhánh V12 dùng `--reading-policy candidate`, `schema_version=12` và
experiment `outputs/pilot_v12_candidate_selection`. Đây là bản chạy mới; dữ
liệu V10/V11 không được chuyển thành kết quả V12. Chính sách đọc theo marker và
heading của V11 vẫn giữ nguyên.

Reader và lượt sửa lựa chọn tạo mục bằng **một** `anchor_source_id`; khi cần
đổi nguồn của mục cũ, model chọn `scan_sources`. Host cung cấp tối đa 12 nguồn
ứng viên mỗi request, gắn khóa `C0`…`C11`; model trả `include` hoặc `exclude`
cho từng khóa bắt buộc. Host tích lũy lựa chọn qua các nhóm rồi mới cập nhật
`source_refs` một lần. Các nguồn gần anchor đã được cung cấp có thể được rà
ngay cho mục mới. Không có mảng ID nguồn để model tự sinh và không đặt trần cố
định cho **tổng số nguồn trong một mục**. Treatment cũng dùng quyết định theo
từng nguồn đã chốt, không dùng mảng ID bằng chứng.

Danh sách ứng viên vẫn bị giới hạn bởi nguồn thực sự đã gửi trong request hoặc
nguồn đã chọn của mục; bản xem trước catalogue không thành bằng chứng. Giới
hạn an toàn `KB_MAX_SOURCE_SCAN_REQUESTS=24` tính theo case: nếu chạm giới hạn
khi còn ứng viên, case mang trạng thái `incomplete`, không âm thầm cắt nguồn.
Giới hạn này khống chế số request/chi phí, không phải quota nguồn cho một AU.
Có thể điều chỉnh sau khi đo số nhóm thực tế, nhưng thay cấu hình sẽ tạo
fingerprint khác. Schema hợp lệ chỉ xác nhận cấu trúc; chất lượng ngữ nghĩa
vẫn cần đánh giá đầu ra cuối.

Trước khi gọi Modal: chạy unit test, `compileall`, `preflight`, sau đó
`probe-v12 --execute` để kiểm tra endpoint có thực thi cấu trúc mới. Chỉ chạy
án calibration khi các bước đó đạt. Chưa mở 20 án hoặc kết luận chất lượng.

# Pilot V11: đối chứng chính sách đọc

Nhánh V11 dùng `--reading-policy guided` và experiment
`outputs/pilot_v11_reading_guided`. Dùng `--reading-policy v10` cho control
`outputs/pilot_v11_reading_control`; nhánh này giữ prompt, schema và quyết định
đọc V10. Mỗi nhánh chạy mới trên năm án calibration, cùng model và cấu hình.

Guided đưa heading và vị trí `<FRAGMENT_SUPPRESSED>` vào catalogue để định hướng
chọn cửa sổ. Reader và sửa lựa chọn trả `reading_decision`: `read` nêu cửa sổ
và mục đích, hoặc `finish_phase` ghi lý do, nhu cầu còn thiếu và đánh giá đủ
các cửa sổ chưa đọc. Tối đa bảy yêu cầu mở nguồn dùng chung, tối đa hai cửa sổ
mỗi lần; đọc lại cửa sổ cũ cũng tính một yêu cầu. Marker/preview không phải
bằng chứng AU. `source_navigation.json` giữ tọa độ marker/heading đầy đủ;
`reading_history` ghi quyết định và ngân sách còn lại. `completed` vẫn có
`quality_status=not_evaluated`.

Trước khi gọi endpoint, đọc `V11_SOURCE_INVENTORY.md`, chạy unit test,
`compileall`, `git diff --check` và `preflight`. Kiểm tra năng lực bằng
`probe-v10` cho control và `probe-v11` cho guided. Chạy từng án trong cùng cặp
theo thứ tự `099980`, `013948`, `045155`, `011904`, `013009`, đảo thứ tự hai
nhánh giữa các cặp. `report`, `compare` và `adjudication` nhận `--experiment`
để xuất từng nhánh riêng. Chưa mở split evaluation.

Trần là 12 request án/case mỗi nhánh. Năm án, hai nhánh và 3+5 probe có trần
128 request, tương ứng 32 USD dự phòng nội bộ ở mức 0,25 USD/request; số đó
không phải chi phí Modal đo được. Đánh giá AU từ nguồn và KB cuối trước khi xem
log lựa chọn, dùng danh sách cơ hội AU làm tham chiếu agent review, không coi
KOS hoặc V10 là gold.

# Pilot V10: lựa chọn theo schema từng pha

Nhánh control dùng `schema_version=10`, prompt `kb-pilot-v10-scoped-source-2`.
Experiment lịch sử là `outputs/pilot_v10_scoped_source_probe_fix`. Host tạo JSON Schema từ nguồn và item của từng request, gửi bằng
`response_format=json_schema`, rồi kiểm tra lại response trước khi cập nhật
trạng thái. Model trả lựa chọn theo handle; code tạo ID, revision, operation,
nguyên văn và nhật ký. Reader và lượt sửa lựa chọn có quyền chọn nguồn; sau đó
nguồn được chốt. Phân loại, treatment và finalizer chỉ nhận lựa chọn thuộc
nhiệm vụ của mình. Response không hợp lệ khiến case `incomplete`; không gọi
model sửa giao thức. `completed` vẫn có `quality_status=not_evaluated`.
Mỗi request chỉ mang nguồn mới mở và đoạn đã đọc cần để xét các item hiện tại
(đoạn được chọn, đoạn cha và đoạn văn liền trước/sau nếu đã mở). Catalogue chỉ
liệt kê cửa sổ chưa đọc; preview không cho phép chọn nguồn. Schema chỉ cho chọn
handle được cung cấp đầy đủ trong request, và coverage dựa trên nguồn thực sự
được gửi. Giới hạn này giảm context nhưng có thể bỏ sót nguồn cũ từng đọc mà
chưa được chọn vào item; đó là điểm cần kiểm tra khi đánh giá omission.

Kiểm tra endpoint và chạy năm án theo cổng kỹ thuật:

```powershell
python -m unittest discover -s knowledge_base/tests -q
python -m compileall -q knowledge_base
git diff --check
python -m knowledge_base preflight
python -m knowledge_base probe-v10 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 099980 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 013948 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 045155 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 011904 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 013009 --execute --retry-provider-unavailable
python -m knowledge_base report
python -m knowledge_base compare
python -m knowledge_base adjudication
```

Chỉ chạy án tiếp theo khi án trước đã tới finalizer, không còn lỗi giao thức và
mọi excerpt/vị trí khớp nguồn. Nếu endpoint không thực thi schema, dừng ở
`probe-v10` và giữ artifact. Các output V9 vẫn là dữ liệu đối chiếu.

Lần xác nhận đầu của `pilot_v10`: ba probe schema đạt; `099980` dừng tại lượt tiếp
nối sửa lựa chọn vì response bị cắt ở `max_tokens=4096`. Bốn án còn lại chưa
chạy. Xem `V10_RUN_STATUS.md` trước khi khởi động experiment mới; không resume
`pilot_v10` bằng mã/prompt khác. Bản đóng gói nguồn gọn hơn từng tạo
`pilot_v10_scoped_source`, nhưng dừng trước khi xử lý án vì ID probe trùng
với experiment cũ trong sổ ngân sách dùng chung. ID probe hiện gắn experiment
và fingerprint; năm án đã chạy trong `pilot_v10_scoped_source_probe_fix`.
Tất cả tới finalizer và qua kiểm tra nguyên văn, nhưng Codex review ngoài
pipeline tìm thấy lỗi lựa chọn và nhãn ngữ nghĩa. Xem
`outputs/pilot_v10_scoped_source_probe_fix/V10_CODEX_REVIEW_COMPARISON.md` và
`adjudication_codex_review.json`; đây không phải human gold.

## Lịch sử pilot V9

CLI hiện chạy `schema_version=9`, prompt `kb-pilot-v9-operation-repair-2` và
experiment `outputs/pilot_v9_operation_fix`. Protocol repair hướng dẫn riêng theo lỗi control,
lỗi operation hoặc cả hai. `error_id` của control không được dùng làm
`rejection_id` trong `repairs[]`. Khi finalizer chưa hoàn tất, `output_status`
là `incomplete`; `empty_output` chỉ mô tả KB cuối rỗng hợp lệ. Số item đang
lưu vẫn có trong case/checkpoint để kiểm tra bản nháp.

Mỗi bản sửa operation phải chọn rõ `resolution=replace|withdraw`. Hợp đồng sửa
được dùng chung bởi prompt và validator. Mọi handle trong hai danh sách bằng
chứng treatment phải đồng thời có trong `source_refs`; lỗi chỉ rõ danh sách và
handle còn thiếu. Hai experiment V9 cũ được giữ nguyên để đối chiếu.

Lần xác nhận mới của `099980` trong `outputs/pilot_v9_operation_fix` vẫn dừng
trước finalizer do một lỗi khác: host đưa đường dẫn phần tử
`item_checks[2]` vào danh sách trường top-level được phép sửa trong
`control_patch`. Bốn án còn lại chưa được gọi. Xem `V9_RUN_STATUS.md`; không
resume hoặc chạy lại experiment này bằng một fingerprint khác.

## Lịch sử pilot V8

V8 đã chạy `schema_version=8`, prompt `kb-pilot-v8-protocol-semantic-1`,
experiment `outputs/pilot_v8`. Luồng gồm đọc, sửa lựa chọn nguồn, sửa
kind/role/attribution, sửa treatment, rồi chốt. Mỗi lượt sửa ghi quyết định
cho từng item trong `item_checks`; đó là nhật ký quá trình, không phải kết quả
thẩm định pháp lý. `quality_status=not_evaluated` sau khi hoàn tất.

Lần chạy thật đầu tiên của `099980` dừng ở `incomplete_protocol`; bốn án còn
lại chưa chạy. Xem `V8_RUN_STATUS.md` trước khi dùng các lệnh chạy dưới đây.

Response không parse được phải được thay bằng một response đầy đủ hợp lệ trước
khi áp dụng thao tác. Lỗi trong protocol repair làm case dừng. Khi còn cửa sổ
chưa đọc, lượt sửa lựa chọn mở một lần tối đa hai cửa sổ và xử lý ở lượt tiếp
nối. Hai lượt sửa phân loại dùng chung tối đa một cơ hội đọc bổ sung.

Chạy kiểm thử và preflight trước khi gọi Modal:

```powershell
python -m unittest discover -s knowledge_base/tests -v
python -m compileall -q knowledge_base
git diff --check
python -m knowledge_base preflight
```

Chạy mới theo thứ tự năm án trong cùng fingerprint:

```powershell
python -m knowledge_base run --split calibration --case-id 099980 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 013948 --case-id 045155 --case-id 011904 --case-id 013009 --execute --retry-provider-unavailable
python -m knowledge_base report
python -m knowledge_base compare
python -m knowledge_base adjudication
```

Kiểm tra `099980` trước khi tiếp tục. Dữ liệu V7 giữ nguyên; xem
`V7_PROTOCOL_AUDIT.md` để biết vì sao báo cáo kỹ thuật V7 trước đây sai.
Chỉ số AU toàn corpus, NN và Workspace vẫn thuộc giai đoạn retrieval sau.

## Lịch sử pilot V7

CLI hiện dùng `schema_version=7`, prompt `kb-pilot-v7-au-priority-1` và
`outputs/pilot_v7_au_priority`. Reader ưu tiên AU chứa quy tắc, điều kiện,
áp dụng, đánh giá chứng cứ hoặc lập luận tố tụng có thể giúp NN tương lai tìm
Case. Brief giữ tình tiết, tư thế tố tụng, vấn đề và kết quả. Một câu chỉ công
bố biện pháp cuối thuộc `disposition`; lập luận gần phần quyết định vẫn có thể
thành AU. `treatment=unknown` hợp lệ nếu AU không khẳng định cách tòa xử lý
authority khác.

Trong protocol repair, mỗi thao tác bị bác phải được `replace` hoặc `withdraw`
có lý do. Host ghi riêng thao tác đã áp dụng, duplicate noop, thao tác rút lại
và lỗi chưa giải quyết. Rút lại không sửa item active. `completed` vẫn có
`quality_status=not_evaluated` cho đến khi đánh giá đầu ra cuối.

```powershell
python -m unittest discover -s knowledge_base/tests -v
python -m compileall -q knowledge_base
python -m knowledge_base preflight
python -m knowledge_base run --split calibration --case-id 099980 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 013948 --case-id 045155 --case-id 011904 --case-id 013009 --execute --retry-provider-unavailable
python -m knowledge_base report
python -m knowledge_base compare
python -m knowledge_base adjudication
```

Chỉ chạy bốn án còn lại nếu `099980` đã tới finalizer và không còn lỗi giao
thức. Chỉ mục nguồn/AU toàn corpus, NN và Workspace là phần retrieval tiếp
theo; pilot này chỉ xây KB. Các experiment V6 vẫn là lịch sử đối chiếu.

## Ghi chú về pilot V6 trước đây

V6 giữ mô hình trích xuất: agent chỉ chọn địa chỉ nguồn và nhãn; code lấy nguyên
văn, kiểm tra handle, quản lý revision, lịch sử và trạng thái. V6 không gọi model
verifier và không gắn `accepted/rejected` trong lúc xây KB. `completed` chỉ có
nghĩa pipeline đã chạy hết; chất lượng luôn là `not_evaluated` cho đến khi có
đánh giá ngoài pipeline.

Luồng V6:

```text
đọc và tạo bản nháp
→ sửa lựa chọn nguồn
→ sửa phân loại và tính nhất quán
→ chốt KB cuối
→ đánh giá ngoài pipeline
→ truy nguyên lỗi bằng log
```

V5 và các kết quả cũ vẫn nằm trong các thư mục `outputs/pilot_v*` tương ứng. Mã
V5 được giữ trong `pipeline.py`, `prompts.py`, `schema.py` và `state.py`; đường
chạy CLI mặc định dùng các module `*_v6.py` và `outputs/pilot_v6_protocol_fix`.
Case `013948` trong experiment mới kế thừa reader và lượt sửa lựa chọn từ
`pilot_v6` với prompt cũ; các request tiếp theo dùng prompt mới. Đây là
calibration có thay đổi prompt giữa lượt, không phải so sánh prompt đồng nhất.

## Cấu hình và chạy

Sao chép `.env.example` thành `.env`. `KB_REPAIR_MODEL` là tùy chọn và mặc định
bằng `KB_READER_MODEL`. V6 không cần `KB_VERIFIER_MODEL`.

```powershell
python -m unittest discover -s knowledge_base/tests -v
python -m compileall -q knowledge_base
git diff --check
python -m knowledge_base preflight
python -m knowledge_base run --split calibration
python -m knowledge_base recover-v6
python -m knowledge_base recover-v6 --execute
python -m knowledge_base recover-v6-revision
python -m knowledge_base recover-v6-revision --execute

python -m knowledge_base run --split calibration --case-id 013948 --execute --resume --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 045155 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 011904 --case-id 013009 --execute --retry-provider-unavailable
python -m knowledge_base run --split calibration --case-id 099980 --execute --retry-provider-unavailable

python -m knowledge_base report
python -m knowledge_base compare
python -m knowledge_base adjudication
```

Lệnh `run` không có `--execute` chỉ kiểm tra cohort và in dự toán request. HTTP
503 được retry trong thời gian chờ cấu hình. Timeout hoặc mất kết nối có trạng
thái không rõ không được tự phát lại. `--recheck-verifier-errors` bị từ chối rõ
ràng trong V6 vì V6 không có verifier.

`recover-v6` mặc định chỉ xem trước. Khi thêm `--execute`, lệnh kiểm tra nguồn,
fingerprint, cache và ledger rồi sao chép case `013948` sang experiment mới, đánh
dấu một `add` trùng chính xác là `resolved_noop_duplicate`, và đặt checkpoint ở
vòng sửa phân loại. Lệnh không gọi Modal hoặc sửa ledger; chạy lại không tạo thêm
sự kiện. Dữ liệu `pilot_v6` gốc vẫn được giữ để truy nguyên.

`recover-v6-revision` phục hồi ngoại tuyến thao tác `defer` có revision đã được
model sửa trong cache của `045155`. Lệnh mặc định chỉ xem trước, kiểm tra nguồn,
snapshot, cache và ledger; chế độ `--execute` áp dụng đúng một lần, lưu bản cấu
hình cũ trong `config_history` và không gọi API hoặc cộng dự phòng.

Trong lần chạy thực tế, `011904`, `013009`, `013948`, `045155` hoàn tất về kỹ
thuật; `099980` còn lỗi giao thức. Lần thử cứu hộ riêng ở
`outputs/pilot_v6_protocol_fix_control_retry` dùng prompt `...fix-2` và vẫn
còn một AU bị bác do trùng source ref trong bản sửa. Không gộp hai experiment
thành một kết quả đồng nhất hoặc coi các mục còn lỗi là KB cuối đã đạt.
Sau khi tăng prompt lên `...fix-2`, fingerprint của experiment gốc không còn
khớp mã hiện tại; không dùng `--resume` trên đó nếu chưa tạo một bước kế thừa
có kiểm toán mới.

## Hợp đồng và vòng sửa

`schema_v6.py` là hợp đồng duy nhất cho prompt và host. Brief và AU tách schema;
`treatment` chỉ thuộc AU. Mọi thao tác cần lý do ngắn. Ngoài `add`, `update` và
`remove`, V6 có:

- `defer`: chuyển item khỏi KB cuối sang `unresolved_items`;
- `restore`: đưa item deferred trở lại KB;
- `remove`: xóa rõ ràng và giữ item trong `deleted_items`.

Một `add` hợp lệ trùng hoàn toàn item active được ghi riêng là
`resolved_noop_duplicate`, chỉ tới ID và revision của item đã có. Nó không cấp
ID mới, sửa item, hoặc tính là tiến triển của vòng đọc. `add.item` không chứa
ID/revision; host cấp các trường này.

Sửa giao thức cho `action` và `read_window_ids` như một cặp khi lỗi cửa sổ
phụ thuộc action; không tự đổi `read` thành `complete`. Một lượt sửa vẫn không
được mở nguồn mới, và lỗi chưa sửa được giữ nguyên trong báo cáo.

Lượt sửa lựa chọn nguồn được xem toàn bộ item, nguồn đã chọn và ngữ cảnh
cha/trước/sau. Lượt sửa phân loại nhận thêm bảng
`source_id → item, role, attribution, kind, treatment` và ví dụ đối chiếu tổng
hợp. Mỗi lượt có một request chính; khi thật sự cần có thể mở tối đa hai cửa sổ
và có đúng một request tiếp nối. Lượt chốt chỉ dùng nguồn đã được cung cấp.

Agent không trả quote, claim, summary hoặc nội dung AU. Handle `P####`/`S####`
chỉ hợp lệ trong manifest của request. Kết quả lưu ID ổn định gắn với hash nguồn
và tọa độ ký tự. Host materialize nguyên văn; đoạn cha và câu con không thể cùng
được chọn trong một item.

## Checkpoint, log và đầu ra

Trước mỗi request, checkpoint lưu prompt, payload, nguồn đã cung cấp, snapshot
đầu lượt và request identity. Sau response, checkpoint lưu response thô, thao tác
hợp lệ/bị bác, trạng thái trước/sau và dấu đã áp dụng. Resume dùng lại payload đã
lưu và cache đúng identity; thao tác đã áp dụng không được phát lại.

Các snapshot bất biến được ghi tại:

- `snapshots/draft_after_reading.json`;
- `snapshots/after_selection_repair.json`;
- `snapshots/after_classification_repair.json`;
- `snapshots/final.json`.

`case.json` tách `execution_status`, `protocol_status`, `output_status` và
`quality_status`. `brief`/`aus` là KB cuối; `unresolved_items` và `deleted_items`
được giữ riêng. `final_au_ids` là toàn bộ AU cuối, không mang nghĩa AU đã được
verifier chấp nhận. Coverage chỉ đo phần nguồn đã cung cấp, không đo mức hiểu.

Phiếu `adjudication_template.json` được tạo trống. Người đánh giá phải đọc nguồn
và KB cuối trước khi xem log sửa, sau đó mới truy nguyên lỗi về vòng đọc, hai vòng
sửa hoặc lượt chốt. KOS là đối chứng đầu ra, không phải gold.

## Điều kiện cân nhắc mở 20 án

- nguyên văn và vị trí khớp 100%, không mất hoặc lặp thao tác;
- không có lỗi giao thức chưa giải quyết;
- mọi item cuối được đánh giá từng thành phần và không còn lỗi rõ;
- vòng sửa không che lỗi bằng cách defer/xóa hàng loạt item hữu ích;
- có đánh giá omission, item deferred/deleted và phần nguồn chưa đọc;
- kết luận của agent được ghi đúng là agent review, không gọi là human gold.

Không đặt quota AU. Test kỹ thuật đạt, coverage cao hoặc pipeline hoàn tất không
tự chứng minh chất lượng ngữ nghĩa hay chất lượng retrieval COLIEE Task 1.
