# CM4 v8 — feedback khi assessment thiếu evidence

Lượt live `cache/cm4-guard-reuse-preflight-20261115-final` dừng trong T4 với
`TypeError`. Ledger có 4 controller receipts, 4 action starts, 3 action
results. T4 còn active và file `result.json` chưa được ghi. Usage đến lúc
dừng là 26.600 input, 499 output tokens và một embedding request 46 input
tokens. Trace ghi lỗi tại `execute_action` sau 1.377,588 giây của run.

Model chọn speaker phía A nhưng thiếu `speaker_evidence_refs` và bỏ qua ghi chú
tùy chọn `missing_evidence`. Validator M4 trả `pending_evidence` với mã
`speaker_evidence_refs` và `reported_missing_evidence=None`. Làm mới feedback
đã cố duyệt `None` như một danh sách trước khi ghi được kết quả vào ledger.

Bản `cm4-pending-evidence-feedback-v8` xử lý giá trị null như chưa có ghi chú.
Mã lý do của validator tiếp tục được hiển thị cho model và assessment giữ
`pending_evidence`. Kiểm thử regression đi qua validator và bước dựng payload
kế tiếp với đúng trường hợp model bỏ qua ghi chú. Lượt v7 bị crash trước khi
đến các kịch bản guard và search reuse. Kết quả live của hai cơ chế đó còn mở.

Replay offline từ event 13 dùng lại chính JSON phản hồi T4 từ ledger. Payload
assessment 7.725 input tokens, kết quả ghi được `pending_evidence`. Preview
lượt kế tiếp 7.131/8.500 token, gồm `validation_missing_codes` là
`speaker_evidence_refs` và `reported_missing_evidence` là danh sách rỗng.
Hai lần dựng payload và action replay phát sinh 0 request controller hoặc
embedding. Hashes của run nguồn khớp trước và sau. Report nằm tại
`cache/cm4-pending-feedback-replay-20261115-01/report.json`.

Suite offline PASS 42/42. Preflight đạt 5.426 input tokens, 0 request admissions
và code binding khớp bản cuối. Từ repo root, user hoặc AG chạy phiên mới.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-pending-feedback-preflight-20261115-01
```
