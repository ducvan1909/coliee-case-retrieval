# Đề xuất sửa vòng lặp chọn đoạn trong CM4

Bản đề xuất ngày 22/11/2026 cho nhánh tìm kiếm từ nguyên văn A. Đọc cùng [kế hoạch khóa truy vấn A và kiểm định danh B](CM4_SOURCE_BOUND_SEARCH_IDENTITY.md).

## 1. Pilot mắc ở đâu

Controller sau redeploy đã xử lý được request với cap 1.024 token. Pilot `021095.txt` dừng ở T029 khi model vẫn đang xét đoạn [1]. Host đã giao 929 byte từ đầu án. Model xét được 285 trong 927 byte của đoạn [1] qua hai lần chọn đúng span. Run có 29 request, 28 action thực thi và chưa chạy retrieval hay kiểm định danh B. [Nhật ký từng lượt](../../../cache/cm4-source-bound-cap1024-20261122-083057390/semantic_steps.md)

| Lượt | Điều đã xảy ra | Hệ quả |
| --- | --- | --- |
| T003–T004 | Model chọn `no_search_needed` nhưng bỏ trống cả ref lẫn quote. Schema cho phép gửi như vậy. | Host ghi `need_more_context` rồi hỏi lại gần như cũ. Model vẫn thiếu một lựa chọn cụ thể để sửa thao tác. |
| T005, T021 | Model chọn đúng `s1` rồi `s2`, đóng lần lượt `[0,239)` và `[239,285)`. | `[285,927)` vẫn còn việc. LoopGuard gộp hai quyết định vào cùng paragraph nên bỏ qua tiến triển ở T021. |
| T008, T020 | Model chép cả đoạn, một lần bỏ ngoặc kép quanh `Order`, một lần dùng `...` để rút gọn. | Bộ so khớp đúng từ chối cấp span. Tìm gợi ý theo từng câu không đưa được lựa chọn hữu ích cho một quote dài nhiều câu. |
| T022–T029 | Model quay lại mẫu cũ, tiếp tục gửi quyết định thiếu span. | Bộ đếm tăng đến 24 chu kỳ và 23 lượt không tiến triển. Lượt T029 có reply nhưng AG dừng trước khi action thực thi. |

Sửa cần ưu tiên **làm cho lựa chọn đúng dễ gửi ngay từ đầu**, rồi mới cải thiện gợi ý quote và cách đo tiến triển. Chỉ tăng cap hoặc chỉ đổi câu báo lỗi sẽ vẫn để model gửi lại cùng mẫu thiếu span.

## 2. Làm cho model chọn được phạm vi ngay trong schema

Giữ một tool xét nguồn. Schema có nhánh riêng cho các mẫu tham số loại trừ nhau, để model luôn thấy lựa chọn mình đang thực hiện.

| Ý định | Model gửi gì | Host làm gì |
| --- | --- | --- |
| Tìm nguồn | Một `proposition_ref` hoặc một `proposition_quote` kèm thông tin xét như hiện tại. | Xác minh đúng byte nguồn. Nếu đủ điều kiện, cấp permit chỉ chạy nội dung đã khóa. |
| Đã xét và không cần tìm | Một ref đang hiển thị, hoặc quote đúng phần đã xét. Có thể chọn một ref cho cả vùng còn lại đang hiển thị nếu đã đọc và muốn xét cùng một quyết định. | Ghi đúng span hoặc tập span mà ref đã khóa. Các phần khác vẫn có đường quay lại. |
| Cần đọc thêm | Chỉ ra phần đang vướng và chọn đường đọc ngữ cảnh đã cấp nếu có. | Giữ draft và mở vùng liên quan. Việc mở raw chỉ ghi là đã nhận, chưa tính là đã xét. |

