# CM2–CM3 — checkpoint AG đã nghiệm thu offline

Ngày 15/11/2026. Main nhận báo cáo review độc lập do người dùng chuyển lại,
đối chiếu artifact local và chốt **engineering offline CM2–CM3: PASS**,
**0 finding chặn** trong phạm vi này. Không cấp phép CM4 hoặc inference/deploy.

## Evidence độc lập

- 15/15 tests CM2–CM3 PASS, 0 skip; 19/19 regression CM1 PASS, 0 skip.
- Replay AG: `cache/cm23-ag-replay-20261115-093151026/report.json`.
  11 scripted turns, peak 7.814 input tokens, PASS. Park giữ assessment;
  resume bằng nhau; source artifacts không đổi; 0 inference/embedding mới.
- Stress AG: `cache/cm23-ag-stress-20261115-093151026/report.json`.
  Pool 3/50 duyệt đầy đủ; 500/10.000 chỉ trang đầu. Peak tương ứng
  3.797 / 4.404 / 4.326 / 4.331. Giữ đủ canonical pool.
- AG kiểm bổ sung no-hit boundary: stage `no_hit` và vẫn có đường search/stop.
- SHA-256 replay:
  `c4956b4fb67880c7bbf63db3879dc55fb2e25bff8c65950d25693d3e6b0bfe32`.
- SHA-256 stress:
  `6e2646dc1056c2737de1d5328d871f90f013b5f60064e677d56ab9a63df51398`.

Main đã kiểm hai hash trên và toàn bộ runtime bindings trong manifests AG
khớp code hiện tại. Không chạy lại inference hoặc chỉnh artifact AG.

## Ghi nhận không chặn offline, phải rà soát trước CM4

1. `completed_roots` hiện dùng chung trong context; route sang root khác dùng
   offset đầu record. Nếu nhiều pair chia sẻ A roots hoặc chuyển root giữa chừng,
   quay lại có thể đọc lặp phần đã đọc. Cần tách progress theo pair/root và giữ
   offset dở dang; kiểm cả thứ tự root không tuần tự và pair chia sẻ A.
2. Resume pair có thể giữ `missing_reason` của pair trước. Cần gắn reason đúng
   pair hoặc xóa khi đổi focus; khi đang reading, trang parked chưa hiện pairs
   do policy chưa cho đổi cặp. Cần làm trạng thái này rõ cho model.

Chưa sửa runtime tại checkpoint nghiệm thu này; thay đổi tiếp cần namespace và
bindings mới, không sửa báo cáo lịch sử để coi là kết quả của code mới.

## Giới hạn và điểm dừng

Một raw window mỗi phía A/B; attribution/quote-chain nhiều đoạn còn có thể
pending/unknown. Action và assessment replay giả lập, không chứng minh model
chọn đúng, legal correctness, recall/F1 hay bias. Prompt bounded không bảo đảm
host CPU/RAM bounded. **Dừng trước CM4**; nếu mở CM4, chuẩn bị khắc phục hai
ghi nhận trên và kế hoạch một-query có giám sát/dừng riêng theo scope được giao.
