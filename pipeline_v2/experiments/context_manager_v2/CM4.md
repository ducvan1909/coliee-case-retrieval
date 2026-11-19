# CM4 — kết nối inference cho một query

Bản `cm4-anchor-flow-v23` đối chiếu câu trích theo nguyên văn, khoảng
trắng và kiểu cặp ngoặc. Với một vị trí khớp duy nhất, host lưu đúng
nguyên văn và offset rồi thực thi truy vấn. Nếu có nhiều vị trí khớp
hoặc chỉ tìm được đoạn gần giống, CM4 đưa tối đa ba đoạn nguyên văn
để model xác nhận trước retrieval. CM4 giữ truy vấn nháp khi model đọc
vùng khác, tạm gác hoặc quay lại. Truy vấn nháp chưa được xác nhận
vẫn là việc chưa hoàn tất.

Bản `cm4-anchor-repair-v22` đưa phản hồi lỗi của `anchor_quote` vào
payload đọc toàn vùng, cùng nguyên văn để model sửa câu trích. Nếu payload
sát trần token, host giữ câu trích và phản hồi sửa trong prompt, giữ
bảng mã đoạn ở host để xác định offset và kiểm tra trước retrieval.

Bản `cm4-anchor-quote-v21` nhận `issue`, `source_proposition` và
`anchor_quote` trong cùng action tìm kiếm. Host xác định mã đoạn và
offset từ câu trích khớp duy nhất trong nguyên văn án đang tra cứu.
Đối chiếu cho phép khác khoảng trắng, giữ nguyên chữ và dấu câu.
Khi câu trích sai hoặc trùng, model nhận phản hồi sửa trước retrieval.
Host giữ nguyên văn quanh câu trích trong payload assessment và cấp
đường quay lại câu trích nếu nó nằm ngoài cửa sổ đang mở.

Bản `cm4-review-flow-v20` tính tiến độ và điều kiện hoàn tất theo từng
cặp vấn đề và ứng viên. Một ứng viên xuất hiện dưới hai vấn đề tạo hai
cặp cần đánh giá. Khi an toàn để chuyển vấn đề, payload có thể cấp ngay
mã chuyển đến một vấn đề còn việc.

Khi đọc ứng viên từ lead truy hồi, CM4 đặt cửa sổ nguyên văn quanh đoạn
khớp. Nếu lead bị chia qua các trang đọc nguồn hoặc qua các payload,
CM4 cấp đường đọc tiếp và chỉ cấp assessment sau khi đã đưa hết lead
qua các lượt đọc với đoạn khớp còn hiện trong payload. Offset các phần
trước và sau đoạn khớp vẫn dùng được. Tìm nội bộ theo focus chuẩn hóa
khoảng trắng. Sau khi phát hiện cụm trùng, host ưu tiên đường đọc hữu
ích khác trong một lượt và hiện các cụm đã thử theo từng cặp.

Bản `cm4-compact-model-view-v19` gửi nguyên văn vùng đang đọc cùng mã án,
mã đoạn ngắn, vị trí, số đoạn và tín hiệu về người phát biểu hoặc trích dẫn.
Host giữ hash, provenance đầy đủ và bảng ánh xạ về mã gốc. Schema dùng cùng
mã ngắn với payload. Sau khi kiểm schema, host tra lại mã gốc trước khi
thực thi tool. Bộ điều hướng dùng bản ghi nguồn của host để theo dõi những
vùng model đã đọc. Danh sách đoạn trong A dùng vị trí và mã đoạn để tra
nguyên văn ngay trong payload.

Kiểm offline bằng tokenizer Qwen trên `027864.txt`: payload chứa trọn
14.831 byte nguyên văn với 8.288 token trên trần 8.500. Bản v18 cần
29.935 token cho toàn án. Luồng replay riêng trên `021095.txt` hoàn tất
13 lượt giả lập, đánh giá 3 ứng viên và phục hồi sau 1 lần nhập lý do
không hợp lệ. Hai kiểm tra dùng 0 lượt inference và 0 lượt embedding thật.

