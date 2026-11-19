# Sửa feedback sau lượt CM4 live đầu tiên

Run lịch sử: `cache/cm4-live-20261115-103308159`. Không sửa run, snapshot hoặc
receipt lịch sử; không gọi inference/deploy mới ở đợt sửa này.

## Chẩn đoán từ payload và ledger thật

Hạ tầng controller/embedding/hybrid đã trả kết quả. Run dừng bởi guard sau
5 controller requests: 28.577 input, 422 output, 0 retries/unknown receipts.
Provider latency controller tổng 71.154,06 ms; transport elapsed 393.639,08 ms;
tool elapsed 348.348,10 ms. Embedding 1 request, 37 input tokens theo báo cáo AG.
Không mở raw B hoặc tạo assessment; prediction vẫn pending_selection. Không coi
exit 0/guard stop là hoàn thành bài toán hoặc là tiết kiệm đã chứng minh.

Ledger có 22 events, gồm final run_stopped. Tìm được 012856 / 020605 / 025361
theo rank 1 / 2 / 3. Controller lặp cùng search, M4 từ chối duplicate không gọi
retrieval thêm, rồi guard dừng semantic_context_cycle.

Các lỗi được xác nhận:

1. Không đưa outcome action gần nhất và duplicate rejection vào payload mới.
2. Search duplicate có observation không chứa hits nhưng bị đổi thành `no_hit`.
   Đây không phải search thật trả rỗng; làm sai focus stage.
3. Chưa giữ boundary search→results→read B hoặc ghi thiếu trước search mới.
4. Candidate map được serialize theo hash key: thứ tự trình bày 2/3/1 dù rank
   trong leads còn đúng. Cần danh sách có thứ tự tường minh.

Payload cũ **đã có** candidate_count=3, 3 candidate cards, search_completed=true
và read_case_passages. Không kết luận model hoàn toàn không thấy kết quả, hoặc
temperature=0/tool đầu danh sách là nguyên nhân đã chứng minh. Đây chỉ là các
giả thuyết hành vi; chưa thay sampling/model hay fusion vì chúng.

## Bản sửa `cm4-feedback-v3`

- `last_action_feedback`: action model/canonical, status/reason, search có thật
  sự executed không, hit count; search thành công gần nhất với tối đa 5 hits theo
  native order; next tools và missing reason đúng current pair khi có.
- Full observation tiếp tục không đưa nguyên khối vào prompt; trường
  `observation_scope` nói rõ bounded feedback đã được đưa vào, không giả history
  đầy đủ. Feedback không biến preview thành raw evidence.
- Duplicate giữ need/candidate/stage; chỉ successful executed search trả hits=[]
  mới là no_hit. Pending assessment vẫn chuyển missing_evidence đúng contract.
- Search có hits → results_ready: có thể đọc bất kỳ B hợp lệ, xem trang, kết thúc
  hoặc ghi rõ thiếu evidence. Search mới chỉ mở lại sau boundary hợp lệ. Không ép
  đọc rank 1 hoặc ép round-robin, không đổi K/fusion/selector.
- `cm_page.candidates` là ordered list, có candidate_ref, case_id, original_rank,
  read_allowed khớp schema. Map refs vẫn dùng cho dispatch; danh sách không rerank.
- CLI replay đọc cả ledger cũ ở root và CM4 ở session/, giữ source identity và
  exact recorded diagnostic/query binding. Kịch bản dùng next page khi fitting
  thu nhỏ trang; không giả định mọi hit nằm trang đầu.

## Kiểm local

Main suite: **34/34 PASS**, 0 skip, 16,985 giây. Reviewer độc lập: 4/4 feedback
tests PASS, 0 skip, 5,296 giây; các probe từ prefix run thật xác nhận feedback
647–776 bytes, thứ tự 1/2/3, duplicate không executed và giữ hits. Preview marker
không thành evidence, chưa đọc B thì không có assessment tool. 0 lỗi chặn xác nhận
cho bản sửa feedback/routing.

Lượt suite ban đầu có 3 assertion lỗi do fixture mặc định lexical_both trả hai
kênh: raw hit count gấp đôi số unique cases. Fixture cuối cố định case_bm25 cho
regression này; không sửa fusion/retrieval production để làm test PASS.

Replay đầu `cache/cm4-feedback-replay-20261115-01` đi qua đọc B/assessment nhưng
script chọn C chưa hiện trên trang bị StopIteration. Giữ artifact lỗi, không
resend vào namespace đó; sửa script dùng pagination thực. Không phải inference
hoặc bằng chứng model đã đi tiếp.

Replay cuối: `cache/cm4-feedback-replay-20261115-final-v2/report.json`, **PASS**,
13 scripted turns, peak **7.885 input tokens**, 35,968 giây. Dùng đúng query,
diagnostic và kết quả retrieval của run live vừa lỗi; reader nguồn thật,
0 inference/embedding/retrieval mới. Đi qua search→read B→assessment→page→read C→
missing→parked page→resume B→reload. Hash toàn bộ source run trước/sau bằng nhau;
runtime bindings mọi manifests khớp code cuối. Metadata feedback trước read B
báo search executed=true, hit_count=3, rank 1/2/3, reader hợp lệ và không cấp
search mới ở results_ready. Kịch bản chọn action vẫn là giả lập.

Namespace replay `cache/cm4-feedback-replay-20261115-final` (không v2) còn lỗi
script tương tự ở parked page: B không nằm trang đầu vì page fitting; giữ lại,
script cuối đã duyệt next page cho cả candidates và parked pairs.

SHA-256 replay report:
`b13c42cc4e4d386b05b4eb02f9df41862d9c18b9f7af79a1c97ceb082a383a7e`.
SHA-256 historical events (không đổi):
`e26545e33477dd8d72f918b6b11ac8ca281d028a544c9b126e9047040cc6a64c`.
SHA-256 historical result (không đổi):
`d6f5879d2107a716b2858362662c8e0c4f287543512c9d1349fe625660413abd`.

Preflight mới `cache/cm4-feedback-preflight-20261115-final`: exit 0,
**5.430 tokens**, 0 request admissions. Chạy với guard cấm Modal send và hybrid
search. Plan bindings khớp code cuối. Plan SHA-256:
`5eea9f1d8d13bdebb388ab6da3d13b29c13d7f34bd7569554f97162c13bd310e`.

Lệnh user/AG chạy thử một-query mới, từ repo root:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-feedback-preflight-20261115-final
```

Đây là lệnh có thể gọi provider thật. STOP tại
`cache/cm4-feedback-preflight-20261115-final/STOP`; vẫn là safe boundary,
không hủy ngay call đang chờ. Không resume run 5-turn cũ bằng code mới.

## Giới hạn

Các lựa chọn replay là giả lập. Sửa feedback và schema gate không chứng minh model
sẽ đọc đúng B hay cải thiện COLIEE. LoopGuard vẫn bật, giữ usage các run lỗi; cần
một lượt live mới do user/AG chạy để kiểm hành vi. Không mở thêm query/pilot.
