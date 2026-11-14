# Thảo luận tối ưu vòng truy hồi

Ngày tạo: 13/11/2026. Căn cứ code tại commit `c0ab182`.

Trạng thái ngày 14/11/2026: người dùng đã cho phép triển khai theo từng mốc, nghiệm thu kết quả rồi mới sang mốc tiếp. RT1 và RT2 đã nghiệm thu engineering; RT3 đang triển khai, chưa chứng minh cải thiện recall. Các mô tả “chưa triển khai” ở mục 8 là checkpoint lúc chốt yêu cầu; trạng thái thực thi lấy tại mục 10 và báo cáo từng mốc.

## 1. Phân công và phạm vi

- Máy còn lại tối ưu phần chọn đúng án khi vòng truy hồi đã đưa đủ gold vào candidate pool.
- Máy này phân tích và đề xuất tối ưu vòng truy hồi: mô hình thấy và chọn đoạn A nào, tạo query thế nào, tìm ứng viên và hình thành pool ra sao. Bao gồm chẩn đoán top K, cap embedding và đối chiếu ranks từng kênh/sau RRF trước khi quyết định thay đổi.
- Authorization mới ngày 14/11/2026: triển khai theo kế hoạch, chia mốc nghiệm thu; dừng ở gate mỗi mốc trước khi mở mốc sau. Giai đoạn chỉ viết tài liệu đã kết thúc. Inference/deploy vẫn do người dùng hoặc AG chạy.
- Phân công Modal giữ nguyên: Codex chuẩn bị code/lệnh khi được giao; người dùng hoặc AG thực thi inference/deploy.

Đầu ra cần cải thiện là pool unique case IDs cùng passage leads và provenance. Chưa thay assessment, selector, cutoff hoặc fallback của máy kia.

## 2. Nhận định chính

Ưu tiên kiểm tra khả năng nhìn và chọn đoạn A trước, rồi mới tối ưu câu tìm và xếp hạng. Đây là thứ tự đề xuất, chưa phải kết luận nguyên nhân lỗi.

Hiện chưa đủ evidence để quy gold bị hụt cho mô hình hoặc bộ truy hồi. Chọn đúng đoạn cũng chưa bảo đảm tìm đúng án: query có thể quá chung, tín hiệu nguồn có thể bị mất, hoặc gold đã được kênh tìm thấy nhưng bị cắt trước khi vào pool.

## 3. Điểm yếu đã thấy trong code

| Điểm yếu hoặc giới hạn | Ảnh hưởng có thể xảy ra | Hướng đề xuất |
|---|---|---|
| Khi toàn văn không vừa, khởi đầu ưu tiên anchor ở trang map đầu hoặc đoạn đầu vừa ngân sách | Mô hình có thể tìm từ phần mở đầu, chưa thấy vấn đề pháp lý quan trọng phía sau | Cho mô hình khảo sát bản đồ toàn A, chọn vài vùng có nhu cầu tìm nguồn rồi mở raw |
| Chỉ cấp handle tìm theo issue cho paragraph nằm nguyên trong một excerpt hiện tại | Đoạn dài bị phân trang có nguy cơ không trở thành lựa chọn | Xem xét chọn vùng con đủ ý, có provenance, và mở thêm ngữ cảnh khi cần |
| Kiểm handle/hash/offset không kiểm được ý nghĩa của câu tìm | Chọn đúng đoạn nhưng query vẫn có thể quá chung hoặc lệch ý | Tách rõ mệnh đề cần tìm nguồn trước khi diễn đạt query |
| Pilot chỉ lấy top 3 án mỗi lượt và cho tối đa 2 request embedding | Gold có thể có trong kênh hoặc RRF nhưng bị cắt trước pool; số lượt tìm ít có thể chưa phủ nhu cầu nguồn | Đối chiếu ranks từng kênh và sau RRF trước khi đổi prompt hoặc tăng K |
| Observation M6 chỉ giữ thông tin kênh hỗ trợ các hits đã giao | Ledger M6 riêng lẻ có thể không giải thích được gold rơi ở kênh hay ở điểm cắt | Khi được triển khai, lưu raw kết quả từng kênh ngoài payload model để chẩn đoán |

### Căn cứ code

- `pipeline_v2/m4.py`: `M3Tools.query_start()` mở trang map đầu, chọn anchor hoặc paragraph đầu làm phần đọc ưu tiên khi dùng fallback.
- `pipeline_v2/m6.py`: `_seed_query_paragraph()` chọn paragraph nguyên vẹn vừa byte budget; `_visible_paragraphs()` chỉ cấp lựa chọn paragraph nằm trọn trong một excerpt.
- `pipeline_v2/agent_harness/adaptive_policy.py`: `translate()` kiểm paragraph ref, raw nguồn, hash và span. Các kiểm này không chứng minh query liên quan đúng về ngữ nghĩa.
- `pipeline_v2/reviews/m6_discovery_pilot/manifest.json`: `search_limit=3`, `embedding_budget.max_requests=2`, `byte_budget=1024`, `map_limit=2`.
- `pipeline_v2/full_search/hybrid.py`: giữ tối đa 100 unique cases mỗi kênh, dense scan tối đa 4.096 passages, RRF xuất tối đa 20 án.
- `pipeline_v2/m6_hybrid.py`: `observation()` chuyển các hits được giao sang M6, không giữ toàn bộ danh sách từng kênh trong observation.

Giới hạn top 3 và hai embedding là cấu hình pilot, không phải giới hạn bắt buộc của hệ thống. Dense exact trên tập passage trả về cũng không bảo đảm đã phủ top 100 unique cases toàn corpus khi scan cap bị chạm.

### Kiểm kê độ dài paragraph trên dữ liệu local

Đọc navigation tại `pipeline_v2/artifacts/m2_navigation_20261106_v3/sources/` ngày 13/11/2026, không đọc nhãn gold và không gọi model:

| Query | Tổng paragraph | Paragraph dài hơn 1.024 byte | Paragraph dài nhất |
|---|---:|---:|---:|
| `017984.txt` | 20 | 2 | 1.415 byte |
| `090579.txt` | 35 | 1 | 1.060 byte |
| `021095.txt` | 101 | 8 | 2.518 byte |

Đây là inventory của navigation, không phải nghiệm thu lại toàn bộ snapshot hoặc phép đo payload thực tế. Các đoạn dài chưa chắc bị ẩn: nếu toàn văn A vừa token budget, chúng có thể vẫn được giao nguyên vẹn. Cần kiểm payload thực tế với tokenizer đã pin trước khi kết luận mức ảnh hưởng.

Tại thời điểm phân tích, checkout local chưa có các thư mục run live pilot, query embedding runtime hoặc tokenizer controller dùng trên máy kia. Vì vậy chưa thể chấm lại recall hiện hành hoặc xác nhận toàn bộ đường đọc thực tế từ evidence local.

## 4. Đề xuất chọn đoạn theo nhu cầu truy nguồn

Trạng thái cập nhật ngày 14/11/2026: người dùng yêu cầu để sau phần bổ sung hướng dẫn ba nhóm đầu mối vào prompt. Giữ prompt hiện hành trong đợt sửa sắp tới; nội dung bên dưới là giả thuyết để thảo luận sau, không phải yêu cầu triển khai hoặc điều kiện nghiệm thu. Quyết định này không hoãn các hướng đã thống nhất tại mục 8.

Không chỉ hỏi đoạn nào quan trọng hoặc đoạn nào tóm tắt án. Cần hỏi: **đoạn nào chứa mệnh đề mà hệ thống cần tìm nguồn?**

Các nhóm đầu mối đề xuất:

1. Đoạn có tên án hoặc citation: tìm dấu hiệu nguồn cụ thể.
2. Đoạn phát biểu quy tắc, tiêu chuẩn hoặc phép thử: tìm án làm căn cứ cho mệnh đề đó.
3. Đoạn áp dụng, phân biệt hoặc bác bỏ tiền lệ: tìm nguồn cho quan hệ đang được bàn.

Không loại cứng đoạn trích dẫn, role `quoted` hoặc `unknown`, hay lời đương sự. Chúng vẫn có thể chứa đầu mối hữu ích. Cần giữ attribution để tránh tạo query theo một quan điểm mà tòa không sử dụng.

Luồng đề xuất để thảo luận:

1. Khảo sát bản đồ đủ rộng của A, có theo dõi vùng đã thấy và chưa thấy.
2. Chọn một số vùng có nhu cầu truy nguồn khác nhau.
3. Mở raw và đủ ngữ cảnh để hiểu mệnh đề, chủ thể phát biểu và quotation khi liên quan.
4. Chỉ rõ mệnh đề cần tìm nguồn rồi mới tạo query.

Với mỗi lựa chọn, cần giữ handle, source hash, UTF-8 byte span, raw text hash và lý do chọn. Lý do do model sinh là giả thuyết, không phải gold.

Chưa chốt số vùng, cách ưu tiên, ngân sách đọc hay cách xử lý paragraph dài. Không mặc định phải đọc toàn bộ A qua model nếu một policy navigation có thể đạt độ phủ tương đương với chi phí thấp hơn.

## 5. Hướng dẫn tạo query bám mệnh đề pháp lý

Thống nhất ngày 14/11/2026: bỏ đề xuất nhánh riêng “có citation hoặc tên nguồn rõ” khỏi mục này; đưa phần hướng dẫn tạo query còn lại vào kế hoạch. Chưa sửa prompt thực thi hoặc code. Việc bỏ đề xuất không đồng nghĩa xóa tool citation hiện có.

Phần bổ sung vào prompt/mô tả tool tìm theo issue: tạo query cho một mệnh đề pháp lý cụ thể, bám phần raw A được chọn:

- Giữ thuật ngữ hoặc cụm diễn đạt giúp phân biệt nguồn.
- Hạn chế chi tiết sự kiện không giúp tìm nguồn.
- Tránh query chỉ nêu chủ đề rộng, ví dụ chỉ có `standard of review`.
- Không gộp nhiều nhu cầu nguồn độc lập vào cùng một query.

Không áp dụng loại bỏ sự kiện một cách cứng nhắc: giữ tình tiết nếu nó giúp phân biệt nguồn. Đây là hướng dẫn diễn đạt query, không phải điều kiện tất định để host từ chối query dựa trên ngữ nghĩa. Không thêm lượt model riêng; mệnh đề debug và query vẫn theo JSON ở mục 8.3.

Phần đã có cần giữ: host/ledger lưu query thực sự gửi, query hash và ref/span/hash của đoạn A làm căn cứ. Không yêu cầu model tạo hash hoặc offsets; không coi binding hiện có là tính năng cần xây mới.

Không mặc định query ngắn hơn tốt hơn, hoặc paraphrase luôn tốt hơn nguyên văn. Có thể so query dùng cụm nguyên văn với query diễn đạt nhu cầu pháp lý trên cùng đoạn A, trong một thí nghiệm riêng.

BM25 và dense hiện nhận cùng text query. Chỉ cân nhắc query view riêng cho từng kênh sau khi có evidence rằng query chung làm yếu một kênh.

Việc so query nguyên văn với paraphrase và query view riêng là thí nghiệm có điều kiện về sau, chưa chốt thay đổi retriever. Bổ sung hướng dẫn tạo query ở mục này độc lập với đề xuất ba nhóm đầu mối chọn đoạn ở mục 4 đang được để sau.

## 6. Thứ tự kiểm chứng đề xuất

