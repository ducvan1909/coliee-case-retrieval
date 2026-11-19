# CM2–CM3: triển khai và kiểm offline

**Sau CM4 live đầu tiên:** run 5-turn đã xác minh đường provider/hybrid nhưng
chưa đọc B, bị guard dừng vì lặp search. Đã sửa bounded feedback, duplicate/no-hit,
ordered cards và results_ready routing. Xem `LIVE_FEEDBACK_FIX.md`: 34 tests PASS,
replay đúng dữ liệu live PASS 13 lượt/7.885 peak tokens, preflight mới 5.430 tokens.
Chưa chạy inference mới để nghiệm thu hành vi model sau sửa.

**CM4 đã nối code:** xem `CM4.md` và `CM4_LOCAL_CHECK.md`: 30 tests PASS,
preflight cuối 5.375 tokens, 0 request thật, code/local review không có lỗi chặn.
Chỉ user/AG chạy lệnh live; chưa có kết quả inference CM4 thật.

**Bản sửa mới sau AG:** hai ghi nhận progress/missing reason đã sửa ở version
`cm23-offline-v2-pair-progress`; 19 tests PASS cùng replay/stress mới. Evidence
ở `PAIR_PROGRESS_FIX.md`; luồng model/context/tools ở `MODEL_CONTEXT_FLOW.md`.
Các kết quả 15 tests và hashes phía dưới thuộc checkpoint trước sửa.

**Cập nhật sau review AG:** CM2–CM3 đã được nghiệm thu engineering offline,
0 finding chặn. Xem `CM23_ACCEPTANCE.md` để biết evidence AG, hashes đã đối chiếu,
hai ghi nhận không chặn và điểm dừng trước CM4. Các đoạn “chờ AG” bên dưới
ghi lại checkpoint Main trước khi nhận review, không phải trạng thái mới nhất.

Phạm vi: bộ thử nghiệm riêng; không đổi entry point chạy thật. Tái dùng ledger,
source tools và assessment validator M4. Không chạy inference/embedding/Modal.
CM4 chưa được triển khai hoặc chạy ở đợt này.

## Cơ chế

- Raw canonical được kiểm source hash, byte span, UTF-8, text hash và provenance;
  cửa sổ context không phải tóm tắt. Canonical root và cửa sổ được phân biệt.
- Pin/park theo need–candidate; assessment vẫn nằm trong ledger khi raw không
  còn trong prompt. Reload đưa đúng raw trở lại trước khi validator đánh giá.
- Catalog nguồn/assessment hiện hành được ghép với các lệnh xem trang, đổi focus,
  báo thiếu evidence, tiếp tục raw và quay lại cặp đã park. Host và schema giới
  hạn theo state; đang đọc một cặp phải assessment hoặc ghi thiếu trước khi đổi.
- Admission/receipt/action/result được ghi bền vững. Unknown, crash và phản hồi
  sai không tự gửi lại. Mỗi payload có manifest/schema/code/tokenizer binding.
- Token cap 8.500 input, 512 output; mục tiêu mềm 7.900. Khi cần, giảm số cards
  trước rồi giảm raw window; coverage partial và mã đoạn phải phản ánh đúng raw.

## Evidence phát triển

Các namespace `cache/cm23-main-replay-20261115-01` đến `-04` được giữ nguyên.
Chúng là các lượt dò tích hợp chưa PASS: thiếu phương thức của recorded adapter,
chọn nhầm vùng query trong script, mã đoạn lịch sử không hợp lệ sau windowing,
và script quay lại chưa đi qua trang parked. Không coi các lượt này là inference
hoặc kết quả thành công. Các receipt token/provider usage để unknown; không
chuyển thành chi phí provider bằng 0. Số lần gọi provider thực trong thí nghiệm
offline là 0 theo đường thực thi và guard cấm gọi.

Review độc lập cũng tìm lỗi mất đường quay lại cặp cũ và phần đuôi của raw gồm
nhiều records. Các tình huống này phải có regression trước khi chốt bản cuối.

## Kết quả bản cuối

Checkpoint ngày 15/11/2026: **triển khai và kiểm local PASS; chờ AG review cuối**.