Bản `cm4-whole-query-first-v18` tắt `find_citation_matches` và
`continue_citation_search` trong prompt, schema và registry CM4.
Trước khi cấp đường đọc/map, host thử payload đầy đủ của toàn án A
bằng tokenizer hiện hành. Nếu vừa 8.500 token, chỉ cấp lựa chọn đọc
toàn án và ẩn map. Nếu vượt, các vùng nhỏ hơn được xét qua cùng
`read_query_passages`. `m6.whole_query_fit` ghi số token và quyết định.
Kiểm bằng tokenizer thật trên `027864.txt` cho payload toàn án
29.935 token, nên host vẫn cấp đường chọn vùng. Con số này gồm văn bản
14.831 byte, provenance và registry đoạn, vượt trần 8.500 token.
Report local ở `cache/cm4-whole-query-first-short-20261116-v18/report.json`.

Bản `cm4-unified-query-read-v17` dùng một interface
`read_query_passages(query_ref)` để xem A. Host kiểm payload đầy đủ của
vùng được chọn với tokenizer hiện hành. Nếu vừa 8.500 token, lượt sau
nhận toàn văn vùng đó. Nếu vượt, cùng thao tác trả map các vùng con.
Model tiếp tục chọn vùng con bằng `read_query_passages`. Các lựa chọn
quay về vùng cha/gốc cũng dùng interface này.

Ngưỡng byte chia cây chỉ xác định các vùng trên bản đồ. Host thử cả
vùng lớn hoặc toàn án trước khi quyết định trả văn bản hay map. Kích thước
reader B và các giới hạn retrieval vẫn thuộc cấu hình của run.

Kiểm offline v17 hoàn tất review ba ứng viên trong 14 lượt giả lập, đỉnh
7.555 token và 0 inference/embedding. Run dùng tokenizer và corpus thật ở
`cache/cm4-unified-read-full-20261116-v17/report.json`. Đọc vùng
`027864.txt [0,3184)` cho đủ nguyên văn ở 3.596 token.
Preflight AG cho án ngắn nằm ở
`cache/cm4-unified-read-short-preflight-20261116-01`, với 3.922 token.

Bản `cm4-query-map-first-v16` bắt buộc mở map ở vùng A còn vùng con.
Chỉ vùng lá có thể đọc trực tiếp; host tính trước payload nguyên văn của
cả vùng với tokenizer hiện hành và trần 8.500 token. Vùng không vừa được
thay bằng lựa chọn mở map nhỏ hơn theo ranh giới UTF-8 ổn định.

Sau khi đọc một vùng lá, lượt kế tiếp dùng view `query_leaf` chứa đủ
nguyên văn vùng đó và các tool phù hợp. Map A được mở lại qua lựa chọn
trang query. Vùng đang hiện đủ không được cấp đọc lại. Các tool mở vùng
lân cận A trực tiếp được thay bằng đường chọn trên map. Progress guard
phân biệt các vùng map bằng ref ổn định.

Kiểm offline dùng văn bản và tokenizer thật; luồng review đủ ba ứng viên
hoàn tất sau 14 lượt, đỉnh 7.571 token, 0 inference/embedding. Artifact ở
`cache/cm4-map-first-full-20261116-v16/report.json`.
Bộ test CM4 đạt 67/67. Kiểm chọn vùng thật trên ba án cho đủ raw
`027864.txt [3184,3942)` ở 3.254 token,
`082653.txt [0,705)` ở 2.491 token và
`021095.txt [0,929)` ở 2.525 token. Các lượt này dùng lựa chọn giả lập,
chưa đo hành vi chọn vùng của model thật trên v16.
Report nằm ở `cache/cm4-map-first-<case>-20261116-v16-verified/report.json`.

Bản `cm4-valid-tool-choices-v15` đưa kết quả cũ lên sau truy vấn trùng và
tạm bỏ tìm theo vấn đề trong lượt kế tiếp khi còn ứng viên đọc được. Mã
trích dẫn đã xử lý được bỏ khỏi lựa chọn tìm ban đầu, còn cursor quét
tiếp của need hiện tại vẫn hoạt động. Danh sách điều hướng loại trang
rỗng, trang hiện tại và thao tác resume chính cặp đang xem.

