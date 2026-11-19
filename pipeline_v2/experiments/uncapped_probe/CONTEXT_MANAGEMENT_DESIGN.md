# Đề xuất quản lý context cho COLIEE Pipeline V2

Ngày 14/11/2026. **Thiết kế tổng thể chưa nghiệm thu.** Người dùng đã giao triển
khai CM0–CM1 trong bộ thử nghiệm riêng. Ngày 15/11/2026, sau nghiệm thu AG CM1 v2,
người dùng giao tiếp CM2 và CM3, vẫn trong bộ thử nghiệm riêng, không inference/
deploy và dừng ở AG review trước CM4. CM4 chưa được giao chạy.
CM0–CM1 đã có prototype offline và AG review checkpoint v1. Theo yêu cầu tiếp
theo, CM1 rules v2 đã sửa eligibility chung/schema/host, exact previous, delivery
metrics và hướng dẫn tool; xem `../context_manager_v1/REPORT.md`. Không diễn giải
bảng thiết kế CM2–CM3 dưới đây thành các nhánh live đã được triển khai.
Phạm vi: cách tổ chức context của vòng M6, thử riêng trước khi tích hợp.
Không đổi model, passages, embedding, fusion, K retrieval, selector hoặc holdout.

## 1. Vấn đề cần giải quyết và giới hạn kết luận

Run `cache/m6-uncapped-021095-20261114-200422096` dừng trước request 3 do
`payload_token_cap`. Bản sửa serialization đã được AG kiểm: request 3 dùng 7.399
token; sau một bước đọc B giả lập, payload A/B dùng 8.285/8.500 token. Đây là
bằng chứng sửa được trạng thái đã ghi, chưa bảo đảm pool lớn hoặc nhiều needs sẽ vừa.

Không mặc định cửa sổ lớn hơn, tóm tắt bằng LLM hoặc chia subagent sẽ giải quyết
nguyên nhân. Cần giới hạn kích thước phần trạng thái được đưa vào từng lượt.
Việc model thấy ít ứng viên mỗi lượt cũng có thể làm bỏ sót hoặc tăng lượt điều
hướng; phải đo tác động này, không gọi phân trang là miễn phí.

Mục tiêu: toàn bộ dữ liệu được giữ và mở lại được; prompt tăng theo kích thước
phần đang xử lý, thay vì tăng theo toàn bộ lịch sử/pool. Nếu phần raw tối thiểu
được chọn vẫn quá lớn, trả trạng thái cần chia trang hoặc đổi trọng tâm rõ ràng.
Không hứa mọi tập evidence đều vừa trong một lượt.

## 2. Ba tầng dữ liệu

| Tầng | Nội dung | Ai sử dụng |
|---|---|---|
| Canonical store | Raw nguồn, manifests, hashes/offsets, mọi search/channel result, pool, needs, evidence, assessments, usage, errors/unknown | Host, validator, evaluator |
| Context state | Focus hiện tại, trang pool/needs/map, evidence được pin, continuation, những gì đã giao, các việc chưa xong | Context manager dựng lại từ ledger |
| Model view | Mục tiêu lượt hiện tại, tổng quan ngắn, một trang lựa chọn, raw cần thiết, tool hợp lệ | Model |

Tái dùng raw/M0–M3, RT1 diagnostics và append-only ledger. Model view là một
projection của canonical state; bỏ một mục khỏi view không xóa nó khỏi pool,
không thu hồi eligibility và không sửa assessment đã lưu.

## 3. Đơn vị công việc: query → need → candidate → evidence pair

`query_id` giữ án A. Một source need giữ các vùng A làm căn cứ, issue thực tìm,
source_proposition do model diễn đạt, search history và pending context. Một need
có thể dẫn tới nhiều B; một B có thể liên quan nhiều needs. Không gán một trạng
thái assessed chung cho B rồi coi mọi nhu cầu về B đã xong.

Focus gồm `mode`, `need_id|null`, `candidate_id|null`, vùng A/B đang đọc, cursor
và lịch sử chuyển focus có giới hạn trong view. Host ghi focus và lý do chuyển
quan sát được; model annotations không trở thành gold.

Theo dõi riêng acquisition, assessment validation, nhãn model và targeted review.
Unknown, pending evidence, raw chưa đọc và bị loại bởi selector là các trạng thái
khác nhau. Không gộp thành một cờ relevant/irrelevant.

## 4. Model view theo công việc hiện tại

Mode là mặc định phân bổ context, không phải một chuỗi bước cứng buộc model đi hết.
Mỗi mode có đường thoát: quay về tổng quan A, chuyển need, xem pool và dừng.