| Bước | Thay đổi hoặc đo gì? | Giữ cố định gì? |
|---|---|---|
| 1. Xác định điểm rơi gold và kiểm đầu vào model | Ngoài danh sách kênh đã quan sát, ngoài top RRF hay ngoài top K được giao; vùng A/raw/ref nào model đã nhận | Raw kết quả, query, source snapshot, channels và fusion hiện hành |
| 2. So cách chọn đoạn | Độ phủ A và policy chọn nhu cầu nguồn | Cách tạo query, số lượt tìm, indices, fusion và K |
| 3. So cách diễn đạt query | Cụm nguyên văn hoặc query theo mệnh đề pháp lý | Cùng đoạn A, số lượt, indices, fusion và K |
| 4. Chỉnh lịch tìm | Phủ nhu cầu nguồn mới, chống lặp, điều kiện dừng | Model/profile và tổng cap so sánh |
| 5. Xem xét K hoặc fusion | Chỉ khi evidence cho thấy gold đã có trong kênh nhưng bị cắt/xếp hạng thấp | Các biến khác trong thí nghiệm tương ứng |

Có thể tính lại top 3/5/10/20 từ cùng raw kết quả từng kênh mà không gọi embedding lại. Đây là chẩn đoán offline. Đưa thêm án vào runtime là thay đổi riêng vì có thể tăng payload, số lượt đọc và chi phí selector. Giữ cấu hình truy hồi cố định khi so các variant điều hướng/chọn đoạn/tạo query; thay K, cap embedding hoặc fusion cần thí nghiệm riêng sau khi có evidence.

Không đồng thời đổi model, chunk, embedding, cách tạo query và fusion rồi quy gain cho một thành phần. Không tăng số lượt tìm rồi gọi toàn bộ gain là cải thiện prompt.

## 7. Đánh giá và giới hạn kết luận

Tiêu chí chính: recall của candidate pool trên toàn gold discovery, theo unique `(query,candidate)`, kèm kích thước pool và chi phí.

Cần báo:

- Độ phủ bản đồ/raw A, đoạn hoặc phần đoạn được chọn, mệnh đề debug và query thực sự gửi.
- Recall từng kênh, union các kênh đã quan sát, sau RRF và pool thực giao.
- Recall theo K, union qua nhiều lượt và đóng góp mới của từng lượt tìm.
- Requests, input/output tokens, latency, lỗi và retry; usage chưa biết giữ riêng.
- Từng query và micro trên toàn bộ query đã chọn, kể cả query lỗi hoặc dừng sớm.
- Ngân sách reading downstream khi pool rộng hơn.

Gold không có trong danh sách kênh đã lưu chưa chứng minh gold thiếu khỏi index hoặc corpus. Với dense scan bị cap, cần giữ coverage và giới hạn đó trong diễn giải.

Chọn query từ discovery đã seal trước khi xem chất lượng. Có thể bắt đầu ba query pilot đã exposed, sau đó kiểm variant đã khóa trên toàn bộ mười query discovery. Không dùng holdout để chọn prompt/policy.

Freeze cấu hình, nguồn/truy vấn và kết quả trước khi evaluator đọc nhãn. Gold cấp cặp án không chỉ định paragraph đúng; review đoạn A phải có evidence riêng, không gọi nhãn suy luận từ model là passage gold.

Không gộp kết quả dùng vector passage cache với query embedding thật để so chất lượng; hai loại input có ý nghĩa khác nhau.

Chọn đúng đoạn là bước trung gian. Cần chứng minh nó giúp tìm thêm đúng án trong cap so sánh. Nếu gain chỉ đến từ tăng K, ghi rõ gain do pool rộng hơn. Chưa suy ra chất lượng chọn án hoặc F1 cuối từ retrieval recall.

## 8. Hướng sửa đã thống nhất để đưa vào kế hoạch

### 8.1. Cho phép tìm theo issue từ phần paragraph bị cắt

Yêu cầu ngày 13/11/2026: bỏ điều kiện phải có nguyên paragraph trong một raw excerpt mới được cấp handle tìm theo issue. Model vẫn được thực hiện tìm kiếm dựa trên phần paragraph bị cắt đang có trong raw payload hiện tại.

Trạng thái: chỉ ghi kế hoạch; người dùng đã yêu cầu chưa sửa code. Giới hạn nguyên paragraph ở mục 3 vẫn mô tả đúng implementantiation hiện tại cho đến khi thay đổi này được triển khai và kiểm tra.

Hành vi mong muốn:

- Một phần paragraph có raw text trong payload hiện tại cũng có thể được cấp ref để model chọn làm căn cứ cho `search_cases_by_issue`.
- Không bắt buộc đọc đủ các trang hoặc mở rộng ngữ cảnh trước khi tìm. Model có thể chọn đọc thêm khi thấy cần.
- Bỏ yêu cầu nguyên vẹn không có nghĩa bỏ byte/token budget, cho tìm từ preview bản đồ hoặc cho viện dẫn raw chỉ có ở lượt trước.
- Giữ kiểm tra đúng án A, source hash, raw ref hiện tại, UTF-8 byte offsets và hash của chính phần text được giao.
- Phân biệt span phần đang thấy với span paragraph gốc; ghi rõ phần bị cắt trong provenance để không diễn giải thành đã đọc toàn paragraph.
- Nếu nhiều phần rời của cùng paragraph hiện đồng thời, cách cấp ref phải phân biệt rõ từng phần. Không ghép qua khoảng raw chưa được giao để tạo ra một đoạn liên tục giả.

Phạm vi triển khai dự kiến:

- Cách tạo các lựa chọn trong `AdaptiveHarness._visible_paragraphs()`.
- Mô tả tool và metadata truyền vào source need nếu cần để biểu đạt phần bị cắt.
- Kiểm thử provenance, lựa chọn đoạn và đường ghép lại evidence A/B; cập nhật tài liệu hành vi.
- Không đổi model, embedding, chỉ mục, fusion, K hoặc selector trong thay đổi này.

Tiêu chí kiểm tra khi được giao triển khai:

1. Phần đầu, giữa hoặc cuối paragraph bị cắt vẫn có thể dùng để tìm khi raw tương ứng đang hiện.
2. Query được bind đúng span/hash của phần được chọn; không ghi thành span của toàn paragraph.
3. Trường hợp paragraph nguyên vẹn tiếp tục hoạt động.
4. Raw sai án, sai hash, ref không thuộc payload hiện tại hoặc chỉ có preview vẫn không được chấp nhận.
5. Nhiều phần rời và ký tự UTF-8 nhiều byte giữ ref/offset chính xác; đường đọc lại evidence không tự mở rộng căn cứ thành toàn paragraph.

Cho phép tìm từ phần bị cắt chỉ gỡ giới hạn về cấp tool. Nó không bảo đảm phần text đủ ngữ cảnh pháp lý, query bám đúng ý hoặc recall sẽ tăng; các điểm đó vẫn cần đánh giá riêng.

### 8.2. Bản đồ cấu trúc phân cấp, mở rộng theo lựa chọn của model

Thống nhất ngày 13/11/2026: bản đồ A có nhiều cấp; model có thể mở rộng từng vùng để xem chi tiết hơn khi muốn. Chỉ cập nhật kế hoạch, chưa triển khai code.

Mục tiêu là cho model điều hướng trên toàn A mà không phải đưa preview của mọi paragraph vào một payload. Không cố định số cấp cho mọi án: án dài hơn có thể cần cây sâu hơn, nhưng từng trang bản đồ phải vừa ngân sách token.

#### Nội dung bản đồ và giới hạn ngữ nghĩa

Đây là bản đồ cấu trúc, chưa phải bản đồ vấn đề pháp lý do xử lý ngữ nghĩa trước. Mỗi nút gồm:

- Ref để mở rộng hoặc đọc vùng.
- Vị trí trong A, phạm vi paragraph hoặc phần paragraph và độ dài.
- Heading nguyên văn nếu có.
- Một số snippets nguyên văn ngắn kèm source spans/hashes.

Không tự đặt nhãn như “phân tích tiền lệ” hoặc khẳng định “chuyển chủ thể phát biểu” khi chưa có evidence tương ứng. Có thể dùng nhãn trung tính như “Vùng 3 — đoạn 80–125”. Không giả định đã trích xuất đầy đủ citation/tên án nếu chưa chốt phương pháp; thiếu regex match không có nghĩa không có đầu mối nguồn.

Snippets phân bố ở đầu/giữa/cuối vùng là phương án khởi đầu để thử, chưa phải quyết định đã hiệu chỉnh hoặc bảo đảm đại diện nội dung. Không thêm tóm tắt bằng model trong phạm vi thiết kế này nếu chưa có quyết định riêng về ngữ nghĩa, chi phí và provenance.

#### Cấu trúc cây và hai lựa chọn điều hướng

Cấp đầu gồm các vùng liên tiếp phủ toàn A. Ưu tiên ranh giới cấu trúc thật khi có và phù hợp; vùng quá lớn được chia tiếp theo thứ tự nguồn, ưu tiên giữ paragraph. Không lấy 1–2 câu của mọi paragraph rồi nối thành một danh sách không giới hạn.

Model có hai lựa chọn riêng:

| Lựa chọn | Kết quả |
|---|---|
| Mở rộng vùng | Nhận bản đồ các vùng con, chi tiết hơn |
| Đọc vùng | Nhận raw theo ngân sách, có continuation nếu chưa giao hết |

Không bắt buộc đi xuống cấp cuối mới được đọc raw. Model có thể mở raw ngay ở bất kỳ cấp nào, đọc tiếp, quay lên cấp cha hoặc chuyển sang vùng khác. Ref là mã do host cấp, bind với án, hash nguồn và phạm vi thật; model không tự đoán byte offsets.

Ví dụ đường đi, không phải thứ tự bắt buộc:

```text
Bản đồ toàn A
├─ Vùng 1
├─ Vùng 2 → mở rộng
│  ├─ Vùng 2.1
│  ├─ Vùng 2.2 → đọc raw → tìm nguồn / đọc thêm / quay lại
│  └─ Vùng 2.3
├─ Vùng 3
└─ Vùng 4
```

Paragraph quá dài có thể chia thành các phần liên tiếp, giữ UTF-8 offsets và đánh dấu bị cắt. Việc dùng phần raw đó để tìm tuân theo hướng sửa ở mục 8.1, không yêu cầu mở đủ paragraph trước.

#### Ngân sách và trạng thái khảo sát

- Khóa trần token cho từng trang bản đồ, tính cả snippets và overhead của payload/tool. Số nút con và số cấp cụ thể chưa chốt.
- Khi cần nhiều nút hơn khả năng hiển thị, thêm nhóm cha hoặc cấp chi tiết thay vì nối danh sách vượt trần. Vẫn phải giữ đường đi đến mọi phần của A.
- Khi mở bản đồ con, thay phần chi tiết không còn cần trong payload; giữ đường dẫn hiện tại và trạng thái khảo sát ngắn gọn thay vì tích lũy mọi bản đồ đã mở.
- Phân biệt vùng đã thấy preview, đã mở bản đồ con, đã đọc raw một phần/toàn vùng và đã dùng để tạo query.
- Hiển thị vùng chưa khảo sát; xem tổng quan không được tính thành đã đọc hoặc hiểu toàn A.
- Không bắt buộc khảo sát toàn bộ các cấp trước lượt tìm đầu tiên. Model được chọn mở rộng hoặc đọc thêm theo nhu cầu và ngân sách.

#### Quan hệ với raw và vòng tìm

Bản đồ/snippets chỉ phục vụ điều hướng. Query phải bind với phần raw thực sự có trong payload hiện tại; không bind cả vùng lớn chỉ vì model đã xem preview của vùng đó. Đọc raw xong, model có thể tạo query, đọc thêm ngữ cảnh hoặc bỏ vùng để chuyển chỗ khác; chưa thêm bước xác nhận bằng một lượt model riêng.

Với A ngắn vừa ngân sách, tiếp tục cho phép giao toàn văn trực tiếp. Không bắt buộc mọi án qua bước bản đồ trước. Bản đồ phân cấp chủ yếu phục vụ A dài và điều hướng trở lại khi cần.