- Với hai quyết định đầu, thiếu cả hai trường hoặc gửi đồng thời cả hai phải bị chặn ở schema và được kiểm lại ở host. Khi sai vì thiếu span, trả thông báo riêng như “Chọn một trong các ref còn lại dưới đây”. Không biến lỗi tham số thành một draft thiếu ngữ cảnh mới.
- Trình bày ref còn việc ngay cạnh preview nguyên văn ngắn, theo thứ tự nguồn. Chỉ hiện một nhóm vừa ngân sách mỗi lượt và giữ đường tới các nhóm tiếp theo. Model nên chọn ref trước. Quote là đường linh hoạt khi ranh giới gợi ý chia sai ý.
- Đề xuất thêm ref **phần còn lại của paragraph đang hiển thị** cho `no_search_needed`. Host dựng ref từ giao của phần raw đang hiển thị và các span chưa xét, gắn ref với phiên và hash nguồn. Hiện trước các khoảng byte, số phần và phạm vi đọc. Ref có nhiều khoảng rời thì ghi đúng từng khoảng, không lấp vùng giữa. Cấm dùng ref gộp này làm permit tìm kiếm. Không tự chọn ref gộp nếu model bỏ trống.
- Với đoạn có cả sự kiện và ý pháp lý, model chọn từng đơn vị. Ví dụ ở [2], xét xong mục `1(a)` không được tự đánh dấu `1(b)` đã xét. Ref rộng giúp giảm lượt ở đoạn thủ tục thuần nhất như [1], nhưng model có thể bỏ sót ý nếu dùng rộng quá. Vì vậy đây là lựa chọn chủ động, có phạm vi xem trước và không vượt vùng raw đang hiển thị.

**Ví dụ sau T021:** màn hình ghi `p000001 · đã xét 285/927 byte`, rồi cấp các ref `s3–s7` với preview và một ref cho phần còn lại `[285,927)`. Model có thể chọn một ref nhỏ hoặc xác nhận đã xét toàn bộ phạm vi còn lại. Khi đã xét hết phần này, host ưu tiên đường mở phần tiếp theo. Phạm vi mới từ byte 929 trở đi vẫn chưa được xét.

## 3. Phục hồi khi quote lệch nguồn

1. Giữ nguyên đường khớp literal và chuẩn hóa an toàn đang có. Khi có nhiều vị trí tương đương, model phải chọn một vị trí bằng ref. Byte và hash luôn lấy từ nguyên văn A.
2. Khi không khớp, giải thích ngắn và đưa ref có thể chọn ngay từ vùng liên quan. Với quote ngắn, ưu tiên các câu hoặc mục gần vị trí đang xét. Với quote dài, dùng vị trí mở đầu và các vùng câu liền kề để đưa vài gợi ý bounded. Nếu vẫn không tìm được gợi ý tốt, hiện các ref còn việc của vùng hiện tại thay cho danh sách rỗng.
3. Nếu quote mất dấu ngoặc hoặc dùng `...` như T008/T020, host giữ phần đang làm ở trạng thái chờ và yêu cầu xác nhận ref nguyên văn. Không tự suy phần bị lược hoặc cấp permit từ một quote gần giống. Nếu cần ghép vài câu, chỉ cấp ref gộp thực sự liên tục hoặc cho model mở thêm raw để tự chọn.
4. Sau một lỗi lặp y hệt trên cùng vùng, ưu tiên catalog phục hồi chỉ gồm chọn một ref đã cấp, đọc vùng phù hợp hoặc quay lại. Ghi lỗi để biết model đã thử gì. Cơ chế này cần một lượt mới khi có lỗi, còn lựa chọn ref đúng ngay từ đầu đi theo luồng bình thường.

## 4. Đếm tiến triển theo phần đã xét

- LoopGuard đo **hợp các khoảng byte đã xét hợp lệ trên cùng A**, chia theo hash nguồn và paragraph. T021 phải tăng độ phủ từ 239 lên 285 byte dù số paragraph hoàn tất vẫn là 0. Gửi lại cùng span, gửi span nằm hoàn toàn trong phần đã xét hoặc chỉ đổi lời giải thích thì độ phủ không tăng.
- Tách các số liệu **raw đã nhận**, **span đã xét**, **permit đã cấp**, **search đã thực thi** và **paragraph đã hoàn tất**. Một permit hợp lệ có thể ghi nhận là tiến triển xét, còn lần thực thi ghi ở bộ đếm search. Phần citation hoặc lời dẫn chỉ làm ngữ cảnh không tự làm tăng độ phủ.
- Thay thế hay sửa phạm vi phải giữ đúng trạng thái hiện hành và lịch sử. Để tránh reset vòng lặp bằng cách mở rồi rút lại cùng permit, LoopGuard chỉ coi byte chưa từng xét hợp lệ trong lượt chạy là tiến triển mới về độ phủ. Bộ đếm phần còn việc vẫn dùng quyết định hiện hành để mở lại span vừa được rút.
- Draft thiếu ref, quote chưa xác nhận, hoặc đổi ref nhưng vẫn trỏ cùng byte đều không tăng độ phủ. Tiến triển điều hướng hay raw mới được giao tiếp tục ghi riêng để biết model còn đang tìm lối đi hay thực sự đã xử lý thêm nội dung.

