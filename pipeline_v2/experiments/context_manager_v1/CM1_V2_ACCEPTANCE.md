# Nghiệm thu checkpoint CM0–CM1 v2 — 15/11/2026

Main chấp nhận checkpoint **engineering offline CM0–CM1 v2** sau review AG:
0 finding chặn trong phạm vi sửa. Đủ điều kiện kỹ thuật để giao CM2 khi người
dùng yêu cầu; **không tự mở CM2, CM3 hoặc inference/deploy**.

AG báo 19/19 tests PASS, 0 skip (1,845 giây), cùng independent edge checks.
Main không chạy lại tests chỉ để tăng số kiểm, đã đối chiếu evidence thực:

| Report AG | SHA-256 |
|---|---|
| `cache/cm1-v2-ag-20261115-074723710-replay/report.json` | `62068b4a7702ce448575e31cb755514462c00fb2b5a916be3adc5e6abfbeac37` |
| `cache/cm1-v2-ag-20261115-074723710-stress/report.json` | `cc99ccd6e784dc8ab832e8a0cabb3a2467378f98c5192396a5f01a1fe7b46683` |

Code bindings khớp source hiện tại; hashes artifacts nguồn vẫn khớp. Replay giữ
3 candidates/1 need, raw-preserved/resume-equal/source-unchanged, view 1.272 và
2.198 tokens. Controller/embedding/retrieval requests mới đều bằng 0. Đây là view
context offline, không phải prompt inference M6 đầy đủ.

Ba nhóm sửa đã qua AG: schema/card/host cùng eligibility; previous theo đúng
trang thực sau shrink/resume; tách need-context/list delivery và bảo toàn unknown.

Ghi nhận không chặn: schema minLength không loại mọi chuỗi whitespace/1 từ,
host vẫn từ chối theo semantics. Chưa thêm pattern: deployment trước đây có giới
hạn chuyển regex JSON Schema sang grammar. Nếu thay schema phải kiểm tương thích
decoder riêng, không đổi để làm mất guard host hoặc thêm lượt retry tự động.

Giới hạn còn giữ: 500/10.000 candidates mới kiểm first page; chưa benchmark
full traversal/host CPU-RAM dài hạn, bias hoặc model quality. Pin/park/reload,
callback tool thật, continuation và assessment integration thuộc CM2–CM3.
Nghiệm thu này không chứng nhận correctness pháp lý, recall hoặc final F1.
