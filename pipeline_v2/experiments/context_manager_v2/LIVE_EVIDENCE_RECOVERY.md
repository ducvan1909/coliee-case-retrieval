# CM4 v4 — ưu tiên đoạn khớp và đọc tiếp khi thiếu evidence

Lượt live `cache/cm4-feedback-preflight-20261115-final` đã qua search, đọc B và
nộp assessment `pending_evidence`. Guard dừng ở turn 7 vì `semantic_context_cycle`.
Usage của lượt này là 49.186 input, 818 output, 7 controller requests và một
embedding request 37 input tokens theo ledger và báo cáo AG. Prediction vẫn
`pending_selection`. Lượt chạy tốn khoảng 996 giây.

Tool đọc `012856.txt` đã fetch cả đoạn lân cận `[410,830]` và lead được yêu cầu
`[1255,1859]` theo `hit_refs`. Compiler chọn đoạn lân cận lên trước. Lead đúng
vẫn đợi trong `cm_unoffered_raw` và có đường đọc tiếp. Sau assessment, model báo
cần xem các đoạn sau của A để xác định có viện dẫn B hay không. Payload chỉ hiện
mã `reported_missing_evidence`, làm mất chi tiết cần đọc phía nào. Model chọn mở
lại B, assessment lại trên đoạn cũ rồi lặp search và bị guard dừng. Schema lúc đó
vẫn có tool đọc tiếp, nên log không cho thấy model bị buộc phải assessment.

`cm4-hit-first-recovery-v4` chọn root của đoạn khớp ở lượt mở B đầu tiên theo
`hit_refs` của reader và passage ID đã yêu cầu. Khi thiếu `hit_refs` thích hợp,
engine dò lead thuộc đúng need hiện tại. Bộ đọc và provenance vẫn cung cấp các
đoạn lân cận, compiler giữ chúng để tiếp tục qua handle. Lựa chọn root chỉ áp
dụng cho thứ tự đưa raw vào prompt. Thứ hạng ứng viên và các tham số retrieval
giữ theo lượt search đã thực thi.

Khi `missing_evidence`, feedback giữ tối đa ba yêu cầu model báo, mỗi yêu cầu
tối đa 240 ký tự, và hiện mã validator riêng. Model nhận các lựa chọn đọc A/B
và chuyển trang với args hợp lệ trong schema hiện tại. Engine ẩn thao tác mở lại
cùng B đã mở khi cặp còn raw chờ. Model vẫn có thể tiếp tục hoặc mở rộng raw,
chủ động reload, duyệt ứng viên/need khác hoặc dừng. Tìm một need mới vẫn được
phép ở boundary đã báo thiếu và host tiếp tục chặn exact duplicate.

Suite local PASS 36/36. Hai regression mới kiểm ưu tiên lead, khả năng đọc tiếp
neighbor, tính hợp lệ của các lựa chọn trong feedback và việc ẩn mở lại B khi
raw còn chờ. Test mở vùng B mới hiện xác nhận đã nhận cửa sổ trước khi mở tiếp.

Replay `cache/cm4-hit-first-replay-20261115-01/report.json` dùng kết quả search
đã lưu của lượt 7 turn với reader và tokenizer thật. PASS 13 lượt giả lập,
peak 8.332/8.500 token. Payload assessment đầu tiên chứa B `[1255,1859]` và A
`[0,512]`. B `[410,830]` nằm trong danh sách raw còn chờ. Hashes của run nguồn
khớp trước/sau. Replay có 0 lượt inference và embedding mới.

Preflight `cache/cm4-hit-first-preflight-20261115-01` PASS với 5.420 token,
0 request admissions và runtime binding khớp code. Từ repo root, người dùng
hoặc AG có thể chạy namespace này theo phân công trong AGENTS.md.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-hit-first-preflight-20261115-01
```

STOP đặt tại thư mục run. Hành vi model sau sửa vẫn chờ lượt live này.
Review độc lập mới xác nhận nguyên nhân trên artifact lịch sử trước khi hết
hạn mức. Bản v4 được Main kiểm bằng suite và replay local ở trên.