| Mode | Nội dung ưu tiên | Nội dung giữ ngoài prompt |
|---|---|---|
| Khảo sát A | Map hiện tại với literal snippets, coverage, raw A nếu đang mở | Toàn cây, mọi map đã xem, mọi candidate dossier |
| Tạo/tìm theo need | Raw A được chọn, need hiện tại, lịch sử tìm ngắn của need | Toàn bộ needs và các bảng kênh |
| Nhận kết quả | Các hits vừa trả, rank/lead preview gọn, tổng pool, lựa chọn đọc hoặc tìm tiếp | Metadata đầy đủ của toàn pool |
| Đọc B | Need hiện tại, A anchor đã kiểm, raw B/continuation, các bước đọc tiếp | Dossiers của B khác và map A mở rộng đầy đủ |
| Assessment/review | Raw A/B hiện tại, attribution/quotation/counterevidence được yêu cầu, pair handles và trạng thái thiếu | Lịch sử mở nguồn không cần cho lượt này |

Kết quả search mới phải được hiển thị trong view kết quả của operation đó; không
đưa model về trang đầu pool rồi để hits mới nằm ngoài màn hình. Ghi riêng hit đã
trả về, đã thêm pool, đã offer và đã được giao trong một request có response.

Không ghim map phân cấp đầy đủ vào mọi assessment. Giữ breadcrumb/tổng coverage
và một đường quay lại map; mở mode khảo sát sẽ trả map với literal snippets.
Đây là thay đổi trình bày so với RT3 hiện tại: quyền đọc mọi cấp được giữ qua
navigation, nhưng toàn bộ routes của các cấp không cùng nằm trong một payload.

## 5. Phân trang pool và needs

**Trang là một nhóm thông tin model được xem trong một lượt, không phải trang giấy
của bản án.** Ví dụ pool có 50 ứng viên, trang đầu hiển thị tối đa 5 candidate
cards. Model chọn một ứng viên để đọc, hoặc chọn trang tiếp để xem nhóm kế tiếp.
Toàn bộ 50 ứng viên vẫn nằm trong canonical store. Xem danh sách ứng viên không
được tính là đã đọc raw nguồn của các án đó.

Ví dụ model view minh họa, không phải dữ liệu hay giao diện đã triển khai:

```text
Pool: 50 ứng viên; đang xem mục 1–5
cA — án B1 — chưa đọc
cB — án B2 — đã đọc một phần, còn pending evidence
cC — án B3 — chưa đọc
cD — án B4 — có assessment cho need hiện tại
cE — án B5 — chưa đọc
Lựa chọn: đọc một ứng viên / trang tiếp / đổi bộ lọc / chuyển need
```

Trang đầu không cần luôn đủ 5 mục: page size còn chịu token cap. Khi model chọn
trang tiếp, host dựng một payload mới với nhóm tiếp theo và cursor tương ứng.
Khi model chọn đọc một ứng viên, host mở raw của án đó và chuyển focus sang việc
đọc/đối chiếu; không nạp toàn văn cả 5 án. Cơ chế phân trang này thuộc đề xuất
CM1, chưa có trong bản sửa serialization v4 hiện tại.

Đề xuất khởi đầu: một trang tối đa 5 candidate cards, có token cap riêng. Số 5 là
tham số thí nghiệm chưa hiệu chỉnh; đây không phải đổi `search_limit=3` của M3.
Mỗi card chỉ cần handle, case ID, need liên quan trong focus, provenance tìm thấy
gọn, trạng thái đọc/assessment và một preview có ích khi đủ chỗ.

Pool vẫn chứa toàn bộ unique candidates đã nhận. **Tách thứ tự lưu/liệt kê khỏi
thứ tự ưu tiên xử lý.** First-seen chỉ là chỉ mục ổn định để tra cứu, audit và
duyệt kho tổng; không coi nó là chính sách ưu tiên đã chốt hoặc không bias.

| Phạm vi | Thứ tự/chính sách đề xuất |
|---|---|
| Kết quả một operation mới | Hiện ngay các hits vừa trả, giữ rank RRF gốc của operation và need tương ứng |
| Kho pool tổng | First-seen ổn định; cùng operation theo rank gốc; dùng cho tra cứu/cursor, không tự coi án đến trước quan trọng hơn |
| Công việc chưa xử lý giữa các needs | Giữ focus qua một bước có ích rồi model cân nhắc tiếp tục/chuyển/quay lại; host cung cấp trạng thái và cảnh báo. Luân phiên là variant so sánh, không phải lịch ép mặc định |
| Payload assessment | Ưu tiên raw A/B của focus hiện tại, phần thiếu và đường đọc tiếp; các án khác mở lại qua view kho |

