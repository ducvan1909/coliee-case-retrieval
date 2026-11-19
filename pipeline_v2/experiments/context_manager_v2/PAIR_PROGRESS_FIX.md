# Sửa progress và missing reason trước CM4

Ngày 15/11/2026, theo yêu cầu người dùng. Chỉ sửa runtime thử nghiệm
`engine.py`, regression `tests/test_engine.py` và tài liệu. Không đổi production,
không chạy inference/deploy, không sửa checkpoint/run cũ.

## Thay đổi

- Version mới `cm23-offline-v2-pair-progress`; run namespace mới bắt buộc.
- `pair_progress[fingerprint([need_id, candidate_id])]` chứa `window_offsets`,
  `next_offsets`, `active_roots`, `completed_roots`, và missing reason của cặp.
  A root dùng chung giữa các cặp vẫn có tiến độ độc lập.
- Window hiện tại giữ cho assessment; next offset tăng tại successful action
  commit. Rời root giữa chừng rồi quay lại dùng next offset, không quay về đầu.
- Resume giữ tiến độ; explicit `reload_pair_evidence` reset riêng cặp được chọn.
  Root đã hoàn tất, kể cả A anchor ngắn hơn canonical source record, không bị
  resume sang offset nằm ngoài requested span.
- Active `missing_reason` chỉ xuất hiện ở đúng cặp và stage missing_evidence;
  đổi/search/read/resume không mang reason của cặp trước sang. Reason lịch sử
  còn trong ledger/pair state; chưa tự được đưa vào registry model.

## Kiểm bản cuối

- Implementer: 19/19 unit tests PASS, 0 skip (38,249 giây).
- Reviewer độc lập: 19/19 PASS, 0 skip (12,213 giây), 0 lỗi chặn cho hai sửa này.
  Probe độc lập xác nhận early-switch giữa roots quay lại offset 2048, missing
  B→C→resume B không rò reason, unknown không tiến progress, partial A vẫn [0,100]
  sau restart dù canonical record dài hơn.
- Main replay: `cache/cm23-pair-progress-replay-20261115-01/report.json`, PASS,
  11 scripted turns, peak 7.819 input tokens, 65,140 giây. Giữ assessment khi
  park, resume bằng nhau, source hash trước/sau không đổi. Toàn bộ runtime code
  bindings của manifests khớp code cuối.
- Main stress: `cache/cm23-pair-progress-stress-20261115-01/report.json`, PASS;
  3/50 duyệt đầy đủ; 500/10.000 kiểm trang đầu. Peak 3.797/4.404/4.326/4.331.
- Tất cả lệnh dùng `.venv/Scripts/python.exe`; 0 controller inference, 0 embedding,
  0 corpus retrieval mới. Local raw reads và recorded-search replay được giữ riêng.

Engine SHA-256:
`8a0411e4cdef00691094b153754acdd181a7b06ed0cb4f357b9c96706cf846b7`.
Replay report SHA-256:
`7025c86487b87ae5a17be9988c1b444a1235b22586cfefb8dcdbbc30810fe503`.
Stress report SHA-256:
`2de05a4b0d60ececcc85dd54f5c158b5905c98ee529d1455e8ba99f5e441735c`.

## Điểm dừng

Hai ghi nhận tại `CM23_ACCEPTANCE.md` đã được sửa theo evidence trên; checkpoint
nghiệm thu cũ vẫn mô tả code cũ, không sửa lịch sử thành kết quả của version mới.
Luồng model/context/tools ở `MODEL_CONTEXT_FLOW.md`. Chưa mở CM4. Một raw window
mỗi phía, semantic quality, bias và giám sát live vẫn là giới hạn/gate riêng.
