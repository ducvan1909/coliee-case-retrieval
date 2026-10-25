# Kế hoạch sửa KB sau pilot V3 — giữ attribution

Ngày: 2026-09-25.

Trạng thái triển khai ngày 2026-09-25:

- Đã triển khai schema/prompt/pipeline V4, địa chỉ handle, verifier từng thành
  phần, checkpoint trước repair, verifier repair, cache envelope, recheck CLI,
  report/compare V4 và các kiểm thử hồi quy cục bộ.
- Đã tạo phiếu phân xử từ đủ 5 án và 29 item V3 tại
  `outputs/pilot_v4/adjudication_template.json`; phiếu còn
  `pending_adjudication`, không phải gold.
- Đã chạy unit test, compileall, kiểm tra khoảng trắng/diff, preflight và dry-run
  chọn đúng 5 án. Chưa gọi Modal và chưa tạo kết quả case V4.
- Việc còn lại trước request thật: điền bảng phân xử/cơ hội AU và xác nhận dự
  toán ngoài số dự phòng nội bộ. Sau đó mới chạy một lần 5 án và kiểm tra trực tiếp.

## 1. Quyết định và phạm vi

- Giữ attribution ở từng tham chiếu nguồn của brief và AU. Không đồng nhất tác giả bản án với chủ thể của mọi phát biểu trong bản án.
- Giữ nguyên nguyên tắc: agent chọn nguồn và phân loại; code lấy nguyên văn, quản lý ID, revision, lịch sử và trạng thái. Không bổ sung claim hay tóm lược sinh vào KB.
- Dự kiến dùng `schema_version=4`, prompt mới và `pilot_v4`; giữ nguyên toàn bộ V1–V3 để đối chiếu. Không chuyển nhãn accepted của V3 thành accepted V4.
- Chỉ dùng năm án hiệu chỉnh: `011904`, `013009`, `013948`, `045155`, `099980`. Chưa mở 20 án đánh giá.
- Không sửa retrieval, không phân chia bản án thành hệ LegalUnit thủ công, không đặt số AU tối thiểu.
- Giữ `KB_BUDGET_USD=unlimited` theo lựa chọn hiện tại nhưng vẫn thống kê request, token, thời gian và dự phòng; dự phòng không phải hóa đơn Modal.

## 2. Bằng chứng và giới hạn của chẩn đoán

Nguồn đối chiếu: `outputs/pilot_v3/MANUAL_REVIEW.md`, response và checkpoint của năm án; `schema.py`, `prompts.py`, `pipeline.py`, `state.py`, `source.py`, `endpoint.py`, `__main__.py`; proposal tại `G:/Legal-AI/AGENTIC_LEGAL_KNOWLEDGE_STORE_PROPOSAL.md`.

### Những điều đã xác nhận

- Báo cáo V3 ghi 29 mục, toàn bộ là brief: 22 accepted, 6 needs_review, 1 rejected, không có AU; 68/68 excerpt khớp nguồn về nguyên văn và vị trí.
- Hai response verifier chứa ID căn cứ không hợp lệ. Host đã giữ chúng ở needs_review; đây không phải lỗi lấy nguyên văn.
- Verifier hiện có một lý do, một danh sách căn cứ và một attribution_status chung. Chưa bắt buộc kiểm tra riêng từng tham chiếu; danh sách căn cứ rỗng vẫn qua validator.
- Prompt verifier không có rubric nhóm brief/chủ thể đầy đủ như reader. Response của `099980` có lý do dựa trên việc văn bản do tòa viết để chấp nhận current_court. Đây là tiêu chí không đủ.
- Một câu có thể gồm lời dẫn của tòa và nội dung authority được trích; địa chỉ câu không bảo đảm một chủ thể duy nhất.
- Ví dụ AU hiện tập trung vào xử lý authority được dẫn; proposal còn cho phép nguyên tắc, áp dụng quy tắc, nhận định chứng cứ và thủ tục của chính tòa.
- Thao tác hợp lệ được áp dụng trong bộ nhớ trước request sửa giao thức nhưng chưa checkpoint ngay. Lỗi giữa hai bước làm phục hồi phải dựa vào phát lại từ cache.
- Verifier lỗi giao thức được chuyển needs_review và tăng chỉ số xử lý; resume thông thường không có đường kiểm tra lại có kiểm soát cho mục đó.
- Validator, ví dụ và mô tả hợp đồng vẫn được viết riêng; chưa thực sự sinh từ một định nghĩa cấu trúc duy nhất.

