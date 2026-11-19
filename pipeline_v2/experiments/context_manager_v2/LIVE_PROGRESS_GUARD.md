# CM4 — ghi nhận raw mới tại ranh giới action

Lượt live `cache/cm4-side-contract-preflight-20261115-01` xác nhận schema phía
A/B hoạt động trên Modal. Cả 16 controller responses qua schema, 0 action
assessment bị từ chối. Payload cao nhất 7.859/8.500 token. T5 và T9 dùng speaker
phía A với refs đúng phía. Các assessment là nhãn do model suy luận. Kết quả
cuối ở `pending_selection`, cả 7 lượt assessment tập trung vào `012856.txt`.

Usage ghi 112.804 input, 2.489 output tokens, 16 controller requests và 2
embedding requests với 94 input tokens. Wall-clock 1.556,747 giây theo trace.

T12 và T15 trả 0 đoạn raw mới. T16 khác: ở event 65, reader thêm A
`[2565,2792]` vào catalog có provenance. Guard cũ chỉ so coverage model đã
nhận, trong khi đoạn mới chưa vào payload kế tiếp. Tái dựng event 65 với guard
cũ cho `stop=true`, `cycles=3`, `no_progress=2`. Guard sửa mới so coverage raw
đã fetch và raw đã giao riêng. Coverage hợp nhất theo case, source hash và
byte span, nên cùng bytes có ref khác vẫn được tính một lần. Trên cùng ledger,
T12 và T15 vẫn cảnh báo lặp, còn T16 cho `stop=false`, `cycles=1`, `no_progress=0`.

T2 và T7 sử dụng cùng query text với hai A anchors khác nhau. Need vẫn cần giữ
riêng theo bằng chứng A. Các lựa chọn chỉ quay về đoạn đã biết và việc model
chưa chọn hai ứng viên khác là quan sát hành vi riêng của lượt này.

V7 dùng lại kết quả hybrid đã commit trong cùng ledger khi query text, channel,
limit, snapshot và receipt M3 khớp. Action ghi kết quả theo need hiện tại và gắn
ID của search nguồn. Embedder và journal giữ số lần thực thi thật. Nếu model
chỉ diễn đạt lại `source_proposition` của cùng need, ledger giữ chú thích
canonical đầu tiên. Câu chữ mới vẫn có trong raw response và action được xử lý
như duplicate.

Replay event 65 dựng được payload T17 ở 6.578/8.500 token, chứa A `[2565,2792]`
và B `[12438,13462]`. Đoạn A mới nằm ngoài anchor của need đang làm nên preview
chưa cấp assessment cho cặp đó. Model có thể đọc thêm hoặc chọn hướng khác từ
schema hiện tại. Đây là lượt compile offline, với 0 request model mới.

Replay T7 từ event 25 dùng lại đúng action T2, giữ ba hit `012856.txt`,
`090399.txt`, `042319.txt` theo thứ tự gốc và giữ hai need ID riêng. Cửa sổ
kết quả tiếp theo đạt 6.068 token. Replay chặn hybrid backend và kiểm journal
embedding không có dòng mới. Report tại `cache/cm4-search-reuse-replay-20261115-final`.

Preflight mới đạt 5.435 token và 0 admission. Người dùng hoặc AG có thể chạy từ
repo root theo AGENTS.md.

Suite thử nghiệm cuối PASS 41/41. Kiểm độc lập đối chiếu lại ba ranh giới T12,
T15 và T16, xử lý lời chú thích đổi trên cùng need và điều kiện reuse dựa trên
ledger gốc. Các bài kiểm tra được thực hiện offline.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live run --run-dir cache/cm4-guard-reuse-preflight-20261115-final
```

Hành vi model trên v7 còn chờ live. Việc model chỉ đánh giá một ứng viên vẫn
chưa được giải quyết bởi hai sửa đổi trên.
