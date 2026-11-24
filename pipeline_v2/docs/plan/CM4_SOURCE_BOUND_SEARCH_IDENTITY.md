# CM4 — khóa nguyên văn A và kiểm định danh B

Phạm vi ngày 22/11/2026. Áp dụng cho pilot dual-query/rerank. Giữ Qwen3.6-27B-FP8, corpus, index, pool 50, reranker và top 10 passage. Kết luận cuối của model vẫn khóa theo `(search_query_id, B)`. Đọc [pilot 149 lượt](../../../cache/cm4-final-once-schemafix-20261121-164159348/semantic_steps.md) để đối chiếu. Pilot có ba select bị rà soát là sai nguồn và một request cuối `finish_reason=length`. Hai thay đổi dưới đây xử lý chọn ý và định danh. Phục hồi output bị cắt thuộc công việc riêng.

Bản 23/11/2026 triển khai các mục 5–8 trong profile thử `--survey-first` và mục 9 bằng `--profile-timing`. Cả hai cờ được khóa lúc `prepare`. Trần live giữ 1.024 token. Thử mức 1.536 phụ thuộc số liệu batch thực tế. Đường chốt trực tiếp hiện chỉ dùng header gốc có các trường citation, ngày và hồ sơ trong cùng cụm tự định danh ở đầu quyết định. Quét 7.708 file của corpus không tìm được header đủ điều kiện theo quy tắc này. Ca dương dùng fixture và đã được kiểm từ ref A đến prediction. Chất lượng ngữ nghĩa, số lượt tiết kiệm và các đỉnh latency cần AG kiểm live.