### Không được kết luận quá mức

- “8/22 không đạt” là kết quả đánh giá ban đầu, không phải gold đã phân xử bởi chuyên gia. Một số câu tòa thuật lại yêu cầu của đương sự còn phụ thuộc quy ước attribution.
- Không coi 8/22 là tỷ lệ lỗi tổng quát của hệ thống; không khẳng định bỏ attribution sẽ tăng từ 14/22 lên 16/22. Đó là phản thực chưa chạy thử.
- Không có AU chưa chứng minh năm án không có nội dung phù hợp, cũng chưa chứng minh lỗi duy nhất nằm ở model. Cần kiểm tra nguồn đã đọc, mục tiêu đọc, prompt và khả năng chọn AU.
- Reader và verifier cùng model có thể lặp cùng sai lầm, nhưng hiện chưa có ablation chứng minh nguyên nhân này. Chưa cần đổi model trước khi sửa hợp đồng.

## 3. Các phương án đã phản biện

Hai subagent đọc độc lập theo hai hướng: chất lượng lựa chọn/phân loại và hợp đồng/trạng thái host. Tổng hợp đối chiếu:

| Phương án | Ưu điểm | Điểm yếu | Quyết định |
|---|---|---|---|
| Bỏ attribution | Ít nhãn, ít token kiểm tra | Mất phân biệt lời đương sự, luật được trích và kết luận tòa; không sửa lỗi kind | Không chọn |
| Chỉ sửa prompt | Rẻ, triển khai nhanh | Không buộc verifier kiểm tra đủ từng đoạn; không sửa checkpoint/cache | Là bước cần nhưng chưa đủ |
| Rubric chung + kiểm chứng từng tham chiếu/thành phần | Kiểm toán được, giữ thiết kế trích xuất | Tăng token; vẫn cần đánh giá độc lập | Chọn làm lõi V4 |
| Thêm nhiều nhóm brief hoặc tách mệnh đề | Có thể tăng độ chi tiết | Dễ che lỗi phân loại bằng mở rộng nhãn; tăng phức tạp địa chỉ nguồn | Chưa làm trong V4 |
| Thêm model/agent bỏ phiếu | Có thể giảm lỗi tương quan | Chi phí cao, đồng thuận không bảo đảm đúng | Chỉ xét sau khi đo V4 |
| Buộc tạo ít nhất một AU | Dễ có đầu ra để xem | Khuyến khích chọn yếu hoặc sai | Không chọn |

## 4. Rubric dùng chung

### 4.1 Attribution

Định nghĩa attribution là chủ thể của nội dung được chọn, không phải tác giả vật lý của tài liệu. Reader, finalizer, verifier và người đánh giá dùng cùng rubric.

- `current_court`: nhận định của tòa hiện tại, hoặc tòa thuật lại sự kiện tố tụng như một dữ kiện; không suy ra chỉ từ nơi xuất hiện của câu.
- `party`: nội dung lập luận, khẳng định hoặc yêu cầu được quy rõ cho đương sự. “Applicant argues X” không biến X thành kết luận của tòa.
- Phân biệt “Applicant filed an appeal on date D” với “Applicant contends X”. Câu đầu có thể là tòa thuật sự kiện; câu sau quy X cho đương sự.
- Câu “Applicant asks the Court to determine whether X” cần xét cả phạm vi được chọn: yêu cầu là của đương sự; nếu giữ cả lời định hình vấn đề độc lập của tòa và không tách được thì dùng mixed. Không áp dụng quy tắc từ khóa applicant.
- `cited_authority` bao gồm nội dung trích từ án khác và văn bản quy phạm. Việc tòa trích một quy phạm không tự chứng minh adopts/applies.
- `editorial`: nội dung biên tập như headnote khi có căn cứ nhận diện. Vị trí đầu tài liệu chỉ là dấu hiệu, không đủ để tự gán nhãn.
- `mixed`: thực sự có nhiều chủ thể trong phần được giữ mà địa chỉ hiện có không tách được. Ưu tiên câu cụ thể nếu đủ nghĩa.
- `unknown`: thiếu căn cứ hoặc loại chủ thể chưa được enum biểu diễn rõ, như một số lời chứng/tài liệu chứng cứ. Không ép sang current_court.

