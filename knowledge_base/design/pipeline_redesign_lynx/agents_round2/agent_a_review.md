# Agent A — phản biện tính đúng vòng 2

## Kết luận độc lập

Kiến trúc đã sửa đúng ở lõi: source bất biến, exact offsets, raw lane độc lập, annotation chỉ là sidecar, treatment không làm filter, và thiếu evidence phải giữ `unresolved`. Tôi không thấy lý do quay lại full-corpus AU hay global finalizer. Tuy nhiên, “source vẫn tồn tại” đang được dùng gần như đồng nghĩa với “coverage được bảo toàn”; hai điều này khác nhau. Năm lỗ hổng dưới đây có thể làm mất bằng chứng dù mọi structural test đều PASS.

## 1. Raw BM25 chưa đủ để mang lời hứa coverage

**Claim →** R0 dùng paragraph/window BM25 và được xem là fallback bảo vệ coverage.

**Counterexample →** Query đã che citation và diễn đạt quy tắc bằng từ khác với án liên quan. Source được index đầy đủ nhưng không có lexical overlap đủ để vào top 200. Đây chính là tình huống mà source spine đúng về lưu trữ nhưng retrieval vẫn thất bại.

**Consequence →** Sidecar có thể bị kết luận là vô ích vì không cứu được candidate mà BM25 chưa từng đưa vào; ngược lại, một sidecar lexical có thể trông hữu ích chỉ vì baseline raw quá yếu. Kết luận kiến trúc về coverage và contribution sẽ sai.

**Exact fix →** Thêm một raw semantic lane độc lập vào baseline thực nghiệm (dense hoặc phương án semantic retrieval đã khóa), vẫn chỉ index exact source spans và không dùng AU/gold. Báo riêng BM25, semantic-raw và hybrid; nếu chưa triển khai, đổi mọi phát biểu “bảo vệ coverage” thành “bảo vệ lexical fallback”.

**Deciding test →** Trên cùng candidate budget, so Recall@50/100/200 và unique-gold cases của BM25, semantic-raw và hybrid, đặc biệt ở masked-citation, paraphrase và no-citation slices. Chỉ được gọi R0 là coverage baseline nếu hybrid không tạo gain có ý nghĩa.

## 2. `source floor` chưa có invariant nên fusion vẫn có thể làm rơi raw hit

**Claim →** Raw lane độc lập và “source floor” ngăn annotation/AU-rich cases lấn raw cases, trong khi tổng candidate budget được giữ cố định.

**Counterexample →** Raw trả 200 case; combined cũng bị cắt ở 200 nhưng dành quota cho AU/annotation. Nếu floor không có con số và tie/case-dedup rule chính xác, một relevant case ở raw rank 180 có thể bị loại bởi nhiều AU-rich cases. Raw index vẫn nguyên vẹn nhưng candidate coverage đã giảm.

**Consequence →** Recall giảm âm thầm; `explain_hit` chỉ giải thích các hit còn sống, không chứng minh case bị rơi. So sánh arm cũng không quy nguyên nhân được nếu quota/fusion thay đổi tập raw trước reranking.

**Exact fix →** Định nghĩa contract bằng tập hợp: log `raw_top_K`, `combined_pre_cut`, `combined_top_K`, mọi case gained/lost và lý do. Khóa quota số nguyên, tie-break, dedup và fusion. Với phép đo contribution, dùng hai chế độ riêng: union budget mở rộng để kiểm tra coverage tiềm năng; fixed budget để đo trade-off thực tế. Không tuyên bố monotonic coverage ở fixed budget nếu không có set-containment.

**Deciding test →** Property test trên mọi query: kiểm tra containment theo floor đã đăng ký và báo `lost_relevant_raw_cases`. Bác bỏ thiết kế quota nếu upper confidence bound của recall loss vượt non-inferiority margin, dù tổng Recall trung bình tăng.

## 3. Evidence resolver chưa có “searched frontier” cho qualifier và court response xa

**Claim →** Mở paragraph trước/sau, heading gần nhất và related mentions, rồi dừng khi không tăng evidence hoặc hết budget, đủ để bảo vệ qualifier/attribution/treatment.

**Counterexample →** Một authority được trích ở phần arguments; phản hồi thật của tòa nằm nhiều section sau, dùng tên viết tắt hoặc không lặp citation. `find_related_mentions` phụ thuộc annotation vốn có thể miss; vòng mở cục bộ không tăng evidence nên dừng sớm. Tương tự, exception có thể nằm ở đầu section chứ không ở paragraph kề.

