# Sửa payload kế tiếp sau lượt tìm đầu — 14/11/2026

Run nguồn: `cache/m6-uncapped-021095-20261114-200422096`.
Ledger chỉ có hai request controller; request thứ ba chưa được gửi vì host dừng
`budget / payload_token_cap`. Lượt embedding đã hoàn tất, không gây lần dừng này.

Nguyên nhân: phần registry/tool metadata vượt ngân sách, ngay cả khi bỏ raw excerpts.
Bản trước sửa nhỏ nhất đạt 9.009 token; baseline tái dựng trên phiên bản cuối là
9.013 do nhãn phiên bản khác. Các trần tổng embedding/action đã được gỡ trong
profile, nhưng trần input mỗi request 8.500 vẫn có hiệu lực độc lập.

Sửa hoàn toàn trong bộ thử nghiệm:

- `policy.py`: alias lựa chọn ổn định có kiểm collision; shared table lưu các need
  giống hệt nhau một lần, hydrate lại canonical bindings khi host xử lý action.
- Bản prompt của tool chỉ dẫn tới bảng lựa chọn thay vì lặp enum dài. Decoder và
  host vẫn dùng schema đầy đủ; không bỏ source hashes, offsets hoặc raw refs.
- `runner.py`: phiên bản/binding mới; `replay_payload.py`: tái dựng read-only,
  có tùy chọn mở source lead local bằng action giả lập rồi kiểm payload A/B.

Kết quả trong `cache/payload3-replay-final-20261114-v1/report.json`:

| Bước | Input token | Kết quả |
|---|---:|---|
| Payload thứ ba | 7.399 / 8.500 | Đủ 3 lựa chọn ứng viên và đường điều hướng |
| Sau khi giả lập mở ứng viên | 8.285 / 8.500 | Raw A/B, 1 pair và tool assessment |

Raw A là `021095.txt [0,927]` (927 byte); raw B là
`012856.txt [410,830]` (420 byte, 404 ký tự). Cả hai khớp nguyên văn UTF-8,
source hash, text hash và raw refs. Một phần nguồn còn pending được giữ rõ.

Kiểm thử độc lập bản cuối: **25/25 PASS, 0 skip, 55,419 giây**:

```powershell
& .venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/uncapped_probe/tests -p 'test_*.py' -q
```

Có kiểm refs cũ/tamper/dangling, schema enum đầy đủ, round-trip bindings, map/read
routes, tokenizer thật, STOP và recovery. Replay dùng **0 controller inference,
0 embedding, 0 retrieval request**; bước mở B chỉ đọc source local. Mọi file run
nguồn giữ nguyên SHA-256; code binding của report khớp source cuối.

Đây là nghiệm thu sửa đóng gói cho trạng thái đã ghi và một bước đọc giả lập,
chưa chứng minh chất lượng model/recall hay mọi kích thước pool tương lai đều vừa.
Không sửa code chính, không tăng cap hoặc đổi K/fusion. Muốn chạy live bản mới
phải prepare namespace mới; không sửa/resume terminal run lịch sử.