Unknown/mixed không tự là lỗi và không tự được accepted: verifier phải kiểm tra việc dùng nhãn đó. Không suy ra sự tán thành của tòa từ các mục này.

### 4.2 Nhóm brief

Giữ bốn nhóm và bổ sung tiêu chí loại trừ:

- facts: sự kiện và chứng cứ của vụ án; quy phạm pháp luật không phải facts chỉ vì xuất hiện trong bản án.
- posture: giai đoạn tố tụng, quyết định đang bị xem xét và yêu cầu giải quyết; không nhầm với lệnh cuối cùng của tòa hiện tại.
- issues: câu hỏi phải giải quyết; một kết luận về câu hỏi đó không tự là issues.
- disposition: quyết định và biện pháp cuối cùng của tòa.

Không ép nhận định pháp lý vào facts hoặc issues. Nếu không phù hợp brief, xét làm AU hoặc không lưu. Không thêm nhóm mới chỉ để giảm số lỗi hồi quy.

### 4.3 AU và treatment

- AU có thể chứa nguyên tắc, điều kiện/ngoại lệ, áp dụng quy tắc, nhận định chứng cứ hoặc thủ tục; không bắt buộc có citation.
- Bổ sung ví dụ hợp lệ: primary của current_court với treatment unknown; AU gồm authority và court_response; AU có qualification thiết yếu; ví dụ sai do đoạn rời không liên quan.
- Trong V4 giữ enum treatment hiện có để hạn chế thay đổi: unknown nghĩa là chưa xác lập được một quan hệ xử lý authority thuộc các giá trị còn lại. Đây không phải khẳng định có authority bị thiếu.
- Verifier ghi rõ trong phần kiểm toán unknown là do không có quan hệ xử lý authority cần biểu diễn hay do thiếu bằng chứng; thông tin này không trở thành nội dung AU sinh mới.
- Non-unknown vẫn phải có authority_source_ids và response_source_ids được lưu trong mục. Distinguishes giữa hai khái niệm không đủ; citation đơn thuần không đủ cho applies.
- Lượt chốt ghi `au_search_outcome`: found / none_supported_in_read_source / insufficient_reading, cùng ID đã khảo sát và khoảng nguồn cần đọc thêm. Đây là nhật ký quyết định, không phải bằng chứng tự xác nhận đã đọc kỹ và không phải nội dung KB.

## 5. Hợp đồng verifier V4

- Mỗi kiểm tra có `{status, reason, evidence_source_ids}`; reason không rỗng và căn cứ phải thuộc nguồn thực sự đã cung cấp.
- `attribution_checks` bao phủ chính xác tập source_ref của mục, không thiếu/trùng/thừa. Mỗi tham chiếu có nhãn đánh giá độc lập và kết quả đối chiếu với nhãn reader.
- Brief: kiểm tra lựa chọn/đủ ngữ cảnh, kind và attribution từng tham chiếu.
- AU: kiểm tra tính liên quan, điều kiện/ngoại lệ, attribution từng tham chiếu và treatment.
- Mọi thành phần accepted phải có căn cứ riêng không rỗng. Một lý do chung không thay thế cho kiểm tra từng nhãn.
- Host kiểm tra cấu trúc, tập ID, revision và suy ra trạng thái tổng; không dùng accepted tổng của model để bỏ qua thành phần sai.
- Trong cùng một request, verifier được yêu cầu phân loại từ nguồn trước rồi đối chiếu nhãn đề xuất. Không coi thứ tự trường JSON là bảo đảm độc lập; đánh giá thực nghiệm mới xác nhận hiệu quả.
- Verifier không nhận lý do chọn của reader và không đòi claim diễn giải. Nhận đoạn chọn, đoạn cha và lân cận do code lấy.
- Cho phép một lần bổ sung ngữ cảnh và một lần kiểm tra lại về ngữ nghĩa. Ngữ cảnh xem thêm không tự được đưa vào mục; thiếu đoạn thiết yếu trong mục thì needs_review.
- Tách accepted bởi verifier khỏi xác nhận của người đánh giá. Báo cáo và bộ xuất KB phải thể hiện rõ nguồn của quyết định chấp nhận.

