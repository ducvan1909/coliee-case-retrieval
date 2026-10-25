# Các lỗi hiện tại của pilot V5

> File tạm phục vụ thảo luận và lập kế hoạch sửa. Nội dung dựa trên năm án
> calibration `011904`, `013009`, `013948`, `045155`, `099980`. Đây là đánh giá
> trực tiếp của agent, chưa phải human gold.

## 1. Trạng thái tổng quát

V5 đã đạt các bảo đảm kỹ thuật chính:

- 5/5 án hoàn tất;
- không còn `empty_output` hoặc `inconsistent_output`;
- không còn lỗi operation, protocol hoặc verifier protocol chưa giải quyết;
- 48/48 excerpt khớp tuyệt đối với nguồn theo hash và vị trí;
- không phát hiện thao tác bị mất hoặc áp dụng lặp.

Tuy nhiên V5 chưa đạt chất lượng ngữ nghĩa:

- 27 item hợp lệ kỹ thuật;
- model verifier chấp nhận 12 và bác 15;
- kiểm tra trực tiếp chỉ giữ được 8 item, bác 19 item;
- 4/12 item được model chấp nhận là false positive;
- trong 8 item có thể bảo vệ chỉ có 1 AU, còn lại là brief.

Không mở tập 20 án ở trạng thái hiện tại.

## 2. Các false positive đang có

| Item | Lỗi |
|---|---|
| `045155:brief:000` | Chọn vùng headnote/tóm tắt biên tập nhưng gắn các tham chiếu là `current_court`; item facts còn trộn cả kết quả tố tụng. |
| `045155:aus:000` | Dùng headnote/editorial làm `court_response`; AU verifier gọi cùng nguồn là `current_court` dù brief verifier nhận đúng là `editorial`. |
| `045155:aus:001` | Source authority chỉ là dòng citation “Act ... s.27”, không chứa nội dung nghĩa vụ được cho là đã được áp dụng; `treatment=applies` thiếu rule text trong item. |
| `099980:brief:002` | Nội dung là câu hỏi/yêu cầu của applicant nên attribution phải là `party`, nhưng item và verifier đều chấp nhận `current_court`. |

## 3. Lỗi attribution

Agent và verifier vẫn nhầm giữa:

- phát biểu riêng của tòa và authority được tòa viện dẫn;
- lời/yêu cầu của đương sự được tòa thuật lại và phát biểu của tòa;
- headnote/editorial và phần thân judgment;
- ghi chú “Translation by the Court” và chủ thể gốc của nội dung được dịch.

Các trường hợp đã thấy:

- câu nêu “trite law” hoặc kết luận standard of review bị gắn
  `cited_authority`, dù đó là phát biểu của `current_court`;
- câu “the applicant is asking the Court...” bị gắn `current_court`, dù chủ thể
  của mệnh đề là `party`;
- headnote được gắn `current_court`;
- cùng một stable source ID có thể được verifier brief gọi là `editorial` nhưng
  verifier AU lại gọi là `current_court`.

Host hiện chỉ kiểm tra attribution bên trong từng review. Chưa có kiểm tra nhất
quán attribution của cùng một source ID giữa nhiều item trong cùng case.

## 4. Lỗi treatment

Reader thường khai `applies` khi bằng chứng mới chỉ cho thấy:

- authority hoặc điều luật được nhắc đến;
- có một dòng citation;
- có một câu nêu quy tắc;
- authority được gọi là cách hiểu đúng của luật;
- hoặc court response chỉ cùng chủ đề nhưng không áp dụng đúng quy tắc đã chọn.

Các lỗi cụ thể:

- `013948:aus:003`: authority nói về subsection 172(4), còn response nói về
  written assessment theo subsection 172(2);
- `045155:aus:001`: authority ref chỉ chứa tên đạo luật và section, không chứa
  proposition pháp lý được áp dụng;
- `099980:aus:000` và `099980:aus:001`: chỉ nêu nguyên tắc/quy tắc, không có
  phản ứng tòa chứng minh application;
- `099980:aus:002` và `099980:aus:003`: dùng yêu cầu của applicant làm court
  response cho `applies`.

Việc citation xuất hiện không đủ chứng minh `applies`. Treatment phải chỉ ra:

1. proposition của authority;
2. phản ứng/kết luận của tòa hiện tại;
3. quan hệ cụ thể giữa hai phần đó trong vụ hiện tại.

## 5. Thiếu điều kiện hoặc ngoại lệ thiết yếu

`013948:aus:002` chọn quy tắc về written assessment và kết luận của tòa, nhưng
không lưu câu xác lập điều kiện trung gian rằng risk assessment là âm.

Verifier được xem câu thiếu này dưới dạng context và bác item. Đây là hành vi
đúng của host: context bổ sung không tự trở thành bằng chứng đã lưu. Tuy nhiên nó
cho thấy reader chưa chọn đủ chuỗi bằng chứng cần thiết.