- `-m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -q`:
  **15 tests PASS**, 0 skip, 8,644 giây. Có regression 7 parked pairs qua trang
  5→2, continuation đa root kết thúc không lặp, exact anchor, UTF-8/provenance,
  M4 accepted unknown và pending attribution, drift, tamper, malformed, unknown.
- Regression CM1: `-m unittest discover -s pipeline_v2/experiments/context_manager_v1/tests -q`:
  **19 tests PASS**, 0 skip, 1,683 giây. Cả hai dùng `.venv/Scripts/python.exe`.
- Replay cuối: `cache/cm23-main-replay-20261115-final-v2/report.json`, **PASS**,
  11 scripted turns, peak **7.808 input tokens**, 34,241 giây. Có 1 query-read,
  1 recorded search, 2 candidate source reads, 1 assessment qua validator thật,
  missing-evidence, page/park/resume/reload và stop. Không coi context commands
  thành source reads. Giữ 1 active assessment qua park; resume state bằng nhau.
  Hash mọi file trong historical source run trước/sau bằng nhau. Toàn bộ manifest
  của replay có runtime code binding khớp code cuối khi Main đối chiếu.
- Reload cuối: A `021095.txt` **[0,512]**, B `012856.txt` **[410,830]**. A chỉ là
  phần đầu của paragraph gốc [0,927]; không chứng nhận đã đọc đầy đủ paragraph.
  Kịch bản chọn mã paragraph partial hiện hành; query retrieval giữ nguyên text,
  nhưng source need được tạo mới từ raw đang có, không giả bằng need cũ.
- Stress cuối: `cache/cm23-main-stress-20261115-final-v2/report.json`, **PASS**,
  tokenizer pin thật, catalog tích hợp đầy đủ, candidates synthetic. Pool 3/50
  duyệt đầy đủ (1/10 trang); pool 500/10.000 chỉ kiểm trang đầu. Kho giữ đủ toàn bộ
  candidates; mỗi trang tối đa 5 cards. Peak lần lượt **3.797/4.404/4.326/4.331**.
- **0 controller inference, 0 embedding và 0 corpus retrieval mới**. Recorded
  search replay 1 lần, đã kiểm diagnostic hash và liên kết operation/controller.
  Source reads local là thật. Token admission là phép đếm prompt; provider token,
  latency và cost không được suy ra từ các receipt scripted.

SHA-256 report replay:
`441e2032e64ffb066ca7f536eda18beefcbbafc17f9a8c97f373854db965b5f5`.
SHA-256 report stress:
`534b9326e4f5606725e34acde873b71c9d0f657e69b2573e29bce1aa36794d26`.

Hai agent triển khai/review bị hết hạn mức trước khi gửi kết luận review cuối.
Main tiếp tục kiểm bản cuối, chạy suite và đối chiếu manifests. Reviewer độc lập
đã tái hiện các lỗi rồi xác nhận multi-root hết vòng lặp; sửa cuối cho parked
pagination được regression 7 pairs kiểm PASS, nhưng chưa có kết luận AG độc lập
trên toàn bản cuối. Không ghi review này thành AG approved.

Namespace `*-final` không hậu tố v2 là checkpoint PASS trước sửa cuối schema
parked pagination; giữ nguyên, không dùng thay báo cáo `*-final-v2` phía trên.

## Giới hạn

PASS engineering offline không chứng minh model tự chọn đúng tool, dùng hết
pagination, giảm bias, hoặc cải thiện recall/F1. Assessment trong replay là nhãn
giả lập/unknown, không phải gold. Stress prompt không chứng minh host CPU/RAM
bounded. AG review độc lập là gate tiếp theo; dừng trước CM4.

Hiện mỗi payload chỉ giữ một raw window cho mỗi phía A/B. Chưa ghép nhiều đoạn
attribution/quote/container rời nhau vào cùng payload; khi validator cần thêm refs
thì pending/unknown vẫn phải được giữ. Đã kiểm bảo toàn provenance và pending,
chưa nghiệm thu mọi trường hợp legal attribution nhiều đoạn. Chưa chạy so sánh
nhiều thứ tự bằng model hoặc nghiên cứu bias; không coi native rank là trung lập.