### Chính sách điều phối đã thống nhất để đưa vào kế hoạch

Theo yêu cầu người dùng ngày 14/11/2026:

1. **Giữ focus qua một bước có ích:** tìm → nhận kết quả → đọc B → assessment
   hoặc ghi rõ evidence còn thiếu. Assessment có thể là unknown/pending theo
   contract; không ép kết luận có liên hệ để được chuyển focus. Bước có ích là
   một tiến triển của need–candidate, không bắt buộc xử lý hết mọi ứng viên của need.
2. **Sau bước đó model cân nhắc chuyển need**, tiếp tục đọc/tìm cho need hiện tại
   hoặc quay lại hồ sơ pending. Tránh đổi liên tục giữa chừng; không ngắt request
   hay action in-flight. Lỗi, không có hit hoặc không thể đọc được phải ghi rõ
   trạng thái/blocker để model quyết định tiếp, không mắc kẹt chờ assessment bất khả thi.
3. **Hiện ứng viên theo rank gốc của lượt tìm**, giữ danh sách chưa xử lý và
   đường quay lại. Không tự dùng first-seen của kho tổng thay cho ưu tiên xử lý,
   không cộng điểm giữa các lượt tìm/needs để tạo một global rank ngầm.
4. **Host cung cấp trạng thái và cảnh báo lặp; model chọn hướng tiếp theo.**
   Host giữ kiểm tra schema/nguồn/ngân sách và các ranh giới an toàn; không tự
   chuyển need theo một vòng round-robin cứng. Ghi action, focus và lý do chuyển
   quan sát được, không suy diễn lý do hoặc mức hiểu của model.
5. **AG vẫn có quyền chủ động dừng** khi thấy lặp, vòng tròn hoặc nghi bị kẹt,
   theo cơ chế STOP/interrupt và quy tắc bảo toàn unknown của bộ thử nghiệm.

Đây là chính sách đã thống nhất cho thiết kế/thử nghiệm, chưa được triển khai
hoặc chứng minh hiệu quả live. Luân phiên needs vẫn có thể dùng làm variant so
sánh sau khi khóa protocol/ngân sách; chỉ chuyển tại ranh giới an toàn, không ép
luân phiên từng action hoặc từng trang trong policy mặc định.

Ứng viên xuất hiện lại được bổ sung provenance nhưng không tự chuyển lên đầu
kho tổng hay cộng votes qua nhiều query. Một B có thể thuộc nhiều hàng công việc
need–candidate nhưng vẫn là một unique case trong pool. Không so trực tiếp điểm
RRF giữa các issue khác nhau rồi coi đó là global relevance score. Chưa thêm
reranker/MMR hoặc đổi fusion trong bước quản lý context này.

Bộ lọc trạng thái chỉ thay view khi model yêu cầu, không thay eligibility hoặc
prediction. Model được chuyển sang các needs khác, không chỉ xử lý ứng viên của
need cuối cùng. Tổng quan báo riêng số án đã tìm thấy, đã offer, đã hiển thị trong
request có response, đã giao raw và đã assessment theo từng need–candidate.
Nếu dừng sớm, giữ rõ phần chưa hiển thị/chưa đọc/chưa đánh giá và lý do dừng;
không diễn giải việc giữ đủ pool thành model đã khảo sát đủ pool.

Mỗi trang ghi tổng số, phạm vi, filter, pool revision, số mới từ lần xem trước,
next/previous/refresh handles. Cursor bind run/query/snapshot/focus/filter/revision
và vị trí ổn định. Cursor cũ hoặc đọc tiếp đúng revision cũ và báo có cập nhật,
hoặc bị từ chối với hướng refresh rõ ràng; không âm thầm thay nghĩa khi pool tăng.

Need list cũng phân trang. Tổng quan chỉ hiện need hiện tại, số needs chưa xong,
và một số mục gần đây có giới hạn; mọi mục còn lại vẫn có đường mở.

**Rủi ro bias cần kiểm:** vị trí trong một payload, phần dữ liệu lọt vào trang
đang xem, ưu ái các lượt tìm/needs tạo sớm, và việc model không mở trang tiếp.
Có cursor chỉ chứng minh có khả năng truy cập; không bảo đảm agent sẽ sử dụng.
Giữ đường mở lại, coverage và kết quả mới chỉ là biện pháp giảm rủi ro, chưa phải
bằng chứng loại bỏ bias. Phân trang có thể không đổi pool recall nhưng vẫn đổi
độ phủ đọc, assessments, chi phí và kết quả chọn án cuối.

