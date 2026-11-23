# CM4 — Truy hồi theo issue và nguyên văn, hợp nhất RRF rồi rerank

Trạng thái ngày 21/11/2026. Đã tích hợp profile thử nghiệm trên nền CM4 v30 tại `dce7163` và kiểm preflight local. Chất lượng rerank và độ chính xác chốt citation cần đo bằng pilot. Cấu hình mặc định của profile thử nghiệm lấy tối đa 50 án mỗi nhánh, 50 án sau hợp nhất để lấy passage cho Qwen, và tối đa **10 hit cấp đoạn** sau rerank. Một án có thể chiếm nhiều vị trí trong 10 hit.

## 1. Hai chuỗi tìm kiếm từ cùng một nhu cầu nguồn

Sau `assess_source_need` với `search_needed`, model gọi `search_cases_by_issue` cho nhu cầu đã duyệt. Một action này khởi động cả hai nhánh ở host:

| Nhánh | Chuỗi gửi hybrid retrieval |
| --- | --- |
| **Issue** | `issue` do model viết, giữ cách truy hồi hiện hành. |
| **Nguyên văn** | Toàn bộ span A đã duyệt qua `proposition_ref`, lấy từ nguồn canonical theo byte offsets. Giữ nguyên chữ, dấu câu và ngôn ngữ nguồn. |