#### Tiêu chí kiểm tra khi được giao triển khai

1. Cây phủ toàn A; không làm mất phần giữa/cuối nguồn, kể cả án rất dài, không có heading hoặc có paragraph dài.
2. Mỗi payload bản đồ tuân thủ token cap; số nút hoặc độ dài nguồn tăng không làm một trang phình không giới hạn.
3. Ref cha/con/raw round-trip đúng nguồn, hashes và UTF-8 spans; không tạo nhãn nội dung ngữ nghĩa chưa được xác minh.
4. Model có thể mở rộng, đọc trực tiếp từ các cấp, quay lên/chuyển vùng và đọc continuation; trạng thái preview/raw/coverage được phân biệt.
5. Preview không tự trở thành raw evidence cho tìm kiếm hoặc assessment; phần bị cắt giữ đúng provenance theo mục 8.1.
6. Sau kiểm kỹ thuật, đo chất lượng chọn vùng và retrieval recall trên discovery trong cùng cap; ghi chi phí navigation/đọc lại. Phân cấp giúp kiểm soát độ dài và điều hướng, chưa tự chứng minh recall tăng.

### 8.3. Mệnh đề debug trong JSON và tăng output cap

Thống nhất ngày 13/11/2026: thêm mệnh đề cần tìm nguồn vào JSON có schema xác định, chỉ để debug; tăng trần output từ 384 lên **512 token mỗi lượt controller** cho profile thử nghiệm mới. Đây là quyết định trong kế hoạch, chưa sửa code hoặc cấu hình chạy.

Action tìm theo issue dự kiến:

```json
{
  "action": "search_cases_by_issue",
  "args": {
    "a_paragraph_ref": "ref-cua-phan-raw-A-dang-hien",
    "source_proposition": "Mệnh đề ngắn mà model muốn tìm nguồn làm căn cứ.",
    "issue": "query thực sự dùng để truy hồi"
  }
}
```

- Giữ tên `issue` của giao diện hiện tại; trường này tiếp tục là query, qua kiểm tra/chuẩn hóa hiện hành rồi gửi tới các kênh truy hồi. Không ghép `source_proposition` vào query, không dùng nó làm tín hiệu xếp hạng hoặc chọn án.
- `source_proposition` là trường bắt buộc của action này, giới hạn ở một câu ngắn; lưu vào ledger/debug cùng ref và query để phân tích lỗi hiểu đoạn hoặc tạo query. Giới hạn ký tự cụ thể chưa chốt.
- Sinh mệnh đề và query trong cùng một phản hồi; không thêm lượt model riêng. Schema kiểm cấu trúc, không xác nhận đúng ngữ nghĩa.
- Cap 512 là trần cho toàn phản hồi JSON mỗi lượt, không phải riêng trường query hoặc mệnh đề. Các action khác không bị yêu cầu thêm trường mệnh đề.
- Với profile pilot đang có `max_payload_tokens=7400`, tổng cap mỗi lượt mới là `7400 + 512 = 7912`, nằm dưới context window deployment hiện tại là 8192. Khi triển khai phải kiểm tổng input thực tế, gồm prompt/schema/tool overhead, tại biên transport thay vì chỉ dựa vào phép cộng cấu hình.
- Nếu giữ 8 request và tổng input cap 60000, cập nhật tổng ngân sách cho profile mới thành `max_total_tokens=64096` (`60000 + 8 × 512`), thay cho 63072. Đây là trần, không phải dự báo usage thực tế. Giữ nguyên cap request, retry và embedding nếu không có quyết định khác.
- Khi được triển khai, tạo version/profile/run namespace mới, không sửa manifest hoặc receipts lịch sử để áp ngân sách mới. Ghi nhận đây là tăng cap khi so sánh kết quả, không quy toàn bộ thay đổi cho trường debug.

Kiểm tra cần thực hiện: structured output và validator nhận đúng trường; query không bị ghép hoặc thay bằng mệnh đề; ledger giữ đúng dữ liệu debug; context và tổng token budgets được áp dụng; ghi output usage và trường hợp `finish_reason=length`. Chưa coi cap 512 là bảo đảm đủ cho mọi phản hồi.

### 8.4. Tăng embedding cap lên 5 request mỗi run

Yêu cầu ngày 13/11/2026: tăng `embedding_budget.max_requests` từ 2 lên **5** cho mỗi run của một query case A trong profile thử nghiệm mới. Chỉ ghi kế hoạch, chưa sửa cấu hình chạy hoặc code.

- Đây là tối đa 5 request tạo query embedding để tìm hybrid, không phải embed lại corpus hoặc giới hạn 5 án kết quả. Không bắt buộc phải dùng đủ 5 request.
- Dự kiến tăng `embedding_budget.max_input_tokens` từ 896 lên **2240**, theo cùng tỉ lệ ngân sách cũ (`896 × 5 / 2`), để cap token không vô tình giữ mức dự trù của hai request. Đây là tổng input token embedding cho cả run, gồm instruction/special tokens theo tokenizer đã pin; vẫn áp giới hạn từng input của profile embedding hiện hành. Đủ request cap không bảo đảm đủ token cap cho mọi bộ query.
- Ngân sách embedding tách khỏi ngân sách controller. Không cộng 2240 vào `budget.max_total_tokens` của controller; báo và kiểm riêng usage của cả hai thành phần.
- Chưa tự tăng `budget.max_requests=8` hoặc `max_actions=8` của controller. Nếu dùng 5 lượt tìm sẽ còn ít lượt cho navigation/đọc/assessment; cần kiểm khả năng thực hiện luồng trong tổng cap trước khi chốt profile hoàn chỉnh. Năm embedding là trần cho phép, không phải cam kết hệ thống luôn thực hiện được năm lượt tìm.
- Tạo profile/run namespace mới khi triển khai, giữ manifest pilot cũ nguyên trạng. So sánh phải ghi rõ tăng ngân sách embedding, không quy gain recall chỉ cho bản đồ hoặc cách tạo query.