## 6. Lỗi phân loại brief

Các lỗi đã gặp:

- kết luận của tòa bị gắn `issues`;
- định nghĩa từ điển hoặc nguyên tắc pháp lý bị gắn `facts`;
- chỉ chọn heading “THE COURT DECLARES AND ORDERS” làm `disposition`, không chọn
  nội dung các lệnh;
- headnote chứa nhiều chức năng bị lưu thành một item facts;
- câu posture hoặc disposition bị trộn trong một item facts mà không tách nguồn
  cụ thể.

Verifier đã bác phần lớn các lỗi này, nhưng chưa phát hiện ổn định vùng headnote.

## 7. Verifier thiếu nhất quán và chưa đủ độc lập

Ví dụ rõ nhất là source vùng 1126–2082 của case `045155`:

- brief verifier nhận đây là `editorial`;
- AU verifier lại nhận là `current_court` và chấp nhận AU.

Reader và verifier cùng dùng một model, nên lỗi đọc nguồn có thể tương quan.
Model verifier chấp nhận không thể được coi là chứng cứ độc lập rằng item đúng.

Hiện chưa có các kiểm tra host sau:

- phát hiện cùng source ID có nhiều attribution mâu thuẫn;
- phát hiện source thuộc vùng headnote nhưng được gắn `current_court`;
- buộc `applies` có authority proposition và court response đủ nghĩa;
- phát hiện một court response được dùng cho authority không tương ứng.

## 8. Không có semantic repair sau verifier

Pipeline có protocol repair và selection recovery cho mâu thuẫn `found` nhưng
không có AU. Pipeline chưa có vòng sửa khi một item hợp lệ kỹ thuật bị verifier
bác.

Ví dụ `011904:aus:000`:

- source chứa một nguyên tắc standard of review có thể dùng làm AU;
- item bị bác vì attribution `cited_authority` sai;
- có thể sửa thành `current_court` và `treatment=unknown`;
- pipeline hiện chỉ kết thúc với `all_items_rejected`, không cho agent sửa item.

Do đó verifier đang loại lỗi nhưng chưa giúp xây lại item đúng, gây mất cơ hội AU.

## 9. Selection recovery chưa được kiểm tra bằng request thật

Cơ chế cho đúng một lượt bổ sung lựa chọn khi `found` nhưng không có AU đã được
kiểm thử cục bộ. Trong fingerprint V5 cuối, cơ chế này không được kích hoạt ở
năm request thật vì reader đã tạo AU trước finalizer.

Vì vậy hiện chỉ có bằng chứng hồi quy host, chưa có bằng chứng model thật tuân thủ
prompt selection recovery.

## 10. Nguy cơ bỏ sót AU

- `011904`: có AU standard-of-review nhưng bị mất khỏi tập accepted do sai
  attribution;
- `013948`: AU written-assessment thiếu điều kiện thiết yếu;
- `099980`: các nguyên tắc section 29/69 và fraud/error được tìm thấy, nhưng
  reader thường ép `applies` hoặc gắn sai attribution thay vì lưu AU
  `treatment=unknown` có căn cứ;
- chỉ có 1 AU trong toàn bộ năm án được kiểm tra trực tiếp là có thể bảo vệ.

Reader coverage:

| Case | Coverage |
|---|---:|
| 011904 | 99,65% |
| 013009 | 99,71% |
| 013948 | 99,37% |
| 045155 | 42,36% |
| 099980 | 85,75% |

Coverage chỉ cho biết nguồn đã được cung cấp, không chứng minh model hiểu nguồn.
Riêng `045155` và `099980` còn phần nguồn chưa đọc đáng kể nên chưa thể kết luận
không còn AU bị bỏ sót.

## 11. Điều kiện chưa đạt để mở tập 20 án

Các điều kiện còn thiếu:

- không còn item model-accepted nhưng sai attribution/treatment;
- cùng source ID không có đánh giá attribution mâu thuẫn chưa được xử lý;
- AU `applies` phải có đủ authority proposition, court response và liên hệ;
- item bị verifier bác nhưng có thể sửa phải có semantic repair hoặc được giữ
  rõ là cơ hội AU bị mất;
- selection recovery cần ít nhất một lần kiểm tra với model thật;
- các case có coverage thấp phải được báo rõ phần chưa đọc và nguy cơ omission;
- mọi accepted trong calibration phải được kiểm tra trực tiếp theo từng thành
  phần, không chỉ dựa vào trạng thái tổng của model verifier.

## 12. Kết luận tạm

V5 đã đáng tin về provenance, nguyên văn, trạng thái và phục hồi giao thức. V5
chưa đáng tin về quyết định chọn nguồn, attribution và treatment. Không nên chạy
20 án hoặc đánh giá retrieval trước khi giảm false positive trong tập accepted
và tăng số AU thực sự có thể bảo vệ.