## 6. Sửa host và giao thức

### 6.1 Một định nghĩa cấu trúc và địa chỉ dễ dùng

- Dùng typed schema hoặc JSON Schema làm nguồn chung cho validation, mô tả request và ví dụ được kiểm thử. Các ràng buộc ngữ nghĩa/liên trường vẫn do host kiểm tra rõ ràng.
- Đưa rubric chung vào reader, finalizer, sửa giao thức và verifier; test không chỉ kiểm tra tên enum mà cả các yêu cầu thành phần.
- Dùng handle ngắn trong request để giảm lỗi chép ID dài. Host ánh xạ sang ID nguồn ổn định bằng manifest có scope/hash; handle lạ hoặc sai scope bị bác, không đoán ID gần nhất.
- Cung cấp danh mục điều hướng cho yêu cầu xem thêm nhưng phân biệt preview với nguyên văn đã cung cấp đầy đủ.
- Nếu cho chọn đoạn cha, request phải thực sự cung cấp nguyên văn đầy đủ đoạn cha. Coverage dựa trên hợp các khoảng ký tự đã gửi, không chỉ dựa trên nhãn cửa sổ đã mở. Ghi riêng reader/verifier.
- Kiểm thử giới hạn payload với đoạn dài; chia cửa sổ kỹ thuật, không chuẩn hóa byte hoặc cắt mất nguồn rồi vẫn tính đã đọc đủ.

### 6.2 Thao tác và sửa giao thức

- Update/remove chỉ được nhắm ID đã có trong snapshot current_items đầu request. Mục mới add chỉ được cập nhật từ request sau; tránh đoán ID của add bị bác rồi sửa nhầm add khác.
- Ghi operation ID, response gốc, lỗi có đường dẫn trường và lịch sử resolution. Không tự ánh xạ kind/enum hoặc bổ sung nhãn thiếu.
- Hợp nhất tối đa một request sửa giao thức cho mỗi response reader/finalizer, gồm lỗi envelope và thao tác. Giữ nguyên thao tác hợp lệ đã áp dụng và trường điều khiển hợp lệ; sửa không được mở thêm nguồn hoặc đổi ý định finalize thành read.
- Response không phân tích được JSON: chưa áp dụng thao tác nào; lưu nguyên bản và dùng cùng hạn mức một lần sửa cấu trúc. Không biến HTTP 200 sai JSON thành lỗi transport không rõ.
- Thay sửa JSON bằng regex toàn chuỗi bằng phân tích an toàn hoặc request sửa có giới hạn. Không cho phép sửa nhầm nội dung trong chuỗi ký tự.
- Verifier có tối đa một lần sửa giao thức riêng, giữ nguyên item/revision. Hết lượt vẫn sai thì needs_review và lỗi chưa giải quyết, không accepted.
- Sửa giao thức khác với sửa lựa chọn ngữ nghĩa. Nếu muốn thay lựa chọn/nhãn, đó là revision mới và phải kiểm chứng lại, không lén sửa trong request phục hồi cấu trúc.

### 6.3 Checkpoint, cache và resume