## 6. Pin, park và mở lại evidence

Pin là lựa chọn host chuẩn bị giao, chưa phải model đã đọc. Pin ưu tiên A anchor
của need, B đoạn đang xét, continuation vừa được yêu cầu và attribution hoặc
counterevidence liên quan. Khi đổi B, park raw B cũ và lưu cursor/coverage; không
ghim mọi B đã mở. Khi quay lại, materialize nguyên văn từ source refs đã bind.

Gỡ evidence khỏi context không làm mất assessment đã hợp lệ. Assessment giữ
dependencies và phiên bản riêng; source drift hoặc evidence thay thế theo contract
mới là lý do invalidation. Muốn assess/review lại thì đưa raw A/B liên quan vào
payload hiện tại. Summary, search preview và nhãn model cũ không thay được raw.

Giữ riêng: source đã fetch; raw đã offer; raw đã giao khi có response; raw đang
có trong lượt hiện tại. Provider trả response không chứng minh model hiểu đúng.
Timeout/unknown không được tự ghi thành đã đọc thành công.

Nếu A anchor dài: ưu tiên cấp đủ phần đã làm căn cứ tìm. Nếu không vừa, trả route
để model chọn một subspan/window qua reader hoặc chia việc đọc; giữ ref parent,
exact span/hash phần hiện tại và pending coverage. Không cắt ngầm rồi gọi là full.
Nếu cả A và B dài, phân trang có overlap/context refs theo policy đọc được khai
báo. Mỗi assessment vẫn phải gắn với những phần raw thực sự đang hiện và giữ
uncertainty khi thiếu attribution/negation/exception hoặc continuation.

## 7. Tool và opaque handles

### Bảng quy tắc điều hướng theo context

Theo yêu cầu người dùng, dùng một policy eligibility chung cho catalog, schema,
host validator và transition handler. Những điều kiện đã biết khi compile phải
được thể hiện trong schema; host vẫn kiểm lại theo manifest của đúng request.
View đang xem khác với trạng thái công việc: xem pool/map không tự kết thúc focus.

| Trạng thái | Lựa chọn hợp lệ | Điều kiện và kết quả |
|---|---|---|
| Khảo sát A | Mở map, đọc A, xem needs/pool, dừng | Chỉ refs được cấp; xem preview không thành raw evidence |
| Có raw A hiện tại | Tìm issue/citation, đọc thêm A | Query bind exact raw hiện tại; proposition chỉ debug; ghi operation/need |
| Nhận search results | Đọc B thuộc need, xem thêm, đọc A hoặc tìm tiếp cùng need | Hits mới giữ rank gốc; đọc B giữ focus need–candidate |
| Đang đọc B | Đọc thêm B/A, mở context, reload, xem trang, ghi thiếu evidence | Giữ focus; không cấp đổi sang B/need khác giữa bước |
| Raw A/B hiện tại | Assess, đọc thêm, ghi thiếu evidence | Pair refs đúng payload; đủ raw không chứng minh đủ căn cứ pháp lý |
| Đã ghi thiếu evidence | Bổ sung, tìm tiếp, đọc B khác, chuyển need, dừng | Giữ hồ sơ pending và phần thiếu, không tự kết luận irrelevant |
| Assessment được host chấp nhận | Tiếp tục/review có trigger, B khác, need khác, dừng | Kết thúc một bước có ích, không tự hoàn tất toàn need |
| Search no-hit | Query khác cùng need, đọc A, need khác, dừng | Ghi no-hit; không mắc kẹt đòi assessment khi không có B |
| Tool lỗi đã rõ kết quả | Sửa tham số, đường khác, ghi blocker, chuyển focus, dừng | Giữ usage/lỗi; không tự gửi lại action không an toàn |
| Request/action in-flight hoặc unknown | Chờ/đối chiếu call hiện có, AG có thể dừng | Không cấp model request mới hoặc resend ngầm |
| Run terminal | Chỉ inspect/report | Không resume bằng sửa ledger hoặc profile |