Kiểm tra khi triển khai: request thứ năm được phép nếu còn các ngân sách khác; request thứ sáu bị chặn; token cap vẫn áp dụng; lỗi/unknown receipt và retry không làm reset cap hoặc mất usage lịch sử.

### 8.5. Lưu đầy đủ kết quả từng kênh ngoài payload model

Yêu cầu ngày 14/11/2026: lưu raw kết quả từng kênh khi thực hiện tìm hybrid để chẩn đoán gold bị hụt ở kênh, RRF hay điểm cắt đưa vào pool. Chỉ cập nhật kế hoạch, chưa triển khai code.

Hiện `m6_hybrid.observation()` chỉ giữ các hits đã giao và thông tin các kênh hỗ trợ những hits đó. Ledger M6 riêng lẻ vì vậy không đủ tái dựng thứ hạng của ứng viên ngoài top K đã giao.

Hành vi dự kiến:

- Lưu nguyên raw M3 hybrid response trước bước rút gọn thành observation M6: các danh sách `case_bm25`, `passage_bm25`, `dense_passage`, ranks/scores và passage leads, fused hits, coverage, timings và query-vector provenance đã trả về.
- “Đầy đủ” là toàn bộ kết quả mà runtime đã trả theo cap của từng kênh, không phải toàn corpus hoặc mọi dense point đã quét. Không khẳng định gold thiếu khỏi index chỉ vì không có trong các danh sách đã lưu.
- Lưu bên ngoài payload model, trong artifact riêng write-once của run; ledger giữ đường dẫn/hash và liên kết tới run, action, M3 request, query text/hash, đoạn hoặc phần raw A làm căn cứ, mệnh đề debug nếu có và snapshot/profile/implementation bindings.
- Không đưa danh sách dài từng kênh vào prompt, không tự thêm những án chỉ có trong diagnostic vào candidate pool hoặc làm thay đổi thứ tự kết quả. Lưu telemetry không gọi thêm embedding/model và không thực hiện lại retrieval.
- Khi không thể lưu/ghi liên kết, phải ghi rõ diagnostic thiếu hoặc lỗi, không báo đã có evidence đầy đủ. Lưu usage, lỗi và unknown receipt hiện hành; nếu không có raw response do lượt tìm thất bại thì không tạo kết quả giả. Các kết quả kênh có trước lỗi, nếu có thể lưu, phải đánh dấu partial và thiếu kênh nào.
- Giữ nguyên lịch sử, không ghi đè response/seal/receipt cũ; dùng namespace mới khi triển khai.

Chẩn đoán offline dự kiến sau khi freeze run và đưa gold vào evaluator riêng:

1. Gold có trong danh sách từng kênh đã lưu không, tại rank nào?
2. Gold có trong union các kênh nhưng rơi ngoài top fused đã chọn không?
3. Gold có trong RRF ở K rộng hơn nhưng bị cắt khỏi hits giao cho M6 không?
4. Hits đã giao có thực sự được ghi vào candidate pool không? Phân biệt rõ bước trả kết quả tìm với bước cập nhật pool.

Nếu raw response chỉ lưu fused hits theo K đã yêu cầu, có thể tính lại RRF ở K khác từ các danh sách kênh đã lưu và policy đã khóa. Kết quả tính lại phải được ghi là chẩn đoán offline, không phải các hits thực tế model đã nhận. Không suy rộng vượt cap của các danh sách đầu vào.

Tiêu chí kiểm tra khi được giao triển khai:

- Lần ngược được action/query/đoạn A → raw response → từng kênh → RRF → hits giao → pool; refs/hashes khớp và phát hiện artifact thiếu hoặc bị thay đổi.
- Dùng fixture có ứng viên nằm ngoài top K giao, bị loại bởi fusion, hoặc không có trong kênh quan sát được để kiểm các kết luận khác nhau; chấm unique case IDs, không đếm passage lặp thành nhiều án.
- Bật ghi diagnostic không làm đổi payload model, kết quả retrieval, pool, admission/resume hoặc số request inference; chi phí lưu local được báo riêng nếu có ý nghĩa.
- Lỗi, response partial và unknown giữ nguyên trạng thái; không bỏ query lỗi khỏi mẫu đánh giá hoặc coi missing evidence là kết quả rỗng thành công.

### 8.6. Bổ sung hướng dẫn tạo query theo mục 5

Yêu cầu ngày 14/11/2026: đưa hướng dẫn giữ thuật ngữ phân biệt, hạn chế sự kiện không hữu ích, tránh query quá chung và không gộp nhiều nhu cầu nguồn vào một query vào đợt sửa dự kiến. Áp dụng cho prompt/mô tả `search_cases_by_issue`, chưa triển khai. Giữ nguyên binding query/hash/đoạn A đã có; không thêm nhánh literal/identity mới theo đề xuất đã bỏ khỏi mục 5.

Khi được triển khai, kiểm prompt/schema/token budgets và việc `issue` vẫn là query thực sự gửi; không ghép mệnh đề debug vào query. So chất lượng query và retrieval trên discovery trong profile kiểm soát; hướng dẫn mới chưa tự chứng minh recall tốt hơn. Ba nhóm đầu mối chọn đoạn ở mục 4 vẫn để sau.

### 8.7. Nâng input cap lên 10.000 token

Checkpoint sau khi AG chạy profile 8.500: deploy v2 báo thành công nhưng canary một request timeout/unknown, cancel_requested; chưa có actual provider usage hoặc nghiệm thu live. Không tự resend hoặc mở RT4. Chẩn đoán call cũ và bàn giao theo `docs/RETRIEVAL_HANDOFF_20261114.md`; canary hiện dùng finite wait 1.080 giây cần được review cùng remote logs, không kết luận context/OOM chỉ từ timeout.