- Persist thao tác hợp lệ, thao tác bị bác và repair_pending trước khi gọi request sửa. Payload/request ID sửa phải được cố định để tiếp tục đúng request.
- Ghi pha request/response/apply bằng journal; commit trạng thái nguyên tử và áp dụng operation idempotent. Không cấp lại ID hoặc dự phòng sau crash.
- Cache envelope chứa logical request ID, experiment/schema/model, hash cấu hình/prompt/nguồn/payload và checksum response. Kiểm tra khi đọc; mismatch là lỗi rõ ràng, không âm thầm dùng hoặc ghi đè.
- Resume không gọi lại request timeout/mất kết nối có kết quả chưa rõ; giữ bảo đảm cold start 503 hiện có.
- Bổ sung đường recheck tường minh cho lỗi verifier chưa giải quyết, thay vì bỏ qua vì execution đã completed. Giữ lịch sử và revision; không tự mở lại mọi mục đã hoàn tất.
- Khóa sổ ngân sách chung trước cả đọc/kiểm tra/ghi cấu hình chạy để tránh race giữa experiment; giữ khóa experiment và giải phóng đúng khi lỗi.

## 7. Đánh giá lại năm án và hiện tượng không có AU

1. Lập bảng phân xử nguồn cho toàn bộ 29 mục V3, không chỉ tám mục bị nghi sai: ID/revision, source refs, nhãn đề xuất, kết luận từng thành phần, căn cứ và bất đồng.
2. Phân loại kết luận đánh giá: lỗi rõ / cách hiểu khác có căn cứ / thiếu ngữ cảnh. Khóa rubric trước chạy V4. Nếu chỉ có agent kiểm tra, ghi đúng là agent review, không gọi human gold.
3. Chọn các cơ hội AU có căn cứ trong chính năm án. Ghi nguồn và lý do đủ điều kiện trong bộ đánh giá riêng, không nạp đáp án vào reader end-to-end.
4. Chạy bài chẩn đoán chọn AU trên đoạn nguồn được cung cấp sẵn, tách khỏi chạy đọc toàn án. Phân biệt lỗi khám phá nguồn, lỗi lựa chọn, lỗi giao thức và lỗi verifier.
5. Nếu không xác nhận được cơ hội AU trong năm án, báo giới hạn của mẫu; ví dụ bổ sung ngoài mẫu chỉ là bài chẩn đoán riêng, không nhập vào điểm hiệu chỉnh.
6. Dùng các lỗi đã biết làm regression, thêm đoạn chưa dùng để chỉnh prompt trong cùng năm án. Báo riêng hai nhóm; chúng vẫn là dữ liệu hiệu chỉnh, không phải held-out độc lập.
7. Không tăng điểm bằng cách bác hết mục khó. Báo song song độ đúng của mục accepted, mục bỏ sót trong tập cơ hội đã phân xử, needs_review và phần nguồn chưa đọc.

## 8. Thứ tự triển khai và file dự kiến

| Ưu tiên | Công việc | File/phạm vi |
|---|---|---|
| P0 | Rubric và bảng phân xử, ví dụ AU dương/âm | Tài liệu rubric mới, fixtures đánh giá riêng |
| P0 | Schema chung và verifier từng ref/thành phần | schema.py, prompts.py, state.py, pipeline.py |
| P0 | Checkpoint trước repair, chống thao tác phụ thuộc sai | state.py, pipeline.py, tests/ |
| P1 | Handle nguồn, cung cấp đầy đủ đoạn, coverage | source.py, pipeline.py, tests/ |
| P1 | Cache envelope, JSON repair, recheck, khóa | endpoint.py, __main__.py, pipeline.py, tests/ |
| P1 | Báo cáo ba chiều và xác nhận đánh giá | Bộ report/compare hiện có; kiểm tra tên file thực tế khi triển khai |
| P2 | Smoke nhỏ và chạy năm án pilot_v4 | outputs/pilot_v4/, không sửa outputs/pilot_v3/ |

Các ưu tiên P0/P1 phải đạt kiểm thử trước chạy cả năm án. Không cần đổi model hay mở rộng taxonomy để hoàn thành các bước này.

