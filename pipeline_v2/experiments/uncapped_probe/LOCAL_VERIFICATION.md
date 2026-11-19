# Kiểm local ngày 14/11/2026

## Checkpoint sửa payload thứ ba, policy v4 / runner v2

Tái dựng read-only từ events 1–9 của
`cache/m6-uncapped-021095-20261114-200422096`: run lịch sử có đúng **2 request đã
admission** và dừng ở event 10 với `payload_token_cap`; request thứ ba chưa gửi.

Nguyên nhân đã tái hiện: metadata model-facing lặp dài (key lựa chọn, source need
giống nhau ở ba candidate, các enum ref lặp trong tool parameters). Payload nhỏ
nhất ở bản chưa sửa là **9.009 token**, kể cả khi không giao raw excerpt. Đây là
lỗi đóng gói request mới, không phải đã dùng hết ngân sách do request trước có
8.295 token. Baseline dưới version text hiện tại là **9.013 token**; chênh 4 token
đến từ version marker, không phải thay nguồn/kết quả tìm.

Kết quả cuối: `cache/payload3-replay-final-20261114-v1/report.json`:

- Baseline vẫn `unfit`, 9.013/8.500; payload đã compact **ready, 7.399/8.500**.
- Giữ ba lựa chọn án `012856.txt`, `042319.txt`, `090399.txt`, map/read routes và
  nguồn/hash/offset/literal. Toàn bộ source need vẫn hiện trong bảng dùng chung.
- Model action giả lập đọc lead có sẵn của `012856.txt` qua source reader local:
  payload kế tiếp **8.285/8.500**, raw A `021095.txt:[0,927]` và B
  `012856.txt:[410,830]`, có một pair và tool `assess_case_link`.
- **Một phần nguồn vẫn pending**, không báo đã đọc đủ B. Đây là local scripted
  delivery/packing check, không phải đánh giá quan hệ pháp lý của model.
- 0 controller inference, 0 embedding, 0 retrieval. Source/index/tools/tokenizer
  bindings khớp lịch sử. SHA-256 mọi file run lịch sử trước/sau không đổi.

Các lượt thử trung gian giữ nguyên: baseline, ordinal alias, stable alias và
shared-needs-only. Hai bản alias/shared-needs-only làm vừa request thứ ba nhưng
chưa ghép A/B được. Enum prompt view v4 mới đạt cả hai kiểm trên. Một replay
shared-needs-v1 lỗi helper chưa hydrate need trước dry-read; đã sửa, không tạo
provider call hoặc thay evidence lịch sử.

Code/schema binding đã đổi: các prepare cũ bên dưới là checkpoint lịch sử và
không được resume bằng code mới. Phải prepare namespace mới trước lần live tiếp.
Bản sửa chỉ nằm trong thư mục thử nghiệm, chưa chạy lại inference/deploy.

## Checkpoint ban đầu trước bản sửa payload

Phạm vi: bộ thử nghiệm riêng, query `021095.txt`, RT4 và hai profile uncapped/RT5.
Không chạy inference/deploy, chưa nghiệm thu context live hoặc retrieval recall.

- `python -m unittest discover -s pipeline_v2/experiments/uncapped_probe/tests -p 'test_*.py' -q`: **16 tests PASS** qua `.venv/Scripts/python.exe`.
- Test giữ `source_proposition` trong ledger nhưng chỉ gửi `issue` làm query; schema production không nhận trường thử nghiệm.
- Test STOP trước request/sau response, không thực thi action đang chờ; interrupted request giữ unknown và recovery không gửi lại.
- Test uncapped vượt 8 controller/actions và 5 embedding; profile RT5 kiểm riêng request cap 5 và token cap 2.240.
- Reviewer độc lập chạy luồng giả lập 12 request/11 action, STOP trước action thứ 12; không có lỗi chặn còn xác nhận.

Prepare trên corpus thật với tokenizer pin:

| Profile | Run local | Kết quả | Input payload đầu | Inference |
|---|---|---|---:|---:|
| Uncapped + RT4 | `cache/uncapped-rt45-local-preflight-20261114-v2` | ready | 5.792 / 8.500 | 0 |
| RT5 + RT4 | `cache/rt5-local-preflight-20261114-v1` | ready | 5.741 / 8.500 | 0 |

Đã đối chiếu code bindings của cả hai plan với source cuối, đều khớp. Có thể dùng
hai run này theo thứ tự hướng dẫn README nếu source/bindings vẫn khớp; runner sẽ
từ chối drift. Không tự chạy hai profile nối tiếp hoặc đồng thời.

Lỗi prepare đầu tại `cache/uncapped-rt45-local-preflight-20261114-v1` được giữ nguyên:
`Trace.emit` trùng tên tham số `kind` với event ledger. Đã sửa và có regression test;
lượt lỗi có 0 inference. Không tái dùng run lỗi để sửa evidence thành PASS.

Task này chỉ thêm file dưới `pipeline_v2/experiments/uncapped_probe/`. Diff tracked
`agent_harness/evidence.py` một dòng tồn tại trước task, được giữ nguyên.

Giới hạn: sentinel `2**60` là giới hạn hữu hạn rất lớn; per-request context/output,
per-input embedding, source/schema, duplicate/recovery và giới hạn service vẫn có
hiệu lực. STOP tác dụng ở ranh giới an toàn; Ctrl+C không chứng minh remote đã hủy.
Canary context cũ vẫn unknown theo bàn giao, không được resend. Freeze/score chỉ
thực hiện sau run terminal; lỗi/unknown không được xóa khỏi denominator. Kết quả
một query không thay nghiệm thu RT3/context/RT4 live hay đánh giá COLIEE cuối.