`open_retrieved_passage` mở lead đã xác định theo need và án.
`read_case_passages` dùng `focus` để tìm thêm trong án. Khi need mới có
cùng lead, CM4 có thể đưa lại đoạn đã lưu sau khi kiểm hash và byte span.
Assessment nhận lựa chọn `A`, `B` hoặc `A+B` cho bằng chứng nhận diện và
phản chứng. Văn bản tự do vẫn đi qua kiểm tra tham số và lượt sửa có giới
hạn như v13.

Replay truy vấn trùng dùng ledger v14 đến event 29 và chạy
`replay_fit --check-duplicate-navigation`. Lượt giả lập đi tiếp đến
`013180.txt` với guard bật. Run chuẩn bị live cho AG nằm ở
`cache/cm4-valid-tool-choices-preflight-20261116-02`.

Bản `cm4-empty-reopen-v14` giữ assessment và vị trí đọc khi mở lại một
cặp đã đánh giá mà reader không lấy được byte B mới. CM4 hiện ngay danh
sách kết quả của need đang xét để controller chọn ứng viên chưa đọc.
Replay v13 từ trước lượt 12 kiểm truy vấn trùng, mở lại `009152.txt`,
kiểm guard rồi đọc ứng viên khác với các đoạn nguồn thật. Báo cáo nằm ở
`cache/cm4-empty-reopen-replay-20261116-v14-final/report.json`.

Bản `cm4-tool-contract-v13` ràng buộc đoạn trích với ref dẫn nguồn trong
schema và trả phản hồi có giới hạn cho lỗi tham số. Xem
[nghiệm thu hợp đồng tool](TOOL_CONTRACT_FIX.md).

Bản `cm4-pair-navigation-v12` sửa điều hướng khi đọc A và khi quay lại cặp
đã lưu. Xem [nghiệm thu offline](OFFLINE_ACCEPTANCE.md) cho vòng kiểm tra với
corpus thật, replay và các nhánh dừng.

Bản `cm4-review-completion-v11` phân biệt review đầy đủ và dừng sớm. Xem phần
kết quả v10 live và preflight v11 trong `LIVE_SPEAKER_SUPPORT.md`.

Bản `cm4-grounded-speaker-v10` yêu cầu raw ref khi khai speaker đã xác định.
Xem `LIVE_SPEAKER_SUPPORT.md` cho kết quả v9 live và kiểm chứng v10.

Bản `cm4-assessed-progress-v9` điều phối sau assessment accepted và đưa cảnh
báo guard vào payload. Xem `LIVE_ASSESSED_PROGRESS.md` cho replay và lệnh chạy.

Bản `cm4-pending-evidence-feedback-v8` xử lý ghi chú tùy chọn khi assessment
pending. Xem `LIVE_PENDING_FEEDBACK.md` cho lỗi T4 và namespace chạy v8.

Bản `cm4-exact-hybrid-reuse-v7` ghi nhận raw mới ở ranh giới action và dùng lại
kết quả hybrid chính xác trong cùng run. Xem `LIVE_PROGRESS_GUARD.md` cho kết
quả v6 live, replay và namespace chạy v7.

Bản `cm4-assessment-sides-v6` đồng bộ schema với validator cho refs attribution
sau lỗi ở turn 7 của `cache/cm4-compact-preflight-20261115-final`. Xem
`LIVE_ASSESSMENT_SIDES.md` cho kết quả replay và namespace chạy mới.

Bản hiện tại `cm4-compact-context-v5` xử lý `context_unfit` trước turn 8 của
`cache/cm4-hit-first-preflight-20261115-01`. Xem `LIVE_CONTEXT_FIT.md` cho replay,
preflight và lệnh chạy mới.

Bản hiện tại `cm4-hit-first-recovery-v4` đã qua kiểm local sau lượt live 7 turn.
Dùng namespace preflight và lệnh mới trong `LIVE_EVIDENCE_RECOVERY.md`.