| Lựa chọn | Ràng buộc cần thể hiện |
|---|---|
| Trang next/previous | Chỉ đổi view, không đổi focus/evidence; previous quay đúng mốc đã xem kể cả khi trang co |
| Pool tổng | Card báo thuộc need hiện tại hay không; B khác need không xuất hiện trong enum đọc trực tiếp |
| Đổi need | Chỉ needs khác đang được cấp và tại safe stage; không cấp thao tác no-op đổi về cùng need |
| Đọc B | Enum chỉ các B thuộc need hiện tại; khi reading chỉ B đang focus được phép đọc tiếp |
| Ghi thiếu evidence | Chỉ focus đang reading, lý do cụ thể không rỗng; không ghi assessment hoàn tất |
| Reload/continuation | Chỉ source refs đã quan sát/bind, không tự suy offsets hoặc đổi nguồn |
| Assessment/review | Raw A/B đúng pair hiện tại; review có trigger; host giữ canonical dependencies |
| Dừng | Báo việc chưa xử lý; AG vẫn được dừng ở mọi giai đoạn theo STOP/unknown contract |

CM1 sửa ngay eligibility của context commands, previous và metrics. Các nhánh
tìm/đọc thật, callback tool errors/no-hit, reload/assessment/review và terminal
vẫn phải nối ở CM2–CM3; không cấp tool giả chỉ để hoàn tất bảng này. Tách metric
need được hiển thị qua current context khỏi need card đã duyệt trong danh sách;
cả hai chỉ là delivery, không chứng minh model đã đọc hiểu hoặc giải quyết need.
Mỗi tool cần mô tả mục đích, lúc dùng, kết quả, bảng chứa handles và cách phục hồi.

Giữ tên các tool hiện có khi hành vi không đổi. Có thể thêm các action trình bày
như xem trang candidates/needs, đổi focus hoặc quay lại map; chỉ thêm khi không
thể biểu đạt rõ bằng action đang có. Việc chọn B để đọc có thể đồng thời chuyển
focus và nạp A, tránh bắt model trả thêm một lượt chỉ để host đổi màn hình.

Model chỉ nhận handles cho lựa chọn hiện tại. Host giữ binding đầy đủ ở admission
manifest: case, raw source hash, offsets, cursor, need, config và phiên bản.
Source identity vẫn được kiểm đầy đủ; không bắt model sao chép mọi hash kỹ thuật
chỉ để chọn một hành động. Nếu dùng handle evidence ngắn, adapter phải đổi sang
canonical raw refs trước validator; không được làm yếu điều kiện current payload.

Handle phải ổn định với cùng binding, khác khi binding có hiệu lực khác, có kiểm
collision và chỉ được dùng khi được cấp ở lượt hiện tại. Không dùng ordinal trần
có thể trỏ sang đối tượng khác ở lượt sau. Decoder schema vẫn enum các handles
đang hợp lệ; mô tả tool có thể dẫn tới bảng lựa chọn, như bản thử nghiệm v4.

## 8. Ngân sách và thuật toán đóng gói

Giữ hard cap input 8.500, output 512, context engine source 12.288. Đề xuất soft
target 7.900 để tránh luôn sát trần; 600 token còn lại là headroom trong cap 8.500.
Đây là mục tiêu thử nghiệm, chưa phải số đo đã chứng minh đạt.

| Thành phần | Phân bổ khởi đầu |
|---|---:|
| Instructions và tool đang cần | 1.800 |
| Focus, tiến độ, việc còn thiếu, controls | 400 |
| Map hoặc candidate/need page | 800 |
| Raw evidence ưu tiên | 4.900 |
| Headroom | 600 |
| Tổng | 8.500 |

Ngân sách mềm có thể chuyển giữa map/page và raw theo mode. Context manager đếm
toàn bộ chat prompt bằng tokenizer pin, kể cả instructions/template/tools; không
ước lượng ký tự, không cộng riêng các trường rồi coi là tổng chính xác.

Trình tự compile:

1. Đọc state ở ledger prefix xác định; resolve focus và source/config bindings.
2. Tạo view tối thiểu với mục tiêu, các đường đổi focus/mở lại và trạng thái chưa xong.
3. Materialize evidence được pin; dựng tool/schema phù hợp chính view này.
4. Render và đếm prompt thật. Tăng nội dung theo phần ngân sách còn lại.
5. Nếu quá target: bỏ display trùng, giảm optional previews và page size; giữ controls,
   coverage và raw bắt buộc. Không xóa candidate hoặc evidence khỏi canonical store.
6. Nếu raw cần thiết chưa vừa: chia thành phần exact UTF-8 với continuation, hoặc
   trả một view phục hồi nhỏ yêu cầu chọn vùng/đổi focus. Không giả vờ có đủ cặp A/B.
7. Kiểm lại raw refs, schema, exact token count và tổng ngân sách còn lại, rồi admission.
8. Ghi delivery/coverage sau receipt theo quy tắc hiện hành.

