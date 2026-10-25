# Plan 12 — Model lựa chọn, host dựng evidence

## Phạm vi

Thay đường truyền response của model trong vòng validate/repair. Giữ contract đầy đủ `repair_wire.v2.json` và artifact lịch sử. Không thay AU extraction ở Plan 10, model, ngân sách, endpoint hoặc tiêu chí ngữ nghĩa.

## Phân công

Host lập danh mục evidence từ các atom đã thực sự được cung cấp trong lượt hiện tại. Mỗi lựa chọn gắn với task, case, phiên bản source và exact span. Không đưa text chưa đọc vào danh mục; sau khi mở context, host dựng danh mục mới.

Model chọn primary proposition, witness và tham chiếu evidence trong danh mục, thay vì tự chép quote hoặc tính offset. Proposal, tool, verdict, defect type, action, kind, speaker, attribution role và context flags bị giới hạn bởi danh mục hoặc enum tương ứng. Claim, reason và nhãn `other_kind` vẫn là text có giới hạn độ dài; chúng không phải kết luận được host xác nhận.

Host chuyển lựa chọn thành contract đầy đủ, rồi kiểm tra lại schema, nguồn và quan hệ giữa các field trước khi lưu revision. Không tự loại trùng để biến một response sai thành hợp lệ. Không tự chuyển `uncertain` thành `supported` hoặc `reject`.

Đường truyền mới dùng `repair_selection_wire.v1.json`, với `schema_version=repair-selection-v1`. Danh mục baseline gồm nguyên atom và phần giao atom–TARGET, tối đa 128 lựa chọn; không tự sinh các đoạn ngữ nghĩa mới. ID ngắn gắn fingerprint của view; host kiểm tra collision. Input dùng bảng metadata gồm ID, chỉ số atom, hai offset tương đối và cờ `target_eligible`, không lặp nguyên văn. Primary chỉ chọn tập `target_eligible`; witness và `open_span` chọn tập đã đọc. Grammar chặn ID trùng trong mảng witness hữu hạn.

## Ràng buộc phải giữ

- ID ngoài danh mục, ID thuộc task/source khác, ID chưa đọc và lựa chọn trùng phải bị bác bỏ.
- Primary phải nằm hoàn toàn trong TARGET và thuộc evidence của AU; witness chỉ ra lỗi có thể thuộc context đã đọc.
- Nhiều witness và nhiều AU replacement vẫn được phép theo trần hiện tại.
- Chọn proposal retained không đủ chứng minh duplicate về ngữ nghĩa. Grammar production và host cùng kiểm tra retained khác chính nó và được đánh giá `supported` trong cùng response, kể cả khi anchor xuất hiện phía sau.
- Mỗi original proposal có đúng một slot theo thứ tự `original_proposals`; host tiếp tục kiểm tra exact-once sau giải mã. Schema/normalizer không yêu cầu thứ tự này.
- Contract đầy đủ dùng `{atom_id, quote}` nên subquote phải có vị trí duy nhất trong atom. Không chọn lần xuất hiện đầu tiên khi quote lặp. Nếu danh mục không biểu diễn được primary hợp lệ thì dùng `uncertain` hoặc mở thêm nguồn.
- Cache và receipt phải gắn phiên bản wire mới; không tái sử dụng response cũ như response lựa chọn.

## Kiểm chứng

Kiểm tra local việc dựng exact span, Unicode, quote lặp, atom cắt qua TARGET, evidence trùng, ID giả/cũ/chưa đọc, cập nhật context, condition giữa các field và bảo toàn baseline khi `uncertain`. Kiểm tra grammar trên wire lựa chọn riêng và kiểm tra contract đầy đủ sau chuyển đổi.

Probe endpoint phải báo riêng: wire có hợp lệ không, chuyển đổi host có hợp lệ không và còn nhánh nào chưa chạy. Parse failure phải giữ diagnostic đủ phân biệt JSON sai cú pháp, key trùng và output bị cắt. Không gộp chúng thành một `null` không rõ lý do.

PASS hình thức chỉ xác nhận model chọn địa chỉ hợp lệ và host truy nguyên được nguồn. Nó không chứng minh evidence hỗ trợ claim, attribution đúng hoặc AU đạt chất lượng.

## Giới hạn thực thi hiện tại

Compiler relations production giới hạn 6 original proposals/task, fail rõ bằng
`decision_relation_limit_exceeded` khi vượt cap. Các state theo tập supported
và slot có độ phức tạp O(n * 2^n), không enumerate mọi tổ hợp verdict/anchor.
Tập supported có thể rỗng: all-uncertain và all-defect không duplicate vẫn được
phép. Không ép verdict semantic để giảm grammar; cycle và uncertain anchor bị
loại do duplicate chỉ trỏ tới supported. Không âm thầm sửa ID hay verdict.

Đếm local trên manifest repair V6 sau khi thêm catalog: R1 cho cả manifest nằm trong trần 20.000 token; R2 dự phòng hai lượt cho mỗi task có AU vượt trần tổng run. Chạy R2 theo từng task và preflight từng lượt, không nâng ngân sách để che overhead. Ước lượng input dùng byte UTF-8, không phải tokenizer hoặc provider usage. Chỉ probe endpoint mới xác nhận được response thực tế tuân thủ wire mới; chưa có phép đo lợi ích token hay chất lượng ngữ nghĩa sau thay đổi này.