Cập nhật sau lượt live đầu tiên: hạ tầng đã chạy nhưng controller lặp search và
bị guard dừng. Bản sửa feedback/routing ở `LIVE_FEEDBACK_FIX.md` có preflight mới;
`CM4_LOCAL_CHECK.md` phía dưới là checkpoint trước lượt live, không phải bằng
chứng hành vi model sau sửa. Giữ run lịch sử nguyên vẹn, không resume bằng code mới.

Authorization hiện hành: người dùng yêu cầu nối inference CM4. Theo AGENTS.md,
Codex chuẩn bị code, kiểm local và lệnh; người dùng hoặc AG chạy Modal. Không
deploy lại, đổi model/GPU/chunk/reranker/fusion/K hoặc mở thêm query ở đợt này.

Query discovery cố định `021095.txt`. Giữ settings uncapped hiện hành ở
`../uncapped_probe/settings.json`: input 8.500/output 512 mỗi lượt, số requests,
actions và embedding dùng sentinel hữu hạn `2**60`, không phải vô hạn toán học.
CM4 mặc định lấy tối đa 50 án mỗi lần tìm hybrid. `--settings` dùng giới hạn
ghi trong file được truyền vào. Kết quả vẫn được trình bày theo từng trang.
Giới hạn dừng vì vòng lặp/không tiến triển và lệnh STOP độc lập với budget này.

## Kế hoạch sửa đổi cách tổng hợp nhãn

Trạng thái: đã triển khai cho CM4 live và đường đối chứng M6 live. Chưa hiệu
chỉnh trên discovery.

- Giữ đánh giá riêng cho mỗi `(source_need_id, candidate_id)`. Mỗi lượt truy hồi
  theo một đoạn neo khác có thể bổ sung một đánh giá cho cùng cặp án truy vấn và
  án ứng viên.
- Tổng hợp ở cấp `(query_id, candidate_id)` theo nhãn có chứng cứ mạnh nhất
  trong các đánh giá còn hiệu lực. Nếu đoạn neo A cho `supported` và đoạn neo B
  cho `similarity_only`, nhãn tổng hợp là `supported`. Giữ tham chiếu tới bản
  đánh giá và các đoạn nguồn làm căn cứ cho nhãn đó.
- Đọc thêm và sửa đánh giá cho cùng đoạn neo vẫn dùng bản mới nhất còn hiệu lực.
  Ví dụ, nếu cùng cặp đoạn neo và ứng viên được sửa từ `supported` thành
  `similarity_only`, bản `supported` cũ không tham gia phép tổng hợp. Đánh giá
  đang chờ chứng cứ hoặc đã bị vô hiệu hóa cũng không được dùng để xác nhận
  `supported`.

Nghiệm thu offline bằng hai tình huống: hai đoạn neo có nhãn khác nhau cho cùng
ứng viên, và một đoạn neo có bản đánh giá được sửa. Quy tắc này tổng hợp nhãn
chứng cứ. Dự đoán cuối vẫn do selector quyết định.

Selector thử nghiệm chỉ chọn `supported` có citation quan sát được ở A và
khớp định danh trong phần đầu B đã đọc. Citation trong thân B không chứng
minh danh tính của B. Citation song song dùng được khi cùng xuất hiện trong
phần định danh của B. Giữ nhãn model và ID assessment riêng với
`selection_assessment_id`. Nếu định danh bị che hoặc chưa đọc đủ, nhãn
tổng hợp có thể là `supported` trong khi selector chưa chọn. Chính sách này
đặt tiêu chuẩn bảo thủ cho lần chạy thử, cần đo cả trường hợp bỏ sót.

## Kế hoạch cổng truy hồi theo mệnh đề

Trạng thái: đã triển khai cho CM4 live; cần nghiệm thu hành vi discovery.

Kiểm tra xem mệnh đề đang xét có dấu hiệu viện dẫn, diễn giải hoặc áp dụng một
án khác. Sự liên quan về chủ đề hoặc ý kiến rằng mệnh đề nên có trích dẫn chưa
đủ căn cứ để mở truy hồi.