**Cập nhật mới nhất ngày 14/11/2026:** người dùng giảm input cap còn **8.500 token**. Dùng profile `reviews/m6_retrieval_rt3_ctx8500_v1/settings.json` thay profile 10.000; giữ context engine 12.288, map allocation 2.400, 8 requests/actions và output 384 hiện hành. Tổng input cap 68.000, total 71.072; khi output 512 ở RT4 thì total 72.096. Profile/canary/báo cáo 10.000 bên dưới là lịch sử, không dùng để chạy profile mới. AG dùng hướng dẫn tại `reviews/m6_retrieval_rt3_ctx8500_v1/AG_CHECK.md`; chưa deploy hoặc inference bởi Codex.

Yêu cầu bổ sung ngày 14/11/2026: tăng total input payload mỗi lượt từ 7.400 lên **10.000 token**, gồm instructions/chat template/tool overhead do counter thực đếm. Deployment source tăng context từ 8.192 lên **12.288 token** để chứa input mới cùng output tối đa 512. Đây là thay đổi context/budget, không đổi model/revision/chunk/indices/selector.

Tạo profile mới `reviews/m6_retrieval_rt3_ctx10000_v1/settings.json`, giữ 8 requests/actions, output 384 cho RT3; tổng input cap 80.000, total 83.072. Khi output 512 ở RT4 thì total 84.096 nếu vẫn giữ 8 lượt. Embedding cap là ngân sách riêng. Allocation bản đồ 2.400 giữ nguyên trong cap input rộng hơn.

Không sửa lại các run và receipts 7.400 đã khóa. Các tham chiếu cap 7.400 trong checkpoint RT3 ở dưới mô tả evidence trước yêu cầu này. Cần namespace mới khi context/profile/source binding đổi. Local prepare không chứng minh deployment thật đã đổi.

Codex chuẩn bị source và kiểm local; người dùng/AG deploy theo phân công và chạy một canary gần 10.000 input token để nghiệm thu context/VRAM/runtime. App hiện hành có thể đang được máy kia dùng nên phải phối hợp thời điểm deploy và giữ call chưa rõ. Không tự đổi function pin/model/GPU hoặc gọi inference ở Codex. Hướng dẫn tại `reviews/m6_retrieval_rt3_ctx10000_v1/AG_CHECK.md`; chưa mở RT4 trước gate RT3/context.

## 9. Các quyết định đang mở

- Cần xem raw run hiện hành nào để xác định miss thực tế và điểm rơi gold?
- Bản đồ phân cấp đã thống nhất; còn chốt cách nhóm vùng, trần token, số nút mỗi trang, chọn snippets và trạng thái coverage theo mục 8.2.
- Đã thống nhất cho tìm từ phần paragraph bị cắt; còn cần chốt cách đặt ref, biểu diễn độ phủ và mô tả ngữ cảnh thiếu cho model.
- Đã chốt JSON có `source_proposition` chỉ để debug và `issue` làm query theo mục 8.3; còn chốt giới hạn độ dài mệnh đề, chưa thêm trường lý do chọn riêng.
- Sau khi có evidence, có cần thí nghiệm query nguyên văn so với paraphrase hoặc query view riêng cho từng kênh không?
- Để sau: thử bổ sung ví dụ đầu mối citation, quy tắc/phép thử, áp dụng/phân biệt/bác bỏ tiền lệ vào prompt. Chưa có evidence cải thiện so với prompt hiện hành; không buộc model phân loại hoặc phủ đủ ba nhóm.
- Giữ bao nhiêu lượt tìm, K và ngân sách navigation/đọc/tạo query để so công bằng?
- Pool và provenance bàn giao cho phần chọn án của máy kia cần giữ những trường nào?

Các mục trên là điểm để tiếp tục hỏi và chỉnh sửa; chưa phải quyết định triển khai.

## 10. Các mốc triển khai và gate nghiệm thu

Người dùng yêu cầu ngày 14/11/2026: thực hiện sửa theo kế hoạch, chia mốc để xem kết quả rồi mới triển khai tiếp; chuẩn bị phần cần AG kiểm. Không gom mọi thay đổi vào một run rồi quy gain cho một thành phần.

| Mốc | Phạm vi | Evidence và tiêu chí qua gate | Trạng thái |
|---|---|---|---|
| RT1 — Quan sát kết quả truy hồi | Mục 8.5: lưu full response từng kênh ngoài payload, liên kết operation/action/request bằng hash/ref, đọc kiểm lại artifact | Fixture/integration không inference; kết quả/payload/call count không đổi; lưu lỗi rõ; integrity và resume không replay; AG review và kiểm cached hybrid trên corpus khi runtime local sẵn sàng | Nghiệm thu engineering cached corpus; receipt `reviews/m6_retrieval_rt1_v1/main_acceptance.json` |
| RT2 — Tìm từ raw A bị cắt | Mục 8.1; giữ span/hash phần thật đã giao, không yêu cầu nguyên paragraph | Test UTF-8, nhiều phần rời, stale/foreign refs, ghép lại evidence; kiểm nguồn thật đoạn dài; AG kiểm kết quả sau triển khai | Nghiệm thu engineering scripted corpus; receipt `reviews/m6_retrieval_rt2_v1/main_acceptance.json` |
| RT3 — Bản đồ phân cấp | Mục 8.2: cây cấu trúc, ref mở rộng/đọc, cap token, coverage; giữ đường toàn văn cho A ngắn | Phủ toàn nguồn, ref round-trip, payload bounded trên án dài/cực dài; test điều hướng; AG xem payload thực với tokenizer pin và đọc vùng đầu/giữa/cuối | Local PASS: 73 tests (1 skip), 159 trang corpus và scripted navigation; chờ AG final gate tại `reviews/m6_retrieval_rt3_v1/` |
| RT4 — JSON debug và hướng dẫn query | Mục 8.3 và 8.6: source_proposition do model diễn đạt chỉ để debug, issue giữ query; output 512 và tổng ngân sách tương ứng | Test schema/ledger/query không bị ghép, context accounting; AG canary structured output live theo cap và raw A thật; xem query/mệnh đề, usage và lỗi | Chưa triển khai |
| RT5 — Profile 5 embedding và pilot discovery | Mục 8.4: profile mới 5 request/2240 embedding input token; controller cap phải được kiểm feasibility; dùng diagnostic RT1 để chấm | Test cap request/token và recovery; AG chạy profile đã freeze, báo đầy đủ lỗi/usage, recall và ranks theo query; tách ảnh hưởng tăng ngân sách khỏi thay prompt/navigation | Chưa triển khai |