View phục hồi không tự gọi model lặp vô hạn. Ghi signature nguyên nhân unfit;
nếu không thay lựa chọn/evidence mà vẫn không vừa thì báo blocker cụ thể cho AG.
Nếu ngay phần instructions/tool/controls tối thiểu vượt cap, dừng local trước
admission với phân tích token; đây là lỗi cấu hình, không phải evidence thiếu.

## 9. Lịch sử và tóm tắt

V1 không thêm request LLM để tóm tắt. Dùng progress card được host tổng hợp từ
ledger: số needs/candidates, các cặp đã assess/pending, vùng chưa giao, searches
thực hiện và action lỗi/unknown. Query text, model annotations và các quyết định
ngắn có provenance riêng; không biến progress card thành lập luận pháp lý mới.

Về sau chỉ thử LLM summary như một variant riêng nếu evidence cho thấy cần.
Summary phải có refs, không dùng làm evidence, không xóa bản đầy đủ và có test
khôi phục thông tin đã rời context. Đo thêm cost, drift và mất điều kiện/ngoại lệ.

## 10. Admission, resume và nguồn chân lý

Tái dùng reservation, usage và recovery của M4/M6. Mỗi request admission cần giữ
model view bytes/hash, đầy đủ binding manifest/hash, schema/fingerprint, context
policy/profile, focus/page revision, pinned/delivered/pending refs và token count.
Model response được dịch bằng manifest của đúng request đó, không dùng registry
mutable mới nhất. Không ghi là model đã thấy trước khi có receipt phù hợp.

Đổi focus chỉ dựa trên action đã được ghi và kết quả tool đã durable. Crash giữa
admission và response giữ unknown; không resend, không reset ngân sách/cursor để
vượt guard. Context bị park vẫn mở lại được từ nguồn đã bind. Source/config drift
bị từ chối như hiện tại. Terminal run cũ không được sửa/resume bằng policy mới.

M4 `RunState` hiện từ chối event kind không biết; vì vậy không tự append context
events mới vào ledger cũ. Prototype phải có contract/adapter version mới, định
nghĩa rõ cách ghi context state và replay. Nên suy focus từ action/result hiện có
khi đủ, thêm manifest fields ở admission qua adapter riêng; nếu cần journal riêng
thì ghi immutable manifest trước và bind hash trong admission, phát hiện orphan
thay vì coi hai nơi ghi là một transaction. Không giả lập source-read để ghi một
thao tác chỉ chuyển trang pool.

Host có thể cần materialized index cho pool/needs/coverage khi dữ liệu lớn. Đây
là derived cache có prefix/config hash và khả năng rebuild từ ledger, không là
nguồn chân lý mới. Prompt bounded không có nghĩa CPU/RAM host tự bounded; phải
đo riêng chi phí replay state và các guard nguồn hiện hành.

## 11. Log và quyền dừng của AG

Mỗi lượt ghi mode/focus, token tổng/target/cap, item đã chọn/park/omit cùng lý do,
raw byte ranges, coverage, tool names, schema/manifest hashes và query thực gửi.
Token breakdown theo component chỉ phục vụ chẩn đoán; total prompt là quyết định.

Giữ controller/embedding/dense/source-read stage, call/request IDs, thời gian chờ,
provider usage và unknown riêng. Đếm thêm số lượt đổi trang/need/B, số lần đọc lại,
context-unfit recoveries và raw byte hữu ích được giao. Local compile/trim không
là một request model; action phân trang do model chọn vẫn tốn lượt controller.

AG được dừng khi context thrashing: qua lại cùng trang/focus, lặp query/read mà
không có raw/candidate/assessment mới hoặc giải quyết phần thiếu. Signature vòng
lặp dùng canonical operation, không dựa handle thay theo lượt. Trong uncapped
probe, cảnh báo để AG quyết định; không tự mở retry trả phí. STOP/cancel/unknown
giữ đúng giới hạn đã ghi trong README.

## 12. Kiểm chứng và tiêu chí nghiệm thu