**Consequence →** Treatment thành `unresolved` quá thường xuyên hoặc, nếu acceptance kiểm lỏng, bị gán từ lời party. Qualifier bị tách khỏi proposition dù exact offsets đều đúng.

**Exact fix →** Mỗi obligation phải có chiến lược raw-source fallback và ledger `searched_ranges/search_modes`: local window → section → all raw lexical/coreference mentions → bounded forward/backward scan → whole-case control. `stop_reason` phải phân biệt `evidence_found`, `frontier_exhausted` và `budget_exhausted`; hai trạng thái sau không được đồng nhất.

**Deciding test →** Tạo slice có response/condition ở nhiều khoảng cách, alias, citation detector bị tắt và nhiều speaker. Đo obligation recall, false treatment acceptance, chars mở và tỷ lệ budget-exhausted; so với whole-case blinded control.

## 4. Provenance cấp record không ngăn attribution sai ở từng field

**Claim →** `DerivedRecord.source_hash + evidence_refs[] + verification_dimensions` đủ cho provenance và acceptance.

**Counterexample →** Một AU có proposition từ lời tòa, qualifier từ đoạn khác và speaker/treatment do model suy ra. Danh sách evidence chung có thể chứa tất cả spans nhưng không chỉ ra span nào chứng minh field nào; model có thể gắn party span cho `speaker=court` mà record vẫn materialize đúng source.

**Consequence →** Provenance có thật nhưng quan hệ claim–witness sai; audit không phát hiện attribution, qualifier hoặc court response bị tráo.

**Exact fix →** Chuẩn hóa `verification_dimensions` thành map bắt buộc theo field: `{value, status, evidence_refs, verifier, reason}`. `accepted` chỉ khi proposition, attribution và mọi qualifier/treatment field áp dụng đều có witness riêng; normalized text phải liên kết tới source claim span, còn suy luận không có witness giữ `unknown`.

**Deciding test →** Mutation test tráo witness giữa party/court, bỏ qualifier span, hoặc dùng authority proposition thay receiving-court response. Validator phải từ chối 100% mutation và vẫn nhận các record đúng.

## 5. Holdout 40 case không đủ để chứng minh an toàn cho lỗi hiếm nhưng nghiêm trọng

**Claim →** Mẫu 20 development/40 holdout cân bằng split × length, cộng phenomenon slices, đủ để đặt threshold per-type và chọn component.

**Counterexample →** Mẫu chính không được stratify theo speaker conflict, distant response hay qualifier; slice bổ sung lại bị báo ngoài metric chính. Chỉ 20% holdout được annotate hai lượt có thể để lại vài hoặc không có positive cho từng lỗi. Micro/macro F1 tốt vẫn tương thích với treatment sai hàng loạt ở nhóm hiếm.

**Consequence →** Component vượt gate do thiếu power, rồi làm mất qualifier/attribution trên toàn corpus. Bootstrap theo case không sửa được việc không quan sát đủ positive.

**Exact fix →** Trước annotation, đăng ký số positive tối thiểu và severe-error ceiling cho từng critical dimension; oversample bằng rule không dùng gold, đánh giá theo case/authority cluster, và double-annotate toàn bộ critical slice. Giữ metric chính đại diện corpus, nhưng gate an toàn phải dùng worst-slice non-inferiority riêng.

**Deciding test →** Tính CI cho severe omission/false acceptance theo từng slice. Nếu CI không loại trừ mức hại đã khóa, kết quả là “insufficient evidence”, không phải pass; mở rộng mẫu bằng seed đã đăng ký.

## Steelman và tự phê bình

Phiên bản mạnh nhất của kiến trúc là một hệ thống chịu lỗi: canonical source không mất, mọi derived view đều rebuild được, semantic uncertainty không bị ép thành fact, và component chỉ sống sau ablation. Nó giải quyết đúng thất bại V13–V15 mà không phải trả chi phí full KG.

Phản biện của tôi cũng có giá: semantic-raw lane và whole-case control tăng compute; field-level provenance làm schema và annotation nặng hơn; safety slices làm chậm quyết định. Một số lỗi có thể chỉ làm tăng `unresolved`, không trực tiếp tạo kết luận sai. Vì vậy các sửa đổi trên phải được giữ ở mức contract và arm thực nghiệm; nếu deciding test cho thấy không có gain hoặc lỗi đáng kể, chọn thiết kế đơn giản hơn.
