# CM4 v5 — thu gọn metadata trong payload

Run `cache/cm4-hit-first-preflight-20261115-01` đã đọc đúng đoạn B khớp lead và
dùng `read_more_context` sau assessment pending. Sau search thứ hai và lượt mở
B tiếp theo, compiler dừng trước admission lượt 8 với `context_unfit`. Ledger
ghi 7 lượt controller với 47.992 input và 807 output tokens, cùng 2 lượt
embedding với 97 input tokens. Replay prefix qua event 29 tái hiện lỗi offline.

Bản v4 co số card và độ dài raw, trong khi registry vẫn đưa cursor, tham số
truy nguồn và metadata lặp vào prompt. Bản v5 thu gọn phần model thấy trước
khi phải giảm raw. Manifest lưu đầy đủ registry để host giải mã action và ledger
giữ raw record cùng provenance. Mã lựa chọn và schema vẫn chứa các lựa chọn
điều hướng đã cấp. Prompt giữ raw, refs, spans, thông tin attribution và mô tả
choices. Phép đếm token và lượt gửi dùng cùng JSON đã lưu với hash trong manifest.

| Prefix replay từ ledger live | Kết quả local |
|---|---|
| Event 17, trước lượt 5 | 6.810 input tokens. Giữ A `[0,512]` và B `[1255,1859]`. `read_more_context` giả lập dispatch thành công. |
| Event 29, trước lượt 8 | 7.246 input tokens. Giữ A `[1024,2048]` và B `[17937,18961]`. Assessment giả lập đi qua validator. |

Replay kiểm hash nguồn trước và sau, đếm bằng tokenizer pin và chặn provider.
Artifacts lần lượt ở `cache/cm4-compact-pending-20261115-final` và
`cache/cm4-compact-prefix-20261115-final`. Suite thử nghiệm PASS 36/36. Probe
review độc lập cũng xác nhận resume rồi dispatch đúng cursor từ manifest với
schema, raw spans và attribution giữ đúng. Registry vẫn có thể tăng theo lịch
sử. Evidence hiện xác nhận hai prefix này và chưa định lượng các run dài hơn.

Preflight mới `cache/cm4-compact-preflight-20261115-final` đạt 5.424 input tokens
và 0 request admissions. Người dùng hoặc AG chạy từ repo root theo AGENTS.md.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-compact-preflight-20261115-final
```

Kết quả inference của bản v5 vẫn chờ lượt live. STOP nằm trong thư mục run.