| Nhóm | Kiểm bắt buộc |
|---|---|
| Pool tăng | Fixture 3/50/500/10.000 candidates, nhiều needs; view/page không tăng theo toàn pool; không mất eligibility; duyệt hết bằng cursor |
| Nguồn dài | A/B dài, quoted/unknown, UTF-8 nhiều byte, tiếp nối; không cắt hash/span sai, không báo full khi partial |
| Tập trung công việc | Cùng B qua nhiều needs; đổi B rồi quay lại; không trộn pair/need và không bỏ quên needs cũ |
| Evidence | Chỉ raw hiện tại đủ điều kiện assess; summary/preview/ref của lượt trước không được dùng ngầm |
| Phục hồi | Crash ở manifest/admission/response/action; cursor revision cũ, source drift, unknown receipts; không gửi trùng |
| Schema | Prompt gọn nhưng decoder/host validation đầy đủ; stale handles/tamper/collision bị từ chối |
| Recall | Pool đầy đủ và metrics RT1 không đổi trong cùng scripted actions; view pruning không trở thành retrieval pruning |
| Bias do thứ tự | Trên cùng frozen pool/needs và ngân sách, so first-seen, policy luân phiên và các hoán vị khóa seed; đo phần được hiển thị/đọc/assess, kết quả và cost; giữ các trang/needs chưa được xem trong báo cáo |
| Khả năng model dùng | Live discovery kiểm model tìm lại thông tin đã park, chuyển need/B, tiếp tục đọc và assessment đúng source refs |

Tách hai loại đánh giá: (a) cùng actions để kiểm cơ chế và parity; (b) model tự
chọn actions để đo tác động context tới recall/cost. Một replay PASS không thay
cho (b). Không đọc gold trong solver; freeze trước evaluator, giữ lỗi/unknown và
đủ denominator. Pool recall không thay final F1, không chốt selector ở milestone này.

Kiểm bias cần tách: (1) thay vị trí cards trong cùng một trang, giữ nguyên tập được
hiển thị; (2) thay thứ tự trang hoặc lịch chuyển need, làm thay tập được xem trước
khi hết ngân sách. Hoán vị phải được khóa trước khi chấm, không dùng gold chọn
thứ tự và không ghi đè thứ hạng retrieval gốc. Dùng cùng model/prompt, page/token
caps và ngân sách; giữ toàn bộ run lỗi/dừng sớm. Trước tiên replay cùng actions
để kiểm parity, sau đó mới cho model tự chọn để đánh giá bias hành vi. Chỉ mở
thêm inference so sánh khi có scope/ngân sách được giao.

Ngoài peak input, đo token trung vị/tổng, phần metadata/raw, thời gian compile,
model/embedding requests, reload/page turns, raw coverage, pool recall, pending
contexts và cost của các run lỗi. Không đặt tỉ lệ raw cố định thành chứng nhận
chất lượng; một đoạn ngắn nhưng sai trọng tâm vẫn vô ích.

## 13. Lộ trình đề xuất

Checkpoint 15/11/2026: CM0–CM1 và CM2–CM3 đã qua review engineering offline.
Nghiệm thu CM2–CM3 ở `../context_manager_v2/CM23_ACCEPTANCE.md`, gồm hai ghi
nhận không chặn cần rà soát trước CM4. **Chưa mở CM4 hoặc gọi inference/deploy.**

1. **CM0 — Đo context:** compiler trace, token ownership, replay các trạng thái đã
   có. Chốt phần tối thiểu và tính khả thi của phân bổ 8.500, chưa đổi hành vi model.
2. **CM1 — View bounded:** phân trang pool/needs, focus và tool view theo mode;
   giữ raw reader/assessment contract. Tách first-seen index khỏi scheduler và
   khai báo policy/version/seed. Kiểm pool tăng, coverage và cursor/resume offline.
   **Dừng để AG review độc lập cuối CM1** trước khi mở CM2: review thiết kế view,
   bias/thứ tự, focus, cursor/revision, phần chưa hiển thị và replay với tokenizer
   thật. Adapter CM1 chỉ kiểm điều hướng/dispatch intents offline; chưa là runner
   inference hoặc cơ chế pin/park evidence mới của CM2.
3. **CM2 — Evidence lifecycle:** pin/park/reload A/B, continuation, current-payload
   validation; kiểm các tình huống quay lại evidence và attribution.
4. **CM3 — Tích hợp:** replay đường đã lỗi, scripted nhiều vòng tìm/đọc/assess và
   thử áp lực context và các thứ tự trình bày khác nhau bằng scripted actions.
   AG kiểm độc lập, không cần inference cho gate cơ chế.
5. **CM4 — Một query live:** người dùng/AG chạy namespace mới, giám sát/dừng; xem
   traces và chi phí trước khi mở pilot rộng hơn. Giữ các biến retrieval cố định;
   kiểm agent có thực sự dùng phân trang/mở lại. Thí nghiệm bias nhiều run là
   gate tiếp theo cần scope/ngân sách riêng, không tự chạy nối tiếp một-query probe.

Đề xuất code mới ở `pipeline_v2/experiments/context_manager_v1/`, gồm projection,
views, binding manifest, compiler, adapter, replay và tests. Tái dùng source reader,
tokenizer, validators, RT1 diagnostics và transport hiện có; không đổi byte của
module/snapshot đã bind hash. Chỉ chuyển vào đường chạy chính sau gate riêng.