1. **Lượt đánh giá.** Payload và schema chỉ cấp công cụ đọc, điều hướng án truy
   vấn và `assess_source_need`. Mọi tool truy hồi và mở ứng viên đều vắng mặt.
   `assess_source_need` chọn `paragraph_ref` do host cấp và ghi người phát
   ngôn nếu xác định được. Nhánh dương chọn thêm `proposition_ref` và
   `signal_ref` từ các câu hoặc mục đang hiển thị. Host lấy nguyên văn theo
   vùng byte đã gắn với mã. Tool này không nhận cụm từ tìm kiếm.
2. **Lượt truy hồi.** Sau khi host chấp nhận `has_source_signal`, payload kế
   tiếp mới có `search_cases_by_issue` với `source_need_ref` do host cấp cho
   đúng mệnh đề. Model lúc này mới đề xuất cụm từ tìm. Sau khi có kết quả, các
   tool xem danh sách, mở đoạn và đánh giá ứng viên phục vụ lượt tìm đã duyệt.
   Muốn tìm theo mệnh đề khác thì trở lại lượt đánh giá.

Khi quyền tìm đang khả dụng, lượt kế tiếp chỉ cấp tìm hoặc hoãn quyền đó có
lý do. Ledger báo riêng quyền đã hoãn và quyền đã thực thi. Có thể mở lại quyền
đã hoãn khi mệnh đề trở lại trong vùng đang đọc. Tín hiệu bác nhánh âm giới hạn
ở citation hoặc lời dẫn nguồn cụ thể. Cụm pháp lý chung chưa đủ để bác. Nếu
host bác nhánh âm, feedback nêu mã vùng có tín hiệu và cho ghi nhận câu hỏi
còn bỏ ngỏ sau khi đọc đủ ngữ cảnh.

| Quyết định | Căn cứ | Hành động của host |
|---|---|---|
| `has_source_signal` | Chọn mã mệnh đề trong đoạn đích và mã dấu hiệu nguồn trong đoạn đó hoặc đoạn lân cận đang hiển thị. Hai mã có thể trùng nhau. | Kiểm hai vùng đã được giao cho model và khớp nguồn. Nếu đạt, cấp quyền tìm ở lượt kế tiếp. Giữ attribution để bước đánh giá ứng viên phân biệt lời tòa, đương sự và nguồn trích. |
| `need_more_context` | Nêu phần thiếu cụ thể, như đầu câu trích, đoạn xác định người nói hoặc phần văn bản bị cắt. | Chỉ cấp lựa chọn đọc phần còn thiếu. Nếu hết ngữ cảnh liên quan mà vẫn mơ hồ, ghi chưa xác định và chuyển vùng. |
| `no_source_signal` | Mệnh đề đang xét kể sự kiện, thủ tục hoặc yêu cầu của đương sự và chưa có tín hiệu án nguồn. | Ghi đã xét mệnh đề và giữ retrieval ẩn cho vùng này. Cho xét lại khi có ngữ cảnh mới liên quan. |

Nhãn dương cần tín hiệu cụ thể. Chủ đề pháp lý chung hoặc một marker
`<FRAGMENT_SUPPRESSED>` đứng riêng chưa đủ. Khi đoạn có cả tường thuật và quy
tắc, xét riêng từng mệnh đề. Host kiểm được provenance và phạm vi nguồn đã đọc.
Chất lượng phân loại ngữ nghĩa của model cần được đo riêng, kể cả khi không có
tên án hay mẫu citation rõ ràng.

- Kiểm quyền trong schema lẫn lúc thực thi, trước backend và trước khi giữ chỗ
  embedding. `choose_query_anchor` chỉ xác nhận vị trí nguồn. Nhánh xác nhận
  bản nháp cũng phải qua cùng kiểm tra quyền trước khi tìm.
- Ledger giữ hash án truy vấn, vùng byte của mệnh đề và dấu hiệu, attribution,
  quyết định và bản đánh giá hiện hành. Đổi mệnh đề hoặc nguồn bị drift phải
  xét lại. Khi resume, dùng trạng thái đã ghi và tránh gửi trùng request.