## 5. Thứ tự làm và nghiệm thu

1. **Schema và catalog.** Sửa `engine.py` và `source_gate.py` để tách lỗi thiếu span và để ref còn việc xuất hiện ngay. Thêm lựa chọn xét phạm vi còn lại khi đã có manifest rõ. Kiểm schema thực tế gửi controller, lưu ý tương thích backend xgrammar đã từng lỗi ở `uniqueItems`.
2. **Phục hồi quote.** Sửa `source_gate.py` và phần gợi ý trong `anchor_quote.py` nếu cần. Kiểm rằng gợi ý vẫn cần hành động xác nhận. Dùng nguyên văn thật từ `021095.txt` cho T008 và T020.
3. **Tiến triển và đường đi tiếp.** Sửa `live.py` để đếm phần byte mới, kiểm catalog sau khi quay lại A và giữ lịch sử khi resume. Lấy đúng T003, T005, T021 và mẫu lặp T022 trong ledger cũ để replay ở namespace thử nghiệm.

| Ca kiểm offline | Kết quả cần thấy |
| --- | --- |
| Reply cũ T003 hoặc T022 thiếu ref và quote | Không ghi quyết định hoặc permit. Đường phục hồi cho thấy các ref hợp lệ còn lại. |
| T005 và T021 lần lượt xét hai span của [1] | Hai lần tăng độ phủ, lần lượt 239 rồi 285 byte. Mẫu lặp sau đó không tăng. |
| Sau T021 chọn ref gộp `[285,927)` | Chỉ thêm 642 byte của [1]. [2] và phần raw chưa giao vẫn còn việc. |
| T008/T020 và quote xuất hiện ở hai vị trí | Có lựa chọn nguyên văn hoặc đường đọc phù hợp. Chỉ sau xác nhận mới ghi quyết định; vị trí trùng phải được chọn rõ. |
| [2] có cả `1(a)` và `1(b)`, [18] có ý nhiều câu | Giữ khả năng xét một phần hoặc nhiều câu liên tục. Search nhận permit đã khóa, không nhận ý tự nhập tại lúc chạy. |
| Vùng heading `Failure to Consider` | Heading đứng riêng vẫn không cấp permit. |

Chỉ sau khi kiểm local đạt mới chuẩn bị một namespace live mới cho AG. Mốc đầu tiên là thoát khỏi [1] bằng quyết định có phạm vi rõ và đọc sang [2]. Sau đó kiểm luồng chạy tới search và lượt chốt định danh B. Báo số lượt đến các mốc, byte đã xét, số lỗi thiếu span hoặc quote, token và latency. Replay xác nhận đường thao tác hoạt động. Pilot live xác nhận model hiện tại có tự dùng được đường đó.

## 6. Bản đã triển khai

- Catalog giữ một tool `assess_source_need`. Schema gửi controller có các nhánh riêng để hai quyết định kết thúc bắt buộc đúng một lựa chọn span. `remaining_visible` chỉ dùng với `no_search_needed` và lưu từng khoảng chưa xét, kể cả khi các khoảng rời nhau.
- Reply thiếu hoặc gửi cả hai selector được ghi là schema reject. Nếu các trường còn lại hợp lệ, host cấp một lần sửa cho cùng phạm vi. Khi lặp lại cùng lỗi trong phạm vi đó, run dừng với `repeated_tool_input_rejection` kể cả mode warn. Quyết định thiếu span không tạo draft xét nguồn.
- Quote lệch giữ draft và đưa tối đa ba ref nguyên văn có thể xác nhận. Catalog vùng đang phục hồi ưu tiên ref và đường đọc thêm. Xác nhận dựa vào ref do host cấp, giữ hash và byte offsets.
- LoopGuard dùng hợp các byte đã xét và ghi `screened_query_bytes`. Kiểm replay và preflight không gửi request inference. Kết quả kiểm và namespace mới nằm ở [PROGRESS](../PROGRESS.md).