**Điều chỉnh kế hoạch 24/11/2026, chưa triển khai:** [mục 5.6](#56-model-quyết-định-hoàn-thành-khảo-sát-và-map-thu-hẹp) thay gate khảo sát hết A/xử lý hết unresolved bằng quyết định hoàn thành khảo sát của model. Vẫn gom nhu cầu trước retrieval; host lưu trung thực phần đã giao, đã xét, bỏ qua và chưa khảo sát. Các checkpoint 23/11 ở trên mô tả code hiện hành, không phải bằng chứng đã triển khai điều chỉnh này.

## 1. Khóa lượt tìm vào nguyên văn A

Mục này mô tả luồng đã triển khai ở pilot. Phương án tiếp theo ở [mục 5](#5-khảo-sát-a-trước-rồi-gom-nhu-cầu-tìm) đổi thời điểm cấp permit, đồng thời giữ các kiểm tra nguyên văn, ref và hash.

1. Host giao nguyên văn paragraph đang xét, ref và gợi ý các mục/câu bằng ranh giới văn bản. Gợi ý không phải đơn vị pháp lý bắt buộc. Model có thể chọn ref hoặc trích một phần câu, một câu hay vài câu liền nhau trong vùng đang có.
2. Host khớp literal vào A đang hiển thị và lấy lại UTF-8 byte offsets, hash nguồn và nguyên văn. Chấp nhận chuẩn hóa khoảng trắng, xuống dòng và dấu ngoặc kép tương đương. Nếu có nhiều vị trí khớp, hiển thị các vị trí và yêu cầu chọn ref. Gần khớp chỉ tạo gợi ý để chọn lại. Không dùng kết quả fuzzy làm evidence hoặc cấp permit. Draft phục hồi giữ quyết định và phần context đã chọn.
3. Một quyết định áp dụng đúng span chính. `search_needed` cấp permit khi model thấy đủ nghĩa. Có thể đính ref lời dẫn và citation theo vai trò, trong phần A đã được cấp thuộc vùng phù hợp. Các ref chỉ hỗ trợ không tự đóng phần đó. `no_search_needed` ghi đúng span và lý do. `need_more_context` giữ công việc đang làm và cấp đường mở vùng lân cận. Chặn span chỉ gồm heading đã nhận diện chắc, kể cả khi có citation đính kèm. Cho phép ý hợp lệ ngắn và ý nằm giữa paragraph dài.
4. Lượt tìm nhận duy nhất permit ref. Host xác minh đúng nguồn và lấy text canonical từ dữ liệu đã khóa. Không nhận issue hay proposition mới. Mặc định dùng nguyên văn mệnh đề, kèm citation đã chọn ở văn bản tìm kiếm nếu có. Các nhánh có đầu vào giống hệt chỉ gọi một lần và không đóng góp RRF hai lần. Reranker tiếp tục dùng nguyên văn mệnh đề chính. Lưu span và text hash của nội dung đã đưa vào từng tầng. Nhánh cụm từ trích chỉ là biến thể đối chứng sau, chọn từ các span đã xác nhận trước khi cấp permit. So với baseline nhánh diễn giải rồi mới quyết định có bật. Đo gold theo case_id ở cả union, pool và shortlist.
5. Sau search giữ ref về vùng vừa xét, hiển thị các đoạn raw đã nhận nhưng công việc chưa hoàn tất và cấp đường mở thẳng. Độ phủ dựa trên span quyết định; raw đã giao, heading, lời dẫn và citation hỗ trợ được ghi riêng. Không đánh dấu cả paragraph xong vì một ý đã search. Phần chồng lấn đã xử lý có thể là context của một ý mới; tránh cấp lại đúng span đã xử lý như một việc mới.

Ca kiểm thật từ `021095.txt`: 1(a) và 1(b) trong [2] còn độc lập; [18] `unless` đi cùng hai điều kiện nếu model chọn chung; [20] `[8834,9151)` không thể chạy bằng lời diễn giải của [29]; `Failure to Consider` `[9151,9170)` không tự có permit; [21]–[27] đã giao raw vẫn có đường quay lại. Thêm ca quote trùng sau chuẩn hóa, quote lỗi chữ, Unicode nhiều byte, cue sai vai trò hoặc ngoài scope, resume và stale permit. Hai lượt thông thường vẫn là xét rồi tìm; đếm lượt phát sinh khi phải làm rõ.

## 2. Lượt chốt chỉ kiểm định danh B

Mục này mô tả luồng đã triển khai ở pilot. [Mục 6](#6-host-ghi-kết-luận-b-theo-nhãn-định-danh) quy định đầu ra dự kiến của lượt chốt và cách host ánh xạ nhãn. [Mục 8](#8-tự-quay-về-danh-sách-sau-khi-chốt-b) quy định màn hình sau khi ghi kết luận.

1. Model đọc B bằng luồng hiện tại, có thể chốt không chọn trực tiếp nếu đã quyết định loại. Nếu định chọn, nó chủ động yêu cầu lượt kiểm định danh. Yêu cầu này chưa tạo kết luận. Host kiểm gói đã có tài liệu cho ba vai trò, nếu thiếu thì chỉ rõ vùng hoặc loại bằng chứng cần mở, giữ B pending.
2. Host đóng băng gói cho đúng query và B. Gói gồm ngữ cảnh A chỉ đến authority của source need, văn bản nói về chính B, và đoạn B có quy tắc cùng câu dẫn hoặc ngữ cảnh attribution. Dùng nguồn đã giao và kiểm lại hash/span khi dựng payload. Gói được cấp lại với ref phân vai. Không chuyển lý do select do model viết ở lượt trước vào prompt chốt. Điều kiện ngày/cấp tòa chỉ dựa trên thông tin tự định danh đã xác minh. Văn bản vụ việc không mặc nhiên cung cấp ngày phán quyết.
3. Lượt này chỉ có `conclude_candidate`. Select phải viện dẫn A và tự định danh B và nêu cầu nối. Một ref thân án trích X không tự đủ điều kiện làm ref định danh chính B. Nếu có căn cứ A nói về một phán quyết khác, dùng `different_decision`. Nếu gói hiện tại chưa đủ, dùng `insufficient_identity`. Hai lý do cùng là `not_select` nhưng có nghĩa khác nhau. Theo dõi metadata bị che, thiếu và chưa đọc riêng khi có dữ liệu.
4. Host kiểm query/B đang mở, gói bị ràng buộc vào phiên, vai trò ref, nguồn, schema và khóa chốt một lần. Model chịu trách nhiệm phán đoán cầu nối ngữ nghĩa. Lỗi schema, length hoặc transport giữ B chưa chốt. Không suy đoán quyết định từ output dở. Khi chốt vẫn có thể mở lại để đọc; kết luận đã commit không đổi. Quote provenance, hoàn tất giao thức và gold COLIEE được báo riêng.

Ca kiểm: T054 ở B `011064.txt` dùng cùng ref thân [37] cho rule và identity, khi thân đang dẫn Aqua-Gem. Kiểm T048 và T102 với nguyên văn tự định danh B; ngày lệnh bị kháng cáo của A không thay được ngày phán quyết. Ca dương [23] của A có `244 F.T.R. 256` và một nguồn `see also` riêng; chỉ dùng làm đối chứng dương khi đã xác minh reporter đó là định danh chính B. Có thêm ca B tự định danh rõ dù passage B trích án thứ ba, metadata bị che, ref sai vai trò/sai cặp, gói quá cap, reply lỗi và submit lại sau kết luận.

## 3. Tích hợp và nghiệm thu

- Triển khai theo thứ tự khóa permit, phần còn việc của A, gợi ý span; tích hợp lượt chốt B trên contract A đã ổn định. Giữ nhánh đối chứng cũ cho các caller ngoài pilot.
- Dùng `.venv/Scripts/python.exe` kiểm các contract, replay ledger theo namespace mới và giữ lịch sử pilot ở chế độ chỉ đọc. Test tập trung vào từng lỗi với snapshot/nguyên văn, không suy ra semantic accuracy từ hành động được script.
- Đo trước/sau trên cùng model và cùng nguồn. Báo coverage A, số search, gold đến pool/top 10, chọn sai/bỏ sót, lý do không chọn, lượt/usage thêm ở B và lỗi transport. Chỉ báo F1 với dự đoán cuối và evaluator hợp lệ.
- AG chạy model thật sau khi kiểm local. Khi chuẩn bị run mới, binding của code/prompt/query phải đúng với code đang chạy. Giữ cùng call lúc chờ GPU và giữ số đo request lỗi. Không sửa ledger/artifact đã có.

## 4. Phạm vi bản triển khai đầu

- Frontend của model dùng `assess_source_need`, với `proposition_ref` hoặc `proposition_quote`, và `a_supports` có vai trò. `choose_source_span` xác nhận vị trí literal, `read_source_context` mở vùng quanh draft và `revise_source_need` thu hồi permit chưa dùng. Catalog cấp tối đa một nhóm nhỏ các đường quay lại A mỗi lượt. Gợi ý dựa trên câu/mục và vùng văn bản đã nhận. Phân mục pháp lý vẫn do model quyết định.
- Heading lấy từ cấu trúc corpus và nhận diện bố cục hẹp cho dòng tiêu đề trước đoạn đánh số. Metadata đã seal của `021095.txt` không có heading quanh byte 9151, nên ca `Failure to Consider` dựa vào bố cục của nguồn nguyên văn. Cần đánh giá thêm trên các định dạng án khác.
- Ref tự định danh B hiện ưu tiên dòng tự định danh trong preamble và phần mở đầu có mẫu tên thẩm phán khi thiếu header. Chưa có bộ nhận diện tổng quát cho closing hoặc tự định danh ở giữa thân án. Vì vậy án có metadata bị che hoặc định danh ở vị trí khác có thể thiếu đường `select` trong bản đầu. Theo dõi nhóm này khi đo recall.
- Lượt kiểm định danh dùng các ref theo vai trò và một lý do cầu nối ngắn. Chọn đúng ref và hợp lệ về schema vẫn cần được đánh giá bằng model thật. Chưa có đối chứng live cho ca `244 F.T.R. 256` hay kết quả F1 của bản này.

## 5. Khảo sát A trước rồi gom nhu cầu tìm

Thiết kế nền ngày 23/11/2026 khảo sát hết A theo từng vùng đang vừa ngân sách context, lưu các đoạn cần tìm, rồi chuyển sang retrieval và review B. **Kế hoạch thay thế ngày 24/11 ở mục 5.6 giữ khảo sát/gom trước retrieval nhưng để model quyết định khi nào đã đủ; không bắt buộc đọc hết A hoặc xử lý mọi unresolved.** Pilot `cm4-map-loop-fix-ag-20261122-203215184` mất ba lượt tìm cho cùng lệnh ở [5] và cắt hai khối trích ở [18] qua ba query. Khảo sát trước cho host cơ hội thấy các đánh dấu liên quan trước khi trả chi phí tìm và duyệt B.

### 5.1. Khảo sát và lưu đánh dấu

1. Model đọc từng vùng A, đánh dấu đoạn nguyên văn cần tìm và có thể chọn ref lời dẫn, điều kiện, hoặc citation. Phần đã xét và không cần tìm ghi quyết định theo span. Phần cần thêm ngữ cảnh giữ đường mở lại.
2. Host xác minh ref, hash nguồn và byte offsets như luồng hiện tại. Đoạn cần tìm được lưu vào danh sách chờ, kèm ranh giới khối trích và vai trò từng ref. Catalog tiếp tục cho model khảo sát các vùng A khác. Embedding, retrieval và reranker bắt đầu ở pha sau.
3. Lưu riêng các span đã giao, đã xét, đã đánh dấu cần tìm, và đã tìm. Ref hỗ trợ chỉ mang ngữ cảnh. Khi dừng hoặc resume giữa pha khảo sát, giữ các đánh dấu đã ghi cùng vị trí còn việc. Theo điều chỉnh 24/11, gom trong quá trình khảo sát và chốt danh sách khi model chọn hoàn thành; các mục còn thiếu ngữ cảnh được lưu riêng để mở lại, không chặn chuyển pha toàn cục.

### 5.2. Gom và cấp quyền tìm

1. Host gom các đánh dấu có căn cứ rõ ràng rằng chúng chỉ tới cùng quyết định. Ví dụ, cùng một citation được gắn đúng vào quyết định đang dẫn, hoặc cùng lệnh đã được chỉ rõ bằng ngày, người ra lệnh và hồ sơ. Citation phải thuộc đúng khối trích. Chỉ trùng câu luật, tên thẩm phán, số hồ sơ, hoặc vị trí trong cùng paragraph thì vẫn giữ riêng.
2. Với các dấu hiệu chưa đủ để gom, mặc định tạo nhu cầu riêng. Có thể hiển thị gợi ý để model xác nhận liên kết khi hai đoạn có căn cứ đáng kiểm. Chỉ làm rõ nhóm mơ hồ khi cần, tránh thêm một lượt model cho mỗi đánh dấu.
3. Mỗi nhóm có một ref đoạn chính và các ref hỗ trợ đã xác minh, giữ liên kết về mọi span thành viên. Host khóa một permit cho truy vấn dựng từ nguyên văn của nhóm và citation đúng phạm vi. Khi nhóm có kết quả, ghi kết quả gắn với các đánh dấu đã được xác nhận thuộc nhóm. Các đoạn chưa xét vẫn còn việc. Review B tiếp tục chỉ đọc các hit trong top 10 và giữ kết luận theo lượt tìm.

### 5.3. Ca kiểm và số liệu

| Ca kiểm trên `021095.txt` | Kết quả mong đợi |
| --- | --- |
| [5] với lệnh Hargrave ngày 10/02/2003 | Ba phần có bằng chứng cùng lệnh được gom thành một nhu cầu tìm. Giữ đủ ref cho phần bác ba hồ sơ, phần cho T-1523-01 tiếp tục và đoạn trích [31]. Ca dương `070847.txt` vẫn có đường vào shortlist và được model kiểm định danh. |
| [18] với hai khối trích | Giữ hai khối riêng. Nhánh (a)/(b) thuộc khối chứa câu dẫn của nó. Ref `315 N.R. 175 (F.C.A.)` chỉ gắn khối sau. |
| [2], [13], [23] | Các ý độc lập trong [2] vẫn đánh dấu riêng khi cần. Model phân biệt lệnh về McIvor-Grismer ở [13] với lệnh Dewar đang bị kháng cáo. Ở [23], citation chính và `see also` vẫn có thể tạo hai nhu cầu. |
| Scope và resume | Các lượt khảo sát phát 0 request embedding, retrieval và reranker. Resume giữ đúng hàng chờ và độ phủ. Sau khi gom, permit giữ nguyên text/hash và chỉ khởi chạy một search cho nhóm đã khóa. Hai lệnh cùng hồ sơ nhưng khác ngày hoặc nội dung vẫn có đường tìm riêng. |

So với pilot theo cùng phạm vi byte đã xét, đo số đánh dấu, số nhóm, số search và lượt controller, token, thời gian đến search đầu tiên, thời gian chờ GPU, thời gian dựng context và ứng viên đúng vào pool/top 10. Kiểm cả ca gom nhầm và ca tách thừa. Chạy replay offline trên nguyên văn trước, rồi giao AG thử live trong namespace mới.

### 5.4. Thử tối đa ba quyết định A mỗi lượt

- Trong pha khảo sát A, model có thể gửi **từ một đến ba quyết định** cho các span đang hiển thị trong cùng payload. Schema và host đều giới hạn tối đa ba mục. Mỗi mục có ref và quyết định riêng. Ưu tiên ref sẵn có và lý do ngắn để giữ trần output thử nghiệm ở 1.024 token. Đoạn phức tạp có thể xét riêng một lượt.
- Host ghi coverage theo từng span đã được xử lý hợp lệ. Span model bỏ qua hoặc đánh dấu cần đọc thêm vẫn còn việc. Span đánh dấu cần tìm vào danh sách chờ của pha khảo sát. Host kiểm ref trùng, sai phạm vi và các quyết định xung đột trên span chồng lấn.
- Nếu cả reply bị cắt hoặc không parse được, giữ nguyên coverage và danh sách chờ của lượt đó. Chỉ thử lại với nhóm nhỏ hơn sau khi đã xác nhận receipt cuối là `finish_reason=length` và chưa có action thực thi. Các ca còn pending hoặc chưa rõ receipt tiếp tục theo dõi request gốc.
- Kiểm lượt trả một, hai và ba mục, trường hợp trả quá ba, ref lỗi, reply hợp lệ còn bỏ sót span, và reply bị cắt. So với luồng một mục mỗi lượt trên cùng lượng byte đã xét, đếm lượt controller, token, tỷ lệ `length`, lượt thử lại và số span bị bỏ sót.

#### Trần output theo loại lượt

- Bắt đầu thử ba mục với trần 1.024 token. Ledger pilot T229 có 37 lượt `assess_source_need` theo luồng một mục mỗi lượt, reply dài nhất 285 output token. Số này dùng làm mốc đối chiếu. Đo trực tiếp phân bố output và tỷ lệ `length` khi thử ba mục.
- Nếu các lượt khảo sát có thể trả nhiều mục vẫn thường xuyên chạm trần sau khi đã dùng ref ngắn, thử trần **1.536 token chỉ cho loại lượt đó**. Các lượt điều hướng và chốt B giữ trần đang dùng. Host chọn và ghi cap trước khi gửi từng request, kiểm tổng input và cap output nằm trong context. Trước khi thử mức cao hơn, đồng bộ mức cho phép ở host và app Modal, rồi prepare namespace mới với binding tương ứng.
- So sánh 1.024 và 1.536 trên cùng lượng byte A đã xét. Tính cả số request thử lại, token thực sinh, thời gian và span bỏ sót. Giữ 1.024 nếu batch ba mục chạy ổn định. Chỉ dùng mức cao hơn cho lượt nhiều mục khi kết quả đo cho thấy giảm đủ thời gian hoặc lượt thử lại.

### 5.5. Cấp thẳng nguyên văn A ở bước điều hướng xác định được

- Khi bắt đầu pha khảo sát và khi vùng A đang đọc đã xét xong, host tìm byte chưa xét đầu tiên theo thứ tự văn bản. Host cấp nguyên văn của vùng chứa byte đó nếu vừa context. Với vùng quá rộng, host tự xuống vùng con theo cây nguồn và dùng phép đếm token hiện có. Lượt tiếp theo có thể đánh giá A ngay.
- Nếu vùng hiện tại còn span chưa xét, draft còn vướng hoặc request đang phục hồi, giữ nguyên vị trí trong cơ chế cấp tự động hiện hành. Điều hướng do model chủ động chọn vẫn có các tool hiện tại. Điều chỉnh 24/11 ở mục 5.6 thay điều kiện chuyển pha cũ và cho phép model bỏ qua/mở lại hoặc hoàn thành sớm; không dùng cơ chế tự cấp vùng tiếp theo để buộc model đi hết A.
- Ghi vùng được cấp tự động trong admission để khôi phục cùng vị trí sau restart. Preview chỉ dựng payload. Cấp nguyên văn không tự thay đổi số byte đã xét hoặc số lượt đánh giá. Chạy đối chứng trên cùng lượng byte đã xét, đếm riêng lượt `open_query` và `show_context_page` còn lại.

### 5.6. Model quyết định hoàn thành khảo sát và map thu hẹp

**Quyết định thiết kế ngày 24/11/2026 — chỉ lập kế hoạch trong đợt này.** Áp dụng cho profile thử `--survey-first`; giữ model, chunk, corpus, index, reranker, top 10, giới hạn context/output và kiểm định danh B hiện hành. Không tự triển khai, inference hoặc deploy từ việc cập nhật tài liệu này. Mục này có hiệu lực thay các câu yêu cầu khảo sát hết A hoặc xử lý hết unresolved ở mục 5.1–5.5; các quy tắc nguồn và gom đúng authority vẫn giữ.

#### Mục tiêu và hợp đồng hiển thị

- Payload luôn ghi rõ **SURVEY PHASE** khi đang khảo sát: đọc A để nhận diện và gom các nhu cầu tìm án B mà A viện dẫn hoặc sử dụng làm nguồn cho nhận định, lập luận hay quy tắc pháp lý; chưa thực hiện retrieval. Nội dung tương tự về chủ đề hoặc quy tắc chưa đủ để tạo nhu cầu tìm nguồn. Model quyết định nhu cầu ngữ nghĩa, host xác minh ref, offsets, hash và ghi provenance.
- Map mặc định chỉ hiện các phần còn trong lượt khảo sát hiện tại. Danh sách nhu cầu đã ghi nhận là phần riêng, có phân trang và tổng số, giữ ref mở lại mọi span thành viên cùng trạng thái gom/tìm. Một nhu cầu biến mất khỏi map không mất evidence và không tự thành đã tìm.
- Hiện tóm tắt độ phủ và số phần đã ẩn, kèm đường **Mở lại phần đã ẩn**. Map rỗng chỉ có nghĩa không còn mục trong chế độ xem hiện tại; không tự chứng minh A đã được đọc hết hoặc không còn citation.
- Có lựa chọn **Hoàn thành khảo sát** từ các màn hình khảo sát A, kể cả khi còn phần chưa đọc hoặc unresolved. Model có thể tiếp tục khảo sát toàn bộ nếu thấy cần. Không đặt ngưỡng phần trăm coverage, số đoạn, số nhu cầu tối thiểu hoặc xác suất do host suy đoán để thay quyết định này.

Mô tả đầy đủ cho lựa chọn hoàn thành khảo sát:

> Hoàn thành khảo sát và chuyển sang tìm kiếm. Chọn khi bạn đã ghi nhận, gom các nhu cầu tìm án B mà A viện dẫn hoặc sử dụng làm nguồn cho nhận định, lập luận hay quy tắc pháp lý, và đánh giá rằng không cần đọc thêm phần A còn lại để phát hiện nhu cầu mới hoặc bổ sung cho nhu cầu đã có. Án chỉ có nội dung tương tự chưa đủ để trở thành một nhu cầu tìm nguồn. Những phần chưa đọc vẫn được ghi là chưa khảo sát.

Không diễn đạt quyết định này thành “A không còn citation nào khác”. Ý nghĩa được lưu là **model đánh giá không cần khảo sát thêm để xác lập các nhu cầu tìm nguồn hiện có**, không phải host chứng nhận đã phát hiện đầy đủ mọi nguồn của A.

#### Trạng thái host và map đi tới

Không dùng một cờ `done` chung cho việc hiển thị map, đọc A, xử lý nhu cầu và retrieval. Tên trường dưới đây là đề xuất contract khi triển khai; mọi interval dùng UTF-8 byte offsets `[start, end)` gắn với source hash.

| Trục trạng thái | Dữ liệu tối thiểu và ý nghĩa |
| --- | --- |
| Đã giao nguồn (`exposed`) | Raw thực sự được giao trong admission/receipt hợp lệ; preview hoặc chỉ mở map không tính là đọc raw. Giao raw chưa chứng minh model đã xét nội dung. |
| Đã xét (`assessed`) | Span có quyết định hợp lệ của model, gồm cần tìm hoặc không cần tìm. Support ref chỉ cung cấp ngữ cảnh; không tự đóng span khác. |
| Bỏ qua (`skipped`) | Span được model chủ động bỏ qua khi đi tới, lưu action, lý do ngắn và thời điểm. Không tăng exposed/assessed; phần chưa được xét vẫn là chưa khảo sát. |
| Đang ẩn (`hidden`) | Trạng thái trình bày, có thể do đã xét/đã đánh dấu hoặc bị bỏ qua. Có nguyên nhân ẩn và đường mở lại. Mở lại không xóa lịch sử quyết định hay evidence. |
| Còn việc/chưa khảo sát | Tính từ nguồn và các span đã xét, phân biệt chưa giao, đã giao nhưng chưa xét, skipped chưa xét, và unresolved. Các số liệu có thể chồng lấn theo trục; không cộng chúng thành một tỷ lệ hoàn tất giả. |
| Nhu cầu đã ghi nhận | ID ổn định, span chính, support refs phân vai, thành viên nhóm, trạng thái approved/unresolved/deferred/searched và liên kết query/kết quả. Không phụ thuộc vòng đời item trên map. |
| Pha và lần chốt khảo sát | `survey` hoặc `retrieval`, revision của danh sách nhu cầu, event hoàn thành, lý do model và snapshot coverage/phần còn lại. Nếu quay lại khảo sát, lưu revision mới và giữ event cũ. |

**Ví dụ đoạn 1–3:** model chỉ đọc/xét đoạn 3 thì host chỉ ghi exposure/assessment của đúng span đoạn 3. Không đánh dấu đoạn 1–2 đã đọc. Nếu model muốn cả 1–3 biến mất khỏi map, dùng lựa chọn đi tới có thông báo rõ **bỏ qua các phần trước vị trí này**: ghi skipped cho phần chưa xét ở 1–2, còn 3 giữ trạng thái thực tế của nó. Hành động chỉ mở/đọc đoạn 3 không mặc nhiên mang ý nghĩa bỏ qua 1–2. Khi đoạn chứa nhiều ý, chỉ trừ đúng interval đã xét; phần còn lại vẫn còn việc hoặc được bỏ qua rõ ràng.

Map cần lọc theo interval thực tế, không xóa cả paragraph/nhánh cha chỉ vì một span con được đánh dấu. Khi vùng chỉ còn một phần chưa xét, cấp đường mở đúng phần đó, vẫn cho đọc ngữ cảnh lân cận. Mở lại 1–2 đưa chúng về chế độ xem đang khảo sát, giữ lịch sử skipped; chỉ quyết định mới trên đúng span mới tăng assessed. Việc compact refs, phân trang, map vượt cap hoặc dựng preview không được tự sinh event bỏ qua/đã xét.

#### Chốt khảo sát, gom và chuyển pha

1. Trong survey, model tiếp tục đánh dấu tối đa ba quyết định/lượt theo contract hiện tại. Host gom citation exact đúng phạm vi như hiện hành; cho model xác nhận nhóm có căn cứ ngay trong survey thay vì đợi `survey_ready` cũ. Không ép giải quyết mọi cặp nhóm mơ hồ: giữ riêng là lựa chọn hợp lệ. Giữ phân biệt hai khối [18], các lệnh khác ngày/nội dung và các nguồn `see also`.
2. Bổ sung action đề xuất `complete_source_survey(reason)`. Host kiểm đúng pha, đúng revision/admission, reply hợp lệ và không có request/action khác đang pending hoặc kết quả chưa rõ. Draft chưa commit, unresolved hoặc phần chưa đọc được giữ trong snapshot; chúng không phải gate ngữ nghĩa toàn cục. Action hoàn thành là action riêng sau khi batch đánh dấu đã commit; không suy hoàn thành từ output bị cắt hoặc trộn thêm quyết định chưa thực thi trong cùng lần chốt.
3. Commit nguyên tử event hoàn thành và snapshot danh sách nhu cầu/nhóm hiện có, cùng phần chưa khảo sát, unresolved/deferred và lý do. Chuyển sang retrieval, không chạy embedding/retrieval/reranker ngay bên trong action hoàn thành. Nếu chốt lỗi hoặc receipt chưa rõ, không đổi pha và không cấp permit chạy tìm. Replay cùng action không tạo lần chốt hoặc search trùng.
4. Sau chốt, các nhóm approved được cấp permit theo nguyên văn, hash, citation scope và ngân sách embedding hiện hành. Nhóm chưa hợp lệ hoặc span đơn vượt cap vẫn unresolved và chỉ chặn tìm chính nhóm đó. Một unresolved không ngăn nhóm approved khác tìm. Có thể hoàn thành khảo sát với 0 nhu cầu: không phát truy vấn rỗng, không tự tạo nhu cầu mới và không tuyên bố A không viện dẫn án nào.
5. Trong survey, schema và host đều chặn đường tìm, kể cả gọi action trực tiếp bằng permit cũ. Cả embedding, retrieval, reranker và tra citation có thể tự chốt B theo mục 7 đều chỉ được thực thi ở pha sau. Gom và xác minh ref/hash cục bộ không phải retrieval. Khi đã chốt, bỏ gate yêu cầu hết byte chưa xét/hết unresolved ở cả catalog lẫn execute; giữ mọi gate nguồn, cap và định danh hiện hành.
6. Hết map/hết byte chưa xét không tự chuyển pha. Vẫn hiển thị danh sách nhu cầu và lựa chọn hoàn thành để model chốt; không tạo yêu cầu phải giải quyết hết unresolved. Cơ chế tự cấp vùng tiếp theo chỉ hoạt động khi survey còn mở, dùng trạng thái còn việc và skipped mới, không đưa lại vùng đã bỏ qua chỉ để đạt độ phủ toàn A.
7. Giữ đường mở lại phần ẩn và quay lại survey khi model cần bổ sung. Khi một search query đang active, vẫn cho đọc A theo quyền hiện hành nhưng hoãn sửa nhóm/permit hoặc quay pha đến ranh giới query an toàn. Sau khi quay lại survey, ghi revision mới, giữ query/kết luận cũ và chốt lại trước lần tìm mới. Không sửa permit đã dùng, không xóa evidence và không tự tìm lại nhóm đã tìm chỉ vì mở lại map.

#### Resume, kết quả và số đo

- Persist phase, intervals, nguyên nhân ẩn/bỏ qua, hàng chờ/nhóm và event chốt vào ledger; dựng lại từ event đã commit khi restart. Phân biệt dừng giữa survey, dừng sau chốt nhưng chưa search và dừng giữa review B. Drift nguồn làm refs/đánh dấu mất hiệu lực theo cơ chế hiện hành; không dùng snapshot cũ để cấp permit trên nguồn mới.
- Báo riêng `survey_completed_by_model`, full/partial A coverage và phần chưa khảo sát. Hoàn thành pha do model chọn không đồng nghĩa full coverage. Khi kết thúc còn A chưa khảo sát hoặc nhu cầu unresolved/deferred, kết quả phải thể hiện phạm vi đó, giữ prediction đã có và trạng thái review/retrieval riêng; không coi chốt survey là chứng nhận hoàn tất toàn A hay tự đổi lỗi/budget/STOP thành complete. Contract nhãn final phải kiểm cùng cơ chế partial hiện hành trước triển khai.
- Đo byte đã giao/đã xét, byte skipped chưa xét, phần còn lại, số needs/nhóm, số unresolved, lần mở lại, thời điểm chốt và thời gian đến search đầu. Báo request/token/latency controller, embedding, reranker gồm lỗi/retry/unknown; không coi dừng sớm hay thiếu evidence là tiết kiệm.
- So với gate cũ trên cùng A, model và profile: đo độ phủ lẫn gold recall theo pool/top 10/prediction khi có evaluator. Kiểm nhu cầu bị bỏ sót ở phần chưa đọc, gom nhầm/tách thừa và nhận định đủ khảo sát của model. Kiểm contract bằng fixture không chứng minh semantic recall hoặc cải thiện COLIEE.

#### Phạm vi triển khai dự kiến và thứ tự nghiệm thu

| Bước | File/scope dự kiến | Đầu ra cần đạt |
| --- | --- | --- |
| 1. State và replay | `source_gate.py`, phần context/events trong `engine.py` | Tách phase khỏi `survey_ready` dựa coverage; lưu intervals, skipped/hidden, revision và event chốt. Khôi phục nguyên trạng, không viết lại run cũ. |
| 2. Map và hàng nhu cầu | Bộ dựng map/catalog/compact payload trong `engine.py` và module điều hướng liên quan sau khi kiểm code | Map chỉ hiện phần còn khảo sát; danh sách nhu cầu phân trang riêng; nút mở lại phần ẩn và đi tới có skip rõ ràng; refs round-trip đúng nguồn/cap. |
| 3. Actions và prompt | `engine.py`, `source_gate.py`, `live.py` | `SURVEY PHASE`, mô tả hoàn thành nêu trên, action chốt/quay lại survey, gom trước chốt; khóa tìm trước chốt và mở tìm từng nhóm hợp lệ sau chốt ở cả schema/execute. |
| 4. Result và kiểm local | Phần final/coverage của engine và evaluator liên quan nếu cần; `tests/test_survey_first.py`, `test_survey_auto_navigation.py`, `test_source_gate.py`, `test_engine.py`, `test_live.py` | Kết quả tách model completion khỏi full coverage; regression bảng dưới đạt trên code cuối. Chỉ sửa evaluator nếu cần đưa độ phủ mới vào báo cáo. |
| 5. Pilot | Namespace mới có code/prompt binding, lệnh prepare/run và hướng dẫn AG | Codex chuẩn bị lệnh, người dùng/AG chạy; không resume namespace bind gate cũ như thể cùng policy. So semantic/cost sau kiểm local, không mở sang đổi model/chunk/reranker. |

Khi được giao triển khai đáng kể, Main giao implementer sửa các file production thuộc scope trên và tester kiểm độc lập bản cuối theo AGENTS.md; thống nhất ownership trước khi sửa để tránh hai agent đụng cùng file. Đợt hiện tại chỉ cập nhật kế hoạch.

| Ca nghiệm thu | Kết quả bắt buộc |
| --- | --- |
| Survey chưa chốt, có permit hoặc gọi search trực tiếp | Schema không cấp search; host từ chối bypass; 0 request embedding/retrieval/reranker và không tự chốt B qua citation. |
| Chỉ đọc/xét đoạn 3 | Exposure/assessment chỉ đúng span 3; đoạn 1–2 không bị ghi đã đọc hoặc tự skipped. |
| Đi tới sau đoạn 3 và bỏ qua 1–2 | 1–2 được ghi skipped chưa khảo sát; map ẩn 1–3 theo trạng thái thật; có đường mở lại; coverage không tăng giả. |
| Một ý trong paragraph/nhánh lớn đã đánh dấu | Chỉ span đó rời phần việc mặc định; ý còn lại mở được; need/evidence đã đánh dấu còn trong danh sách riêng. |
| Complete khi chưa đọc hết và còn unresolved | Chốt được; giữ snapshot coverage/unresolved; nhóm approved tìm được, nhóm chưa hợp lệ không có permit; không yêu cầu clear hết unresolved. |
| Complete với 0 needs hoặc map đã hết | Không phát query rỗng/khẳng định không còn citation; chỉ chuyển pha sau action chốt hợp lệ, kể cả khi assessed đủ A. |
| Gom trước chốt và search sau chốt | [5] gom đúng authority; [18] giữ hai khối; ref/hash/cap đúng; một nhóm không phát search trùng qua replay. |
| Reply length/lỗi, stale revision, request pending/unknown | Không commit hoàn thành, không đổi coverage/queue từ output dở, không gửi request thay thế khi receipt chưa rõ. |
| Resume trước/sau chốt, phân trang/compact/vượt cap | Cùng phase, map, hidden/skipped, needs và provenance; preview/render không đổi state; drift không tái dùng permit sai nguồn. |
| Mở lại phần ẩn/quay survey sau search | Giữ evidence/kết luận đã có; chờ query active kết thúc trước sửa nhóm; chốt revision mới trước tìm tiếp; không tự rerun nhóm cũ. |
| Final còn phần chưa khảo sát/unresolved hoặc STOP/lỗi | Báo độ phủ thiếu và trạng thái thực tế riêng; prediction không bị xóa chỉ vì partial; không báo full survey hay semantic PASS từ việc hoàn thành action. |

Kiểm local bằng `.venv/Scripts/python.exe` theo các module thay đổi; thêm replay trên byte gốc của `021095.txt` cho ca 1–3, [5], [18] và khối vượt trang. Nghiệm thu engineering cần đủ evidence của state/schema/execute/resume; nghiệm thu quyết định dừng sớm và chất lượng gom cần pilot model thật, được báo riêng.

## 6. Host ghi kết luận B theo nhãn định danh

Thiết kế ngày 23/11/2026. Dùng lượt chốt định danh hiện có. Trong lượt này, `conclude_candidate` nhận một trường `identity_relation` thuộc enum, kèm các ref trong packet và một câu đối chiếu ngắn. Host dùng duy nhất nhãn hợp lệ để suy ra quyết định. Schema lượt chốt bỏ các trường `decision` và `disposition` do model điền. Kết quả lưu vẫn có `decision` và `disposition` cho các bước đọc kết quả hiện tại.

| `identity_relation` do model trả | `decision` do host ghi | `disposition` do host ghi |
| --- | --- | --- |
| `same_decision` | `select` | `confirmed_identity` |
| `different_decision` | `not_select` | `different_decision` |
| `insufficient_evidence` | `not_select` | `insufficient_identity` |

- Model đối chiếu lời dẫn của A với phần xác định chính B và nguồn của quy tắc trong B. Với `same_decision`, nêu dấu hiệu riêng nối A với chính B và đối chiếu các phản chứng hiện rõ. Với `different_decision`, nêu dữ kiện chỉ sang quyết định khác. Với `insufficient_evidence`, nêu điều còn thiếu. Cùng câu luật chỉ là dấu hiệu giống nội dung. Có thể xác nhận bằng tổ hợp số hồ sơ, người ra quyết định và kết quả khi tên án hoặc citation bị che.
- Giữ ref A, ref định danh chính B và ref quy tắc với vai trò hiện có. Khi xác nhận cùng án hoặc nêu mâu thuẫn, chỉ rõ ref A và ref B làm căn cứ cho nhận định đó. Host kiểm enum, cặp `(search_query_id, B)`, vai trò và provenance của ref, và điều kiện chưa có kết luận. Câu đối chiếu được lưu để truy vết. Phán đoán ngữ nghĩa nằm ở model.
- Nhãn ngoài enum, ref sai vai trò hoặc ngoài packet, đầu ra thiếu hay lỗi schema/transport đều giữ B ở `pending`. Một kết luận hợp lệ mới khóa kết quả của cặp. Mọi bước đọc thêm diễn ra trước khi đóng băng packet. Đường loại B trực tiếp khi đang review giữ theo luồng hiện tại.

Ca kiểm offline gồm đủ ba nhãn và bảng ánh xạ, đầu ra hỏng giữ pending, ref sai vai trò và gọi lại sau khi đã ghi. Replay ngữ nghĩa dùng `070847.txt` ở [5] làm ca dương, `093948.txt` ở [18] làm ca phản chứng về cấp tòa, và packet chỉ có quy tắc giống nhau làm ca thiếu định danh. Kết quả host ánh xạ đúng và kết quả model đọc đúng được đo riêng. Nếu model đọc sai rồi trả `same_decision`, host vẫn có thể ghi sai dù giao thức hợp lệ.

## 7. Chốt trực tiếp khi khớp citation của chính quyết định

Kế hoạch ngày 23/11/2026. Phạm vi đường chốt trực tiếp là citation cụ thể của một quyết định. Tên án đứng ngoài quy tắc này. Sau khi một nhu cầu nguồn đã khóa đúng citation của khối A, host tra citation trong chỉ mục tự định danh của corpus.

### 7.1. Bằng chứng ở hai phía

1. Ở A, citation phải được gắn rõ với đúng khối viện dẫn của nhu cầu nguồn. Lưu ref nguyên văn và phạm vi khối. Khi một vùng có nhiều khối hoặc nhiều nguồn, xác nhận ref nào chỉ tới nguồn đang tìm trước khi tra.
2. Ở B, citation phải thuộc phần tự định danh của chính B. Bằng chứng đủ rõ là trường citation do nguồn cung cấp và gắn với B, hoặc dòng có nhãn `Citation:` trong khối tự định danh có ranh giới rõ của chính quyết định. Regex tìm và chuẩn hóa kiểu viết của số citation, gồm khoảng trắng và dấu chấm tương đương. Vai trò tự định danh dựa vào phạm vi và ngữ cảnh của trường, không suy từ việc trùng số hoặc đứng gần đầu file. Metadata được trích bằng regex cần kiểm lại ref và vị trí nguyên văn trước khi dùng.
3. Citation nằm trong thân án, mục `Cases Cited`, trích dẫn của đương sự, phần mô tả quyết định cấp dưới, hoặc khối có vai trò chưa rõ chỉ là đầu mối. Ví dụ, các số trên dòng 137 của `083611.txt` thuộc án được văn bản đó viện dẫn. File này không được chọn tự động từ các số trên dòng đó. Bản đầu chỉ dùng khớp trực tiếp sau chuẩn hóa; tra citation song song có thể thử sau.

### 7.2. Ghi kết quả và kiểm hồi quy

- Nếu cùng citation xác định duy nhất một B hợp lệ trong tập ứng viên và hai ref qua kiểm nguồn, host ghi ngay `select` cho nhu cầu đó. Lưu citation đã chuẩn hóa, ref A, ref tự định danh B, hash và byte offsets hai phía, cùng nguồn kết luận là đối chiếu trực tiếp của host. Đường này kết thúc nhu cầu mà không cần tìm passage, rerank hoặc hỏi model chốt B. Khóa kết luận một lần và đưa B vào phép tổng hợp kết quả cuối. Thống kê riêng ca host chốt bằng citation và ca model chốt bằng packet.
- Khi thiếu bằng chứng tự định danh, có nhiều án khớp, citation ở A chưa rõ thuộc nguồn nào hoặc có xung đột, đi qua retrieval, top 10 passage và lượt kiểm định danh đã lên kế hoạch. Coverage của A vẫn tính theo span đã xét. Việc khớp một citation không tự xử lý các nguồn khác trong A.
- Kiểm ca duy nhất khớp đúng citation ở hai phía, tên án trùng mà citation khác, số chỉ nằm trong thân hoặc được án cấp dưới viện dẫn, phần mở đầu có số nhưng phạm vi mơ hồ, nhiều file có cùng citation, và ref/hash sai. Kiểm kết quả chốt trực tiếp đi vào tổng hợp cuối và được giữ khi resume. Đối chiếu `315 N.R. 175` với corpus thật; chỉ báo chốt trực tiếp khi tìm được ref tự định danh của án đích.

## 8. Tự quay về danh sách sau khi chốt B

Kế hoạch ngày 23/11/2026. Pilot `cm4-map-loop-fix-ag-20261122-203215184` dùng 40 lượt `return_to_candidates`, nạp 129.631 input token cho các lượt đó. Đây là chi phí đo được của luồng cũ. Tiết kiệm thực tế cần đo sau khi triển khai.

- Luồng bình thường là **đọc B → ghi kết luận một lần → hiện lại trang ứng viên**. Khi host ghi thành công `select` hoặc `not_select`, payload kế tiếp tự trở về trang ứng viên của cùng lượt tìm, giữ vị trí trang và hiển thị kết luận vừa ghi trên thẻ B. Model có thể mở ứng viên khác ngay. Lượt chốt không có lựa chọn ở lại B và không cần thêm `return_to_candidates`.
- Model quyết định đọc đến đâu trước khi chốt. Khi B còn pending, giữ đường đọc tiếp hoặc rời tạm về danh sách. Đầu ra lỗi giữ nguyên B pending và ngữ cảnh cần phục hồi. Kết luận đã ghi khóa theo `(search_query_id, B)`. Nếu cùng B xuất hiện trong một lượt tìm khác, model vẫn có thể xét B cho nguồn của lượt đó.
- Kiểm cả `select`, `not_select` trực tiếp và `not_select` qua kiểm định danh. Sau mỗi kết luận hợp lệ, payload kế tiếp phải đúng trang, đúng trạng thái thẻ, và mở được B khác ngay. Kiểm riêng rời tạm khi pending, lỗi lượt chốt và resume. So với pilot trên cùng lượng ứng viên đã chốt, báo số lượt điều hướng, token và thời gian thực tế.

## 9. Đo thời gian từng phần của pipeline

Kế hoạch đo toàn bộ lượt chạy từ khởi tạo đến khi ghi kết quả. Bên trong `compile_context`, chia nhỏ phép đo để tìm nguyên nhân của các lượt dựng payload mất khoảng 98–105 giây ở T181–T182 và T214–T215. [Trace pilot](../../../cache/cm4-map-loop-fix-ag-20261122-203215184/trace.jsonl) hiện chỉ cho biết tổng thời gian của bước này.

| Phần | Các mốc cần đo |
| --- | --- |
| Khởi tạo | Mở kho nguyên văn và index, khởi tạo tokenizer, kiểm binding. |
| Dựng context ở host | Chờ khóa SQLite nếu có, đọc và dựng trạng thái từ ledger, lấy và xác minh nguyên văn, dựng map và phần còn việc, dựng catalog và schema, compact payload và đổi ref, serialize, tokenizer, các lần thử lại để payload vừa context, ghi admission. Ghi số lần và tổng thời gian đếm token mỗi lượt. |
| Gọi controller | Thời gian client gửi và chờ receipt, thời gian xử lý do provider báo, số poll và các mốc chờ worker hoặc cold start nếu có bằng chứng. |
| Thực thi action | Xác minh reply và refs, ghi quyết định ở A hoặc B, tra citation cục bộ nếu có, embedding, truy vấn từng kênh retrieval, hợp nhất/xếp hạng kết quả, reranker và ghi diagnostics. Với dịch vụ remote, đo riêng thời gian client chờ và thời gian xử lý do dịch vụ báo. |
| Hoàn tất | Ghi ledger và kết quả cuối, thời gian giữa các chặng, thời gian toàn run. Ghi riêng các lượt lỗi, thử lại, STOP, resume và request đã gửi nhưng chưa có receipt. |

- Dùng đồng hồ đơn điệu cho thời lượng và ghép mốc theo request, action hoặc call ID. Báo thời gian tổng và thời gian riêng của từng bước, số lần gọi, trung vị, p95 và các lượt chậm nhất. Khi cộng các bước, tránh tính hai lần thời gian của phép đo lồng nhau như tokenizer trong `compile_context`. Phần remote chưa đủ mốc để tách thời gian xếp hàng thì giữ là chưa phân rã.
- Đối chiếu lượt chậm với lượt bình thường cùng chế độ đọc A, duyệt B hoặc chốt. So trước/sau theo cùng phạm vi byte A đã xét hoặc cùng số B đã chốt, kèm số lượt, token và thời gian cả run. Đo chi phí bật phép đo bằng một replay cùng đầu vào. Sau khi thấy khâu nào tốn thời gian, tối ưu khâu đó và chạy lại phép đo.