- Theo dõi tiến độ rà query riêng với tiến độ xét ứng viên. Báo rõ vùng đã xét,
  chưa xác định và chưa đọc. LoopGuard chỉ tính tiến triển một lần cho một vùng
  mới được xét; diễn đạt lại trên cùng nguồn không đặt lại bộ đếm. Xét hết
  ứng viên của một câu neo chỉ hoàn tất câu neo đó.

Nghiệm thu offline: chưa duyệt thì không gọi được retrieval, kể cả xác nhận
bản nháp, dùng quyền của mệnh đề khác và resume. Duyệt hợp lệ mở tool ở lượt
kế tiếp. Đọc thêm có thể chuyển `need_more_context` thành `has_source_signal`.
Sau đó thử trên discovery với cùng top 50 và ngân sách. Dùng các đoạn được
người đọc kiểm tra để đo mở tìm sai và chặn nhầm; báo thêm phạm vi query đã xét,
recall gold trên hợp ứng viên truy hồi, request, token và latency gồm cả lượt
đánh giá. Giữ gold ngoài payload và giữ holdout chưa mở.

## Kế hoạch xử lý các phát hiện review

Trạng thái: đã triển khai đường kỹ thuật. Hai lỗi P1 đã tái hiện offline trước
khi sửa. Kiểm chất lượng ngữ nghĩa và hiệu chỉnh selector trên discovery vẫn
là bước nghiệm thu riêng.

1. **P1 · Đóng hoặc thay thế anchor nháp cùng đợt cổng truy hồi.** Một draft
   đã gác vẫn có thể chặn `complete_policy` sau khi tìm lại bằng câu trích
   đúng và xét hết ứng viên. Thêm cách đóng có lý do `superseded` hoặc
   `discarded`. Lưu lịch sử và liên kết đến bản thay thế nếu có; draft đã đóng
   không chặn hoàn tất và không cấp quyền tìm. Không tự gộp theo văn bản
   `issue`, vì hai đoạn khác nhau có thể dẫn hai nguồn khác nhau. Kiểm offline
   luồng gác câu trích sai → tìm bằng câu đúng → đánh giá hết ứng viên → đóng
   draft cũ → hoàn tất, cùng ca hai draft độc lập có cùng issue.
2. **P2 · Kiểm ngữ nghĩa trước khi bật tổng hợp `max`.** Pilot M5 có ca
   `d13` nhầm A và B cùng dẫn C thành A dẫn B, và ca `d17` bỏ sót hai
   citation song song của cùng một án. M5 chỉ assess context locator và lấy
   nhãn đầu tiên ở cấp cặp. Dùng các ca discovery được đối chiếu nguồn để kiểm
   riêng hướng A→B, danh tính án B, trích dẫn lồng, citation song song và thiếu
   chứng cứ. Giữ `unknown` khi chưa đủ căn cứ. Khi thử `max`, kiểm ca một
   nhãn dương sai có thể chi phối kết quả và ca đánh giá dương đã bị sửa hoặc
   vô hiệu hóa không còn được chọn. Bộ hồ sơ pilot dùng để kiểm loại lỗi.
3. **P1 · Xác minh quyết định của host selector trước khi nghiệm thu prediction.**
   M6 live hiện chưa nối selector hoặc baseline. Replay có selector giả lập
   vẫn thất bại khi assessment còn active nhưng raw A/B không có trong payload
   của lượt finish. Giữ kiểm raw A/B tại thời điểm lập assessment. Trên đường
   host selector, xác nhận ID còn active, mỗi prediction khớp án ứng viên của
   assessment và xác minh hash/phạm vi nguồn theo ledger đã bind. Kiểm offline
   cả ca raw đã rời context nhưng assessment hợp lệ và các ca ID đã bị thay thế,
   nguồn drift hoặc ID thuộc án khác. Khi chưa nối selector, báo
   `pending_selection`; baseline fallback là cấu hình riêng, cần có binding.