## 14. Các quyết định đề xuất chốt cho V1

- Host state đầy đủ; model view có giới hạn và có đường mở lại.
- Một focus need/B ở một thời điểm; chuyển focus do model hoặc kết quả action
  rõ ràng, không dùng gold hoặc LLM hậu trường để xếp lại ưu tiên.
- Trang tối đa 5 candidate cards khởi đầu; tổng pool giữ nguyên; có token cap.
- First-seen chỉ phục vụ kho tổng/audit. Giữ RRF trong từng operation, hiện hits
  mới ngay. Policy thiết kế đã thống nhất: giữ focus qua tìm → nhận kết quả → đọc
  B → assessment hoặc ghi rõ thiếu evidence; sau đó model cân nhắc tiếp tục,
  chuyển need hoặc quay lại pending. Host báo trạng thái/cảnh báo, AG được dừng.
  Kiểm với variant luân phiên và hoán vị khóa seed; chưa coi thứ tự nào trung lập.
- Assessment ưu tiên raw A/B và đường đọc tiếp; map lớn chỉ nạp khi khảo sát A.
- Giữ cap 8.500/512, thử soft target 7.900; chưa tăng context/model/GPU.
- V1 không thêm LLM summary hay subagent; không đổi selector/fusion/K.
- Nghiệm thu theo CM0–CM4 và dừng tại từng gate; đây là đề xuất, chưa là lệnh chạy.
- Authorization hiện hành ngày 15/11/2026: CM0–CM1 v2 đã qua checkpoint AG;
  triển khai CM2–CM3 trong `pipeline_v2/experiments/context_manager_v2/`, kiểm
  offline bằng nguồn thật và phản hồi giả lập, rồi dừng để AG review. Không tự
  mở CM4 hoặc gọi inference/deploy. Không sửa checkpoint CM1 đã nghiệm thu.
- CM2–CM3 được triển khai riêng tại `../context_manager_v2/`: dùng ledger M4,
  reader và assessment validator hiện hành; thêm kho raw được kiểm hash, cửa sổ
  UTF-8, pin/park/reload theo cặp và manifest cho từng lượt. Controller chỉ nhận
  phản hồi giả lập offline. Xem `README.md`, `REPORT.md`, `AG_CHECK.md` trong
  thư mục đó để biết bản đã kiểm và giới hạn. Không nhập vào production ở mốc này.

Tài liệu tham khảo thiết kế: Anthropic, *Effective context engineering for AI
agents* (https://www.anthropic.com/research/effective-context-engineering-for-ai-agents);
LangChain, *Context Management for Deep Agents*
(https://www.langchain.com/blog/context-management-for-deepagents).
Các con số/phân bổ và giao diện COLIEE ở tài liệu này là đề xuất riêng cho repo,
không phải tham số chuẩn hoặc cam kết chất lượng của các hệ thống tham khảo.

Cập nhật nghiên cứu về phân trang và thứ tự ngày 14/11/2026:

- [MCP pagination, bản 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination):
  cơ chế cursor cho list operations, không phải thuật toán ưu tiên kết quả search
  bên trong tool hoặc bảo đảm model duyệt hết.
- [LangChain vectorstore retriever](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/vectorstores/base.py)
  hỗ trợ similarity/threshold/MMR;
  [LlamaCloud retrieval](https://developers.llamaindex.ai/llamaparse/cloud-index-v2/retrieval/)
  mô tả hybrid/rerank/top-k. Đây là các chính sách chọn kết quả, không chứng nhận
  first-seen cho pool đa query; không đưa chúng vào solver ở đợt sửa này.
- [Anthropic Research](https://www.anthropic.com/research/multi-agent-research-system):
  điều phối nhiều hướng và cân bằng breadth/depth; tài liệu không công bố một
  lịch FIFO/phân trang candidates cụ thể để áp nguyên xi.
- [Lost in the Middle](https://arxiv.org/abs/2307.03172): bằng chứng ảnh hưởng vị
  trí trên các tác vụ long-context được thử, chưa định lượng bias cho Qwen/COLIEE.
- [Agents Don't Paginate](https://arxiv.org/abs/2608.26130): preprint báo cáo không
  có yêu cầu second-chunk trong tập log middleware khảo sát; giới hạn theo mẫu,
  không suy ra mọi agent đều không phân trang. Dùng để đặt yêu cầu kiểm hành vi
  mở trang thực tế, không coi là kết quả của pipeline này.