## 9. Kiểm thử bắt buộc

- Ví dụ hợp đồng đều qua cùng validator; reader/finalizer rỗng vẫn nhận đủ schema/rubric.
- Attribution_checks thiếu/thừa/trùng ID, evidence rỗng cho accepted hoặc căn cứ chưa cung cấp đều bị bác.
- Câu tòa dẫn lời đương sự, câu thuật sự kiện tố tụng, câu nhiều chủ thể, headnote và luật trích được kiểm tra theo rubric, không theo tác giả tài liệu.
- Finding không tự thành issues; final order khác posture; luật trích không tự thành facts.
- AU current_court không có citation vẫn hợp lệ kỹ thuật với treatment unknown; applies/distinguishes thiếu căn cứ không accepted.
- Rejected add A → valid add B → update ID đoán của A không được làm đổi B.
- Inject crash trước/sau request sửa và trước/sau commit: không mất thao tác hợp lệ, không áp dụng hai lần, không cấp lại dự phòng.
- Envelope và operation cùng lỗi chỉ dùng một lượt sửa; trường điều khiển đã hợp lệ không đổi; lỗi còn lại được báo.
- Verifier sai ID có đúng một lần sửa; recheck không mở lại request transport không rõ.
- Chuỗi JSON có dấu giống mẫu regex không bị biến đổi nội dung; response HTTP 200 lỗi cấu trúc tách khỏi uncertain transport.
- Cache đúng identity không gọi trùng; cache sai nguồn/model/payload/response checksum bị chặn.
- Giữ hồi quy 503→200, 503 hết hạn, 400/401/403, timeout, ngân sách hữu hạn và unlimited, khóa giữa experiment.
- CRLF/CRCRLF, Unicode, câu lặp, citation, đoạn dài và cửa sổ chồng lấn giữ nguyên byte/hash/tọa độ; coverage phản ánh đúng nguyên văn thực tế đã gửi.
- Báo cáo đọc V1/V2/V3/V4 riêng, không gộp chỉ số diễn giải và trích xuất; không gộp lỗi thao tác với mục bị verifier bác.

## 10. Chạy thử và điều kiện mở 20 án

Trình tự: unit test → compileall → git diff --check → preflight → kiểm tra protocol bằng response lưu sẵn → smoke nhỏ → một lần chạy năm án với fingerprint cố định → phân xử kết quả.

Replay response cũ chỉ kiểm tra cơ chế xử lý, không chứng minh model sẽ tuân thủ prompt V4. Không gọi API trong bước viết kế hoạch này. Trước chạy thật, báo dự toán từ số request/token đo được; không gọi dự phòng là chi phí thực tế.

Chỉ mở 20 án khi đồng thời đạt:

- Nguyên văn, nguồn và vị trí đúng 100%; không mất thao tác hoặc mục mà thiếu lịch sử.
- Không còn lỗi giao thức chưa giải quyết trong năm án; không phân loại nhầm protocol_failure thành empty_output.
- Mọi mục accepted đã được kiểm tra trực tiếp từng thành phần theo rubric khóa trước; không còn lỗi xác nhận rõ mà vẫn được xuất là accepted.
- Needs_review được giữ riêng, không nằm trong KB accepted; mọi bất đồng attribution được ghi, không ép kết luận để qua cổng.
- Có bằng chứng chẩn đoán khả năng tìm và kiểm chứng AU trên cơ hội đã xác nhận; không thay bằng yêu cầu số AU tối thiểu.
- Báo cáo nêu rõ người/agent đánh giá, giới hạn mẫu, phần nguồn chưa đọc và khả năng bỏ sót. Passing unit tests, coverage cao hay nhiều AU không tự chứng minh chất lượng COLIEE retrieval.

Nếu chưa đạt, sửa đúng tầng gây lỗi và tiếp tục có kiểm soát. Không đổi tên experiment để che lỗi, không chạy lại toàn bộ nhiều lần mà chưa biết cần kiểm tra giả thuyết nào.