4. **P2 · Bind thao tác mở lead của M6 trước khi dùng làm đối chứng.** Registry
   giới hạn preview ở ba lead nhưng có thể ghi đè `open_ref` bằng một hit ngoài
   danh sách hiển thị. Thao tác mở lead phải nhận `lead_ref` gắn đúng candidate,
   need và span/nguồn đã cấp. Tìm theo `focus` vẫn là thao tác riêng. Kiểm replay
   nhiều lần search có hơn ba lead cho cùng B, xác nhận lead đã chọn khớp đoạn
   được mở và handle ngoài payload bị từ chối. CM4 đã có đường mở lead theo ref;
   phát hiện này áp dụng cho M6 dùng làm đối chứng.

Mốc bằng chứng: v23 đã chạy live 11 request controller. Lượt top 50 sau sửa
phân trang mới chỉ có preflight. Hai lỗi P1 được xác nhận bằng replay riêng,
không dùng trạng thái preflight để suy ra lỗi đã xảy ra trong một lượt live.

## Contract inference

1. Host khôi phục ledger và dựng đúng context/focus theo cặp.
2. Compiler chọn cards/raw windows, kiểm provenance và đếm tokenizer pin.
3. Trước khi gửi, lưu manifest/schema/admission của đúng request.
4. Gửi bytes payload cùng **schema hợp nhất của manifest**, bao gồm context tools,
   qua Modal transport hiện hành. Không dịch qua catalog gốc trước khi gửi.
5. Nhận output thật; kiểm JSON/schema và refs của admission đó, lưu provider
   token/latency, transport elapsed và call ID. Output sai schema vẫn lưu usage.
6. Host thực thi tool và lưu result/progress/assessment, rồi dựng lượt tiếp.

Crash sau admission, unknown, output malformed hoặc drift không được tự gửi lại.
Không xóa receipt để resume qua guard. Partial result/usage chưa biết phải giữ
unknown; không báo 0 chi phí vì lượt thất bại hoặc dừng sớm.

## Quan sát và dừng

Log phải cho biết đang compile, đợi controller, thực thi tool hoặc dừng; có
heartbeat/thời gian chờ và call ID khi transport đã nhận ID. Đây là trạng thái
quan sát từ host, không phải suy nghĩ nội bộ của model hoặc bằng chứng GPU đang
thực sự chạy khi call còn queued.

STOP được kiểm tại safe boundary trước request và trước action. Nếu STOP đến
trong lúc đợi provider, nó không bảo đảm hủy tức thì call đang chạy. Không spawn
call thay thế; nếu cần hủy đang chờ, user/AG dùng call ID để xử lý đúng call.

Guard vòng lặp phải bỏ qua revision, request ID và handles thay đổi. Cần phân biệt
raw coverage/ứng viên/assessment mới với đổi trang hoặc đổi wording query. Khi
dừng, lưu lý do, counters và usage đã có; không biến run thiếu evidence thành
thành công hoặc tiết kiệm đã chứng minh.

## Kiểm local và nghiệm thu

Kiểm bằng fake transport/hybrid để xác nhận schema thật, telemetry success/error,
unknown không resend, malformed không execute, STOP boundaries và loop guards.
Preflight chỉ đếm tokenizer/kiểm nguồn, không gọi controller hoặc embedding, không
để admission chưa có receipt làm hỏng lượt chạy sau.

Live success chưa được chứng minh bởi test offline. Sau khi user/AG chạy một query,
review raw trace/events/manifests và usage cả lỗi trước khi mở pilot rộng hơn.
Không đọc gold trong solver; evaluator chỉ mở gold sau freeze theo protocol riêng.

## Lệnh chạy cho user hoặc AG

Từ repo root, tạo namespace mới và chuẩn bị local:

```powershell
$cmRun = 'cache/cm4-live-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir $cmRun
```

Trước khi chạy inference, mở hai terminal từ repo root, dùng cùng Modal profile
và environment với tiến trình CM4. Chạy một lệnh theo dõi trong mỗi terminal:

```powershell
& .venv/Scripts/python.exe -m modal app logs coliee-qwen36-27b-fp8-l40s -f --timestamps --show-function-call-id --show-container-id
& .venv/Scripts/python.exe -m modal app logs coliee-pipeline-v2-embed-m3-opt-v2 -f --timestamps --show-function-call-id --show-container-id
```