### Quy tắc nghiệm thu

- Main đọc implementation và evidence, implementer sửa production trong scope, tester_advanced kiểm độc lập logic/provenance/state trước khi bàn giao AG.
- Test fixture/scripted transport chứng minh engineering contract trong phạm vi đó; không thay kết quả controller thật, semantic correctness hoặc COLIEE recall.
- Khi thiếu runtime/dữ liệu cho kiểm tích hợp, ghi rõ phần chưa kiểm, không tạo receipt PASS giả và không tự vượt gate. Không chạy lại các phần đã kiểm chỉ để có thêm số test.
- RT1 không đổi prompt/tool schema/budget/K/fusion/model/chunk/selector. Các mốc sau dùng namespace mới khi binding đổi, không sửa manifest hoặc báo cáo lịch sử.
- AG không được giao tự viết lại production. Chuẩn bị lệnh kiểm, đầu vào, kết quả cần trả và điểm dừng; không gửi sang chat/app khác nếu chưa có chỉ định.
- Hướng dẫn ba nhóm đầu mối ở mục 4 vẫn để sau. Không bổ sung nhánh literal/identity mới đã bỏ khỏi mục 5.

### RT1 — Phạm vi kiểm và giới hạn đã xác định

- Nối artifact với `action_id` trong journal; dùng action ledger M6 hiện có để truy về query và `_m6_need` (đoạn A/provenance). Không cần đưa source need vào schema model hoặc sửa selector.
- Chụp full response thành công tại biên `HybridSearch.search()` trước observation rút gọn. “Full” chỉ là mọi danh sách mà M3 thực sự trả theo cap hiện hành, không phải toàn universe.
- Lỗi trước khi M3 trả response được ghi diagnostic không có dữ liệu; RT1 chưa sửa adapter M3 đã khóa để lấy lexical partial trước lỗi dense. Không gọi missing response là kết quả rỗng hoặc partial thành công.
- Lưu diagnostic lỗi phải phân biệt với search/provider lỗi, giữ kết quả tìm hợp lệ và usage. Artifact tồn tại nhưng thiếu liên kết ledger phải được nhận diện là evidence chưa đủ; không tự resend operation.
- CLI/helper kiểm đọc phải phát hiện file thiếu, hash sai, link/query/request sai và đường dẫn vượt run. Giữ write-once và trạng thái interrupted/unknown.
- Baseline trước sửa: `test_m6_hybrid` và `test_m6_live` đạt 11 tests, 0 request inference. Báo cáo mốc tại `pipeline_v2/reviews/m6_retrieval_rt1_v1/` sẽ ghi kết quả bản cuối và hướng dẫn AG.

### RT3 — Quyết định kỹ thuật cho bản triển khai thử

- Bật bằng cấu hình `query_navigation.mode=hierarchical` trong profile mới; profile không có tùy chọn này giữ đường navigation cũ. Không viết lại profile/run đã khóa.
- Thông số khởi đầu để kiểm engineering: tối đa 6 nút con/trang, leaf target 1.024 byte, map page allocation **2.400 token**, snippet target 96 ký tự. Allocation ban đầu 1.600 không đủ giữ literal snippets với spans/hashes trên fixture UTF-8 và tokenizer thật, có nguy cơ ra bản đồ không có text để chọn vùng. Main điều chỉnh allocation nội bộ lên 2.400 theo evidence, giữ total model payload cap **7.400**, output 384 và các cap request/embedding hiện hành. Không thay topology theo trạng thái chỉ để vừa cap. Đây là tham số thử chưa hiệu chỉnh chất lượng; phải kiểm final payload gồm schema/tool.
- Renderer có thể giảm từ nhiều snippet xuống một snippet literal cho mỗi vùng con và rút ngắn text để vừa allocation, nhưng không lược hết nội dung của lựa chọn vùng rồi báo PASS. Với page lá cần literal của chính vùng hiện tại. Trường hợp không vừa ngay cả nội dung tối thiểu phải báo unfit; metadata trạng thái lặp có thể dùng defaults cấp trang và deltas từng nút để gọn token.
- Page phủ cả các vùng heading/gap/đuôi raw, chia tiếp khi cần; paragraph cực dài có thể chia UTF-8-safe. Giữ heading/snippets literal với spans/hash, không thêm tóm tắt ngữ nghĩa hoặc regex citation mới.
- Có hai lựa chọn phân biệt: mở rộng bản đồ và đọc raw ở bất kỳ cấp nào. Parent/root/back, sibling và continuation phải hoạt động qua ref host cấp và resume từ ledger, không dựa bộ nhớ adapter đã mở.
- Giữ current page/breadcrumb và summary coverage có giới hạn thay vì cộng dồn toàn bộ cây vào prompt. Phân biệt map đã fetch, map đã giao cho model, raw đã giao một phần/toàn vùng và raw hiện đang được offer. Last-open chưa có lượt model nhận không được tính là đã đọc.
- Giữ whole-query delivery cho A vừa payload. Với hierarchical fallback, không tự seed paragraph đầu để thay lựa chọn điều hướng của model. Raw thực giao vẫn đi ref partial của RT2.
- Mốc này không đổi output cap, request/embedding cap hoặc selector. Test điều hướng nhiều lượt là engineering fixture có budget riêng, không tự khẳng định controller pilot 8 lượt đủ khảo sát án cực dài.