`source_proposition` lưu lời diễn đạt của model để truy vết. Ví dụ Q2 của `021095.txt` có issue `standard of review prothonotary discretion`. Nhánh nguyên văn dùng span `[7580, 7829)` của cùng án. Đầu span ghi rằng bên bị đơn đang dẫn tiêu chuẩn của Federal Court of Appeal cho quyết định interlocutory của prothonotaries. Hai nhánh cùng thuộc một lượt tìm và một kết luận. [Báo cáo Q2](../../../CODEX_HANDOFF.md#kết-quả-pilot-v30)

## 2. Hai tầng RRF theo án

1. **RRF trong mỗi nhánh.** Mỗi chuỗi chạy hybrid hiện có gồm case BM25, passage BM25 và dense passage. Giữ cách gộp hit theo `case_id` và RRF hiện hành. Lấy tối đa `branch_limit=50` án từ mỗi nhánh.
2. **RRF giữa hai nhánh.** Lấy hợp theo `case_id`, tối đa 100 án trước khi cắt. Xếp hạng bằng `score(B) = Σ 1 / (c + rank_branch(B))` trên hai bảng xếp hạng đầu ra của tầng một. Rank bắt đầu từ 1. Hai nhánh có trọng số bằng nhau trong thử nghiệm đầu. Án vắng mặt ở một nhánh nhận 0 từ nhánh đó. Đề xuất dùng cùng hằng số RRF với hybrid hiện tại ở vòng đầu và phá hòa theo `case_id` để replay ổn định.
3. **Cắt pool cho Qwen.** Lấy tối đa `rerank_pool_limit=50` án theo RRF tầng hai. Giữ cả hợp trước khi cắt, rank từng nhánh, lead của từng nhánh và thứ hạng hợp nhất ở host để đo mất mát tại từng bước.

Hai nhánh chạy trên cùng corpus, index và cấu hình hybrid. Hạch toán riêng hai truy vấn và embedding thực phát sinh. Nếu đầu vào retrieval trùng hệt, có thể dùng lại execution và chỉ tính danh sách đó một lần trong RRF cấp hai. Phân biệt nhánh chạy xong nhưng không có hit với nhánh lỗi hoặc còn chưa rõ kết quả. Phép đo hai nhánh hoàn chỉnh cần receipt hợp lệ của cả hai. Nếu sau này cho phép chạy tiếp với một nhánh thành công, ghi rõ trạng thái và báo riêng số đo của các lượt đó.

## 3. Qwen xếp hạng top 10 đoạn và gom theo án để đọc

- Thử `Qwen/Qwen3-Reranker-0.6B` zero-shot trên một Modal L4. Từ pool án sau RRF, lấy các passage lead đã lưu theo nhánh và kênh. Đầu vào Qwen là các cặp **span nguyên văn A × passage nguyên văn của B**. Giữ nhiều passage của cùng B nếu khác vị trí. Nếu đúng một passage được tìm thấy qua nhiều kênh hoặc nhánh, chấm một lần và lưu đủ provenance. Vòng đầu dùng các lead sẵn có, chia batch theo số cặp và độ dài. Ghi số cặp thực chấm thay vì giả định mỗi án chỉ có một cặp. Án chỉ có hit cấp án cần đường tìm passage có giới hạn trong chính B trước khi được xếp hạng cấp đoạn. Ghi riêng các án vẫn thiếu đoạn.
- Xếp các passage giảm dần theo điểm Qwen, phá hòa theo rank RRF cấp án rồi `passage_id` hoặc ref ổn định. Cắt **`review_hit_limit=10` passage** trên toàn lượt tìm. Một B có thể có các đoạn ở hạng 1 và 6, một B khác ở hạng 2 và 10. Điểm và hạng passage được lưu ngoài prompt cùng revision model, instruction, hashes, spans và latency. Cache theo đúng đầu vào chấm. Hai nhu cầu có cùng `issue` nhưng khác span A có thể cho thứ hạng khác nhau.
- **Chỉ sau khi cắt top 10 mới gom các hit cần review theo `case_id`.** Không kéo thêm passage của cùng án từ pool rerank. Host giữ điểm và hạng để chẩn đoán. Model thấy một thẻ mỗi án gồm mã án, một preview nguyên văn do host chọn, số đoạn, tiến độ đã nhận/đánh giá và trạng thái chọn. Mặc định trình bày thẻ theo `case_id` và các đoạn cùng án theo vị trí nguồn. Model mở trực tiếp thẻ đang thấy bằng `open_candidate_passages`, hoặc chuyển trang; không bắt buộc khảo sát tất cả thẻ và không có bước gán `read_next` trong nhánh này. Phiếu chọn citation theo mục 6.
- **Phần cấp cho model bỏ mọi điểm số, thứ hạng và nhãn “top 10”.** Áp dụng cho thẻ survey, gói đọc, feedback, tên lựa chọn điều hướng và tham số tool. Ref đoạn ổn định và độc lập với vị trí xếp hạng. Vẫn hiện số đoạn thực có, số đoạn chưa đánh giá, ref và nguyên văn để model biết còn việc gì. `review_hit_limit` và dữ liệu trước/sau rerank chỉ dùng ở host, ledger và báo cáo chẩn đoán.

## 4. Gói đọc B và chú thích nguồn cho controller

Khi model chọn đọc một ứng viên, host ghép trong cùng payload span A đã duyệt, đoạn định danh ngắn của B nếu có, phần giới thiệu B và passage khớp kèm câu dẫn. Chỉ các hit của B nằm trong top 10 của lượt tìm được tự gom vào gói đọc; tool đọc thêm vẫn do model chủ động chọn. Mỗi đoạn hiện **nhãn vị trí lấy nguyên văn** ngay cạnh nội dung. Host lưu `case_id`, ref, byte span và hash nguồn để mở lại đúng đoạn.

**Mở theo án và hợp các vùng chồng lấn trước khi dựng payload.** Khi model chọn `B_A`, host lấy các vùng đọc của hit thuộc `B_A` trong danh sách đã lọc. Với các vùng chồng lấn có cùng `case_id` và hash nguồn, host lấy hợp các khoảng byte trước khi đếm token và chia trang. Giao mỗi vùng hợp nhất một lần, giữ ánh xạ từ từng `hit_ref` về span gốc và giữ nguyên khoảng cách giữa các vùng rời nhau. Gửi các vùng thuộc cùng B trong một payload nếu vừa ngân sách, kèm **một** span A và **một** gói định danh/giới thiệu B. Nếu vượt cap, chia trang theo ranh giới nguồn và giữ tiến độ mỗi hit. Các tool ở mục 5 vẫn được cấp cho ứng viên đang mở khi có vùng phù hợp để đọc thêm.

Prompt nêu án B đang mở, các hit nguồn và trạng thái `pending` hoặc đã chốt. **Model quyết định độ sâu đọc và thời điểm rời án.** `conclude_candidate` chốt đúng một lần cho cả B trong lượt tìm: `select` ngay khi đủ bằng chứng; `not_select` khi model kết thúc xem xét mà không đủ căn cứ hoặc xác định B không phải nguồn. Có thể rời tạm bằng `return_to_candidates(reason)` và mở lại đúng vị trí mà không chốt. Chốt không tự đóng gói đọc; đọc tiếp hoặc mở lại sau chốt không mở khóa kết luận. Passage chưa đọc không thành phiếu phủ định.

| Phần cấp cho model | Nhãn và điều kiện cấp |
| --- | --- |
| **Đoạn định danh B** | `Lấy nguyên văn từ phần đầu án B` khi xác định được vùng. Hiện các dòng tên án, tòa, ngày, số hồ sơ hoặc citation nếu quan sát được. Trường bị che, thiếu hoặc mâu thuẫn giữ trạng thái tương ứng. Model kiểm giá trị nói về chính B hay về một án khác. |
| **Tóm tắt có sẵn** | `Lấy nguyên văn từ mục Summary của B, trước mục Topic`. Chỉ dùng nhãn này khi host xác định được heading `Summary` ở đầu án, ranh giới đoạn và nội dung thực. Bỏ các mục chỉ báo không có tóm tắt, mục rỗng hoặc phần bị che toàn bộ. |
| **Đoạn giới thiệu dự phòng** | `Lấy nguyên văn từ đoạn mở đầu của B` hoặc `Lấy nguyên văn từ mục Background của B`, theo vị trí host thực sự dùng. Chọn tối đa một hoặc hai câu hữu ích để định hướng. Nếu khó xác định phạm vi mục, ghi vị trí đoạn theo ref và để trạng thái chưa rõ đề mục. |
| **Passage và câu dẫn** | `Passage truy hồi từ B` và `Ngữ cảnh liền kề` cho phần mở rộng tương ứng. Hiện tên mục như `Analysis` khi quan sát được. Model đọc câu dẫn và ranh giới trích dẫn để kiểm ai đang nói và án nào được nhắc đến. |

Prompt phân biệt hai mức. **Host đã kiểm xuất xứ** nghĩa là đoạn khớp nguyên văn và nằm trong vùng được ghi. **Nội dung còn cần đối chiếu** áp dụng cho cả `Summary`, đoạn dự phòng và passage. Vị trí trong `Summary` xác nhận xuất xứ của đoạn, còn việc hiểu đúng vai trò người nói, định danh của B và quan hệ A viện dẫn B dựa vào bằng chứng trong lượt kết luận. Đoạn dự phòng do luật chọn để định hướng và được ghi rõ là chưa kiểm ngữ nghĩa. Nếu phần giới thiệu chưa đủ để quyết định, model có thể đọc thêm đúng vùng hoặc rời tạm giữ pending. Chỉ chốt `not_select` khi kết thúc xem xét.

## 5. Tool đọc theo mục đích sau khi mở ứng viên

Gói đọc đầu tiên ở mục 4 tự kèm định danh và câu dẫn khi lấy được trong ngân sách. Sau lượt đó, nếu còn thiếu căn cứ, model chọn một tool đọc theo mục đích và một `target_ref` từ catalog của lượt hiện tại. Mỗi lựa chọn mô tả đoạn sẽ mở để model quyết định ngay trong một action. Host xác định vùng và offsets, kiểm phạm vi ở cả schema lẫn lúc thực thi.

| Tool | Khi được cấp | Đoạn trả về |
| --- | --- | --- |
| `read_candidate_identity(target_ref)` | B đang mở có đoạn định danh hữu ích chưa được giao cho cặp đang xét. | Nguyên văn vùng có dấu hiệu tự định danh của B, như tên án, tòa, ngày, docket hoặc citation. Ưu tiên cụm thông tin đầu án. Dùng vùng khác nếu có căn cứ rằng đoạn nói về chính B. Hiện ref và trạng thái che, thiếu hoặc mâu thuẫn nếu quan sát được. |
| `read_passage_attribution(target_ref)` | Có phần nguồn chưa giao trong cửa sổ khoảng ±1.200 byte quanh vùng passage B. | Ngữ cảnh trước/sau passage để model kiểm tra người nói và nguồn trích. Host không khẳng định đã định vị đúng câu dẫn, người nói hoặc ranh giới quotation. Giữ continuation nếu phần được mở vượt ngân sách. |
| `read_query_citation_context(target_ref)` | Có vùng mới quanh span A của nhu cầu đang mở, như phần còn lại của câu dẫn hoặc khu vực quanh marker bị che. | Nguyên văn A quanh mệnh đề đang xét, ưu tiên tên án, tòa, citation còn thấy và câu dẫn. Giữ ref của vùng A riêng với ref bên B. |

**Bỏ `read_more_context` và `open_candidate_header` khỏi luồng CM4 thử nghiệm.** Chuyển các đường recovery theo mục đích sang ba tool trong bảng. Khi triển khai, cập nhật đồng bộ prompt, catalog, schema, dispatch và phản hồi sửa lỗi hoặc blocker để model chỉ được chỉ tới action đang được cấp. Tái dùng reader và kiểm provenance hiện có bên dưới. Phạm vi là luồng CM4 thử nghiệm. Các caller M4/M6 khác dùng tool contract riêng.

`continue_raw_evidence` tiếp tục phần còn lại của một đoạn host đã xác định nhưng payload chưa giao hết. Continuation giữ nguyên target, bên A/B, nguồn và vị trí tiếp theo. `open_retrieved_passage` vẫn mở lead đã chọn. `read_case_passages` vẫn tìm một đoạn khác trong chính B bằng focus. Các đường này phục vụ đọc đúng lead, đọc tiếp hoặc tìm đoạn mới trong B, còn ba tool mới mở các vùng xác minh mà host đã định vị.

Mỗi `target_ref` gắn với query đang review và nguồn tương ứng. Với đọc B, ref còn gắn với đúng ứng viên trong shortlist. Kết quả giữ nguyên văn, `case_id`, byte span, hash và nhãn xuất xứ như mục 4. `read_case_passages` kiểm tối đa 3 hit và phân biệt `new_content`, `already_read`, `no_hits` theo receipt/source spans; đoạn cũ chỉ mở lại có chủ đích bằng `revisit_case_passage`. Không khóa model trong án tới khi đọc hết nhóm. Thiếu căn cứ mà chưa muốn kết thúc thì giữ pending; khi kết thúc xem xét mới chốt không chọn.

## 6. Kết luận án một lần và tổng hợp citation

Trong CM4 thử nghiệm, mỗi B dưới một lượt tìm có tối đa một kết luận bất biến. Trước đó giá trị chọn mặc định là `not_select` với trạng thái `pending`, không có assessment phủ định do model trả. Đủ bằng chứng thì chốt `select`; kết thúc xem xét mà không đủ hoặc có phản chứng thì chốt `not_select`. Không cấp tool sửa phiếu.

| Nhãn | Điều kiện |
| --- | --- |
| `select` (1) | Model chỉ được đoạn A đang nhắc nguồn nào và dùng các ref nguyên văn đã giao để nối nguồn đó với **chính quyết định B**. Vai trò người nói và lời trích đã rõ ở mức cần thiết cho kết luận. Bằng chứng về quan hệ còn hiệu lực sau khi đối chiếu các điểm mâu thuẫn. Nếu citation A bị che, chỉ chọn khi các dấu hiệu còn thấy đủ để phân biệt B với án khác. |
| `not_select` (0) | Bằng chứng đang có chưa đủ chắc để chọn B cho lượt tìm. Dùng khi còn mơ hồ về danh tính, người nói hoặc lời trích, khi passage chỉ giống về nội dung, hoặc khi có phản chứng. Có thể ghi lý do ngắn và ref liên quan để biết cần đọc gì tiếp. |

Prompt yêu cầu kiểm chiều A viện dẫn B, định danh chính B và khả năng B đang trích X. Rank, điểm và độ trùng câu không chứng minh viện dẫn. Ref model gửi phải đúng A/B trong payload hiện tại, có provenance và nguồn hợp lệ. Host khóa theo `(search_query_id, B)` trong ledger/context, loại tool kết luận sau chốt và từ chối nộp lại ở host. Đọc thêm, đổi lý do, đổi thứ tự ref hoặc resume không mở khóa.

Host giữ riêng kết luận cấp án và độ phủ passage theo receipt. Không tạo phiếu giả cho hit chưa đọc. Pending khi STOP hoặc kết thúc query vẫn là dang dở; query còn B pending phải được ghi partial. Khi tổng hợp toàn án A, hợp B đã được chọn qua các lượt tìm và khử trùng case_id; kết luận âm của lượt khác không xóa kết luận dương đã khóa. Chốt sớm sai không sửa trong cùng lượt: đây là giới hạn được chấp nhận của contract mới.

## 7. Kiểm và đo trước pilot

| Đối chiếu cùng tập discovery | Câu hỏi |
| --- | --- |
| Hybrid issue so với hybrid nguyên văn và RRF hai nhánh | Mỗi nhánh đưa thêm được gold nào? Có bao nhiêu gold mất từ hợp hai nhánh xuống pool 50? |
| Thứ tự passage từ retrieval so với Qwen top-k trên cùng pool | Ở `k=5, 10, 20` hit cấp đoạn, còn bao nhiêu án khác nhau và bao nhiêu gold theo `case_id`? Kiểm xem nhiều hit từ cùng án có làm mất quá nhiều độ phủ án hay không. |
| Survey 50 của CM4 v30 so với mở trực tiếp nhóm án từ top hit | Bao nhiêu lượt survey, gán ưu tiên, lượt đọc và token controller giảm? Phần giảm có bù được lượt hybrid bổ sung và chi phí rerank không? |

Gold ở evaluator. Với nhiều nhu cầu trong cùng án A, đo trên hợp các pool hoặc shortlist tương ứng theo cặp `(A, B)`. Báo riêng gold vào pool, được khảo sát, được mở nguyên văn và được chốt. Chỉ tính micro P/R/F1 khi có prediction cuối. Với latency, ghi riêng retrieval từng nhánh, queue/cold start và thời gian chấm Qwen, rồi so thời gian toàn run. Tính cả lỗi và lượt thử lại.

Kiểm local các ca hợp trùng ID, án chỉ có ở một nhánh, một nhánh rỗng, cả hai nhánh rỗng, lỗi hoặc thiếu receipt, rank hòa, thiếu lead, và hai nhu cầu có cùng issue nhưng khác span A. Kiểm replay giữ đúng shortlist và lead. Kiểm mở B trực tiếp trước khi đủ receipt các trang thẻ, từ chối ref không được cấp hoặc án ngoài shortlist, và không thêm hit cùng B từ ngoài top 10.

Kiểm gói đọc trên án thật có `Summary` trước `Topic`, `Summary` chỉ báo không có tóm tắt, và án bắt đầu ngay ở phần thân. Đối chiếu từng nhãn với đúng vùng nguyên văn. Kiểm model được cấp chú thích về phần chưa kiểm ngữ nghĩa và có đường đọc thêm khi gặp lời đương sự, định danh mơ hồ hoặc án B trích án thứ ba.

Kiểm ba tool mới trên dữ liệu thật có định danh rõ, đầu án bị che, câu dẫn nằm ở đoạn trước, lời trích lồng và dấu viện dẫn còn sót ở A. Kiểm ref hết hạn, sai cặp hoặc sai bên bị từ chối. Khi vùng cần đọc bị chia qua nhiều payload, replay phải tiếp tục đúng vị trí và chỉ tính byte đã có receipt. Kiểm prompt, schema, dispatch và recovery của CM4 thử nghiệm đã loại hai tên tool cũ, đồng thời vẫn có đường đọc tiếp và đường ghi thiếu bằng chứng. Đo số lượt đọc thêm, token và lỗi nhầm B với án X mà B trích.

Kiểm kết luận trên án có căn cứ rõ A viện dẫn B, B chỉ trích X, và định danh A mơ hồ. Pending không tạo assessment. Chốt hợp lệ giữ model trong án để đọc tiếp hoặc tự rời nhưng không cho sửa; schema và host đều chặn nộp lại, kể cả sau resume. Kiểm âm ở query khác không xóa dương đã khóa.

Kiểm thứ hạng xen kẽ với một án có hit 1 và 6, án khác có hit 2 và 10. Hợp vùng chồng lấn và giữ ánh xạ hit. Chốt select từ evidence hit 1 vẫn cho đọc hit 6; chốt âm hoặc pending đều cho rời và mở lại, nhưng chỉ pending được kết luận. Kiểm resume vị trí, khóa kết luận, cảnh báo vòng lặp và last_action thành công/lỗi đúng ledger.

Kiểm payload đã đóng gói ở cả survey và assessment. Điểm từng nhánh, điểm Qwen, thứ hạng và giới hạn top-k có trong chẩn đoán host, đồng thời vắng trong dữ liệu và hướng dẫn model nhận. Đổi thứ hạng trong một fixture giữ nguyên tập hit và preview đã chọn phải giữ nguyên thứ tự thẻ và thứ tự đoạn hiển thị.

## 8. Phạm vi sửa sau pilot grouped-reading ngày 21/11

Nguồn chẩn đoán: `cache/cm4-grouped-reading-20261121-113512216/{semantic_steps.md,semantic_review.md,loop_evidence.json}`. Pilot đã mở trực tiếp và rời/mở lại án, nhưng lặp đánh giá cùng hit ở `023160.txt`. Các mục dưới là contract đợt triển khai mới; kết quả kiểm local và giới hạn được ghi ở PROGRESS, không lấy pilot v2 làm nghiệm thu mới. Giữ top 10 passage tự gom; model quyết định độ sâu đọc và thời điểm rời án.

### 8.1. Một kết luận duy nhất cho mỗi án B trong lượt tìm

Chỉ đạo mới thay thế đề xuất tách tool sửa phiếu. Phạm vi kết luận là `(query_id của lượt tìm, case_id B)`, không phải từng hit; các passage cùng B là evidence cho một quyết định chung. Các mục 4–7 áp dụng contract mới này.

- B mặc định có giá trị chọn `not_select` nhưng trạng thái là `pending`, chưa có kết luận model. Không yêu cầu model nộp lại `not_select` sau mỗi passage. Đọc, tìm thêm và mở lại khi chưa chốt không tạo phiếu hay version assessment.
- Khi đủ bằng chứng A viện dẫn chính B, model được chốt `select` ngay, kèm ref A, ref B và evidence định danh hợp lệ. Không bắt đọc hết passage còn lại trước khi chọn. Đây vẫn là nhận định của model, không phải gold.
- Khi model kết thúc xem xét B mà không đủ căn cứ chọn, hoặc đã có căn cứ B không phải nguồn được viện dẫn, chốt giữ `not_select` cùng lý do và các ref đã đọc nếu có. “Kết thúc” là quyết định của model, không bắt đọc toàn án hoặc toàn bộ top 10. Rời tạm để xem án khác không tự chốt.
- Host chỉ cho commit kết luận đúng một lần. Sau khi chốt, loại B khỏi lựa chọn kết luận trong schema và từ chối mọi lần nộp lại ở host, kể cả đổi nhãn, lý do, thứ tự ref hoặc thêm evidence. Không cấp tool sửa/thu hồi quyết định trong lượt tìm đó. Dữ liệu kết luận phải được lưu bền và khôi phục đúng sau resume.
- Model vẫn có thể đọc thêm hoặc mở lại B đã chốt nếu muốn, nhưng không có lựa chọn đánh giá lại. Guidance nêu rõ kết luận đã khóa. Một lượt tìm khác có nhu cầu/span A khác có trạng thái riêng; không mở lại query chỉ để né khóa. Tổng hợp cuối phải phân biệt kết luận theo từng lượt và khử trùng B.
- Run bị STOP hoặc model kết luận query khi B còn pending: giữ mặc định không chọn trong tập kết quả nhưng lưu riêng trạng thái chưa kết luận/chưa đọc, không bịa phiếu phủ định hay báo review hoàn tất. Phân biệt `pending` với `final_not_select` trong payload, ledger và báo cáo.
- Rủi ro được chấp nhận: chốt sớm sai sẽ không sửa được trong cùng lượt tìm. Vì vậy model cần đọc thêm trước khi chốt nếu còn mơ hồ về định danh, người nói hoặc chuỗi trích dẫn. Cơ chế này ngăn sửa qua lại; không bảo đảm model không lặp công cụ đọc.
- Kiểm replay vòng lặp `023160.txt`; không còn tool chấm lại sau kết luận; host từ chối hành động lặp hoặc đổi nhãn; nhiều hit cùng B chỉ có một kết luận; chọn sớm khi đủ evidence; giữ pending khi rời tạm; chốt không chọn khi model kết thúc; mở lại/read tiếp sau chốt không mở khóa; resume không mất khóa; STOP và partial conclusion giữ đúng trạng thái. Cập nhật các test v2 từng yêu cầu sửa/thu hồi phiếu để phản ánh contract mới, không ghi lại lịch sử run cũ.

### 8.2. Phân biệt tìm thêm trong B với mở lại đoạn đã giao

- Giữ `read_case_passages(focus)` tìm trong đúng B đang mở. Phân loại kết quả theo `case_id`, source hash, byte spans và receipt đã giao; không dựa vào việc focus đổi chữ.
- Kiểm toàn bộ tối đa 3 hit trả về thay vì luôn lấy hit đầu. Phân biệt: có phần nguồn chưa giao; chỉ khớp các đoạn đã giao; không có hit. Khi chỉ có đoạn cũ, báo rõ và cấp lựa chọn mở lại có chủ đích thay vì tự giao lại như một phát hiện mới.
- Với span chồng lấn, ghi phần byte mới và giữ ngữ cảnh đọc cần thiết. Mở lại vẫn là hành động hợp lệ nhưng không tăng độ phủ nguồn; byte mới chỉ chứng minh giao thêm nội dung, không chứng minh có bằng chứng pháp lý mới.
- Kiểm ca focus khác nhưng cùng span, hit đầu cũ/hit sau mới, chồng lấn một phần, không có hit, mở lại có chủ đích, receipt chưa nhận và nguồn thay đổi.

### 8.3. Mô tả đúng chức năng `read_passage_attribution`

- Giữ một tool hiện có, không thêm tool trùng chức năng. Cập nhật mô tả thành: “Đọc ngữ cảnh trước/sau passage để model kiểm tra người nói và nguồn trích”. Đồng bộ prompt, catalog, schema descriptions, source labels và tài liệu liên quan.
- Nêu đúng cơ chế hiện tại: host mở rộng cửa sổ khoảng ±1.200 byte quanh vùng passage và cấp phần chưa giao trong ngân sách. Host không khẳng định đã nhận diện câu dẫn, người nói hoặc ranh giới quotation bằng ngữ nghĩa.
- Giữ nguyên nguồn canonical, hash, offsets, receipt và continuation. Nhãn xuất xứ mô tả vị trí/ngữ cảnh được mở; việc xác định người nói, B đang trích X và quan hệ A→B vẫn do model đối chiếu.
- Kiểm catalog/nhãn không hứa đã tìm đúng câu attribution; phần trước/sau và continuation giữ đúng nguồn, vùng đã giao không bị báo là mới, khoảng mở rộng không vượt biên án. Đối chiếu trên passage có câu dẫn và passage không có câu dẫn trong cửa sổ.

Sau triển khai, kiểm local trên code cuối rồi chuẩn bị namespace mới cho AG chạy. Báo riêng kết quả regression, replay và live; chưa đổi model/GPU/retrieval hoặc kết luận chất lượng COLIEE từ các sửa này.

## 9. Chạy profile thử nghiệm

Người dùng hoặc AG deploy worker theo quy ước repo. Lệnh lookup chỉ lấy ID của method đã deploy. `prepare` kiểm local và ghim ID này vào plan. Cần namespace mới sau khi đổi code, model, settings hoặc function ID.

```powershell
& .venv/Scripts/python.exe -m modal deploy -m pipeline_v2.deployments.modal_cm4_reranker.app
$rerankerId = & .venv/Scripts/python.exe -c "import modal; print(modal.Cls.from_name('coliee-cm4-qwen3-reranker-l4', 'Reranker')().score.hydrate().object_id)"
$run = 'cache/cm4-dual-query-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $run --reranker-function-id $rerankerId
# Người dùng hoặc AG chạy sau khi đối chiếu plan, preview và ngân sách.
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir $run
```

Có thể thêm `--max-turns` khi prepare để giới hạn pilot. Khi chạy lượt đối chứng CM4 dùng profile cũ, prepare namespace riêng và bỏ `--reranker-function-id`. Reranker lưu admission, call ID và receipt riêng dưới `reranker/`. Khi đã có admission nhưng chưa có receipt dùng được, kiểm call gốc trước khi quyết định bước tiếp theo.

Giới hạn còn lại. Bằng chứng định danh có ref thuộc chính B và được kiểm nguyên văn; kết luận hai định danh chỉ cùng một án vẫn do controller đánh giá. Receipt xác nhận đã giao đoạn, không chứng minh model hiểu hay xác minh đúng quan hệ viện dẫn. Bản kết luận một lần v3 cần kiểm local rồi pilot namespace mới; không dùng kết quả protocol để suy ra F1. Cơ chế phát hiện nguồn thay đổi của ledger vẫn có hiệu lực.