Dùng timestamp và call ID để đối chiếu với stderr và trace CM4. Chỉ xác nhận
chờ GPU khi Modal hiển thị trạng thái hoặc log tương ứng. Dòng `pending` hoặc
`awaiting result` chỉ cho biết host chưa nhận kết quả. Nếu cần tra riêng một
controller call, dùng `modal app logs <app> --function-call <fc-id> --timestamps`.

Chạy inference ở terminal đã prepare, giữ tiến trình chạy qua các lần poll:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir $cmRun
```

Để AG yêu cầu dừng tại safe boundary, từ cửa sổ khác dùng đúng `$cmRun`:

```powershell
New-Item -ItemType File -Path (Join-Path $cmRun 'STOP') -Force
```

STOP được xử lý tại safe boundary. CM4 poll cùng controller call mỗi 30 giây
và chờ không giới hạn tổng thời gian ở host. Query embedding dùng Modal
`remote()`, cũng chờ kết quả không có deadline tổng ở host. Hai đường gọi tiếp
tục chờ khi Modal chưa trả kết quả. Modal vẫn có thể trả lỗi thực thi hoặc
startup từ deployment, và run ghi nhận lỗi đó. Nếu trạng thái call cũ còn
unknown, kiểm tra trên Modal trước khi cân nhắc run khác.

Các lựa chọn được khóa trong `plan.json` lúc prepare:

- `--no-progress-limit 6`: dừng sau chuỗi 6 actions không thay đổi evidence,
  ứng viên hoặc assessment có ý nghĩa.
- `--cycle-limit 3`: dừng khi cùng trạng thái context xuất hiện 3 lần mà không
  có tiến triển thực; bỏ qua handles/revision/need wording và lý do tự do.
- `--max-turns N`: cap controller tùy chọn; mặc định không thêm cap nhỏ mới.

LoopGuard là heuristic đã kiểm trên lặp trang/chu kỳ và raw mới, không bảo đảm
phát hiện mọi vòng lặp về ngữ nghĩa. AG vẫn có quyền dừng. Không đổi options
bằng cách sửa plan; khi đổi cấu hình hoặc code, prepare namespace mới.

Artifacts cần review:

- `preview.json`, `plan.json`: preflight và bindings, không có inference admission.
- `trace.jsonl`: compile/controller wait/action đang chạy, heartbeat, guard warning
  và lý do dừng. Trace có call ID khi controller đã nhận ID.
- `session/events.sqlite3`, `session/manifests/`: payload/schema/receipt thật,
  raw reply, token/latency, actions/results/context và coverage.
- `embedding_events.sqlite3`, `retrieval_diagnostics/`: embedding/search receipts
  và kết quả retrieval có provenance khi có search thực.
- `result.json`: tổng hợp trạng thái cuối và usage provider/unknown, không thay
  thế ledger. Nếu process bị kill, ledger còn admission/action chưa hoàn tất;
  đường khôi phục phải giữ unknown, không tự chạy lại.

## Kết quả local trước lần chạy thật

30 tests PASS, 0 skip; reviewer độc lập cũng chạy 30 tests PASS và báo 0 lỗi chặn
cho gate code/local. Có schema context thật, provider usage success/malformed/
unknown, telemetry vượt admission, output Unicode lỗi/duplicate JSON keys,
STOP trước/sau reply, crash không resend, pending action resume, loop navigation.
Probe độc lập xác nhận raw mới không bị guard dừng nhầm trong kịch bản đã kiểm.

Preflight cuối: `cache/cm4-preflight-20261115-final`, chạy với guard cấm
`ModalQwenTransport.send_structured` và `HybridSearch.search`. Xem kết quả kiểm
bindings/requests trong `CM4_LOCAL_CHECK.md`. Không gọi Modal/deploy thật.
Preflight không phải kiểm GPU/provider availability hoặc nghiệm thu inference
schema trên vLLM; các điều đó phải được quan sát trong lượt chạy thật.
