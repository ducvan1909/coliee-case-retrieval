# CM4 Q1–Q4 — báo cáo triển khai local

Ngày 19/11/2026. Base `7c230e5`. Trạng thái: **Q1–Q4 đạt kiểm local; chưa nghiệm thu live/semantic**.

Người dùng đã yêu cầu triển khai toàn bộ kế hoạch `docs/plan/CM4_QUERY_REVIEW_PLAN_20261119.md`. Quyền chạy Modal không thay đổi: Codex sửa code/kiểm local, người dùng hoặc AG chạy inference/deploy.

## Phạm vi

- Q1: khóa một search query đến khi explicit conclusion; giữ tập hits và phần chưa giải quyết.
- Q2: survey toàn bộ cards trước đọc sâu B, priority và các counters tách delivery/raw/assessment.
- Q3: source gate theo nhu cầu nguồn, signal tùy chọn, tìm trên span partial và coverage vùng đã screening.
- Q4: warn-only mặc định cho chống lặp, tùy chọn stop; giữ STOP, provenance và accounting provider unknown.

Engine mới `cm4-query-review-v24`, live CLI `cm4-live-v2`. Cần namespace mới; không resume plan v23 bằng code này. Giữ model/tokenizer/chunk/index/RRF và caps mỗi lượt 8500/512. Không có inference/deploy trong đợt triển khai local.

## Kiểm tra đã chạy

| Lệnh | Kết quả |
|---|---|
| `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/tests -p 'test_m6*.py' -q` | 77 tests, OK, skipped=1, 17.291s |
| `.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_source_selection pipeline_v2.tests.test_m6_hybrid -q` | 14 tests, OK, 1.471s |
| `.venv/Scripts/python.exe -m unittest discover -s pipeline_v2/experiments/context_manager_v2/tests -p 'test_*.py' -q` | Bản code cuối: 122 tests, OK, 0 skip, 74.053s, Main chạy |
| `live --help` | Có `--loop-guard-mode {warn,stop}` |
| `git -c core.whitespace=cr-at-eol diff --check` | PASS; checkout có file CRLF, không coi CR ở cuối dòng là whitespace lỗi |

Nhóm replay V15 không có ledger cũ ở checkout nên skip. Fixture tạo harness bằng `__new__` đã được bổ sung `explicit_leads` từ config, mặc định false; không diễn giải đây là đã chạy lại 6 lỗi lịch sử trên ledger không có. Không cần mang run cũ để prepare run mới.

10 acceptance tests mới ở `tests/test_query_review_acceptance.py` nằm trong suite 122: 50 hits bắt survey đủ trước raw/conclusion, resume/query kế tiếp, receipt-only delivery, partial không citation, query trùng, active assessment IDs và unknown unresolved, warn mode, token fitting 5→2 cards, ghép raw qua hai cửa sổ nhận thành công và chặn vùng thiếu delivery.

Tester_advanced đã chạy các probe độc lập trong thư mục tạm: survey 50/10 trang và immutable order/resume; chỉ đếm cards thật sau fit; không leak raw B cũ vào survey query mới; đổi B khi cặp trước chưa assessed; warn mode qua ngưỡng kể cả resume; STOP trong reply không execute action tiếp; lặp input rejection ở warn vẫn mở run và không execute tool sai. Review bắt và sửa: `uniqueItems` không tương thích decoder, nhầm active assessment ID thành dict, unknown bị tính resolved và query duplicate thiếu phản hồi kết luận cũ. Tester chạm giới hạn sử dụng trước full suite cuối, nên Main trực tiếp review phần cuối và chạy 122 tests; không khẳng định tester đã kiểm độc lập toàn bộ revision cuối.

Main kiểm bổ sung schema survey/review 50 hits không có `pattern`/`uniqueItems`; zero-hit vẫn phải explicit conclusion. Các probes dùng fixture/provider giả lập, không có request Modal thật.

## Fresh prepare trên nguồn thật

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.experiments.context_manager_v2.live prepare --run-dir cache/cm4-query-review-v24-final-20261119-210550317 --loop-guard-mode warn
```

Exit 0, `preflight_ready`, input **2.286 tokens**, elapsed **209.771s**, controller requests **0**, embedding requests **0**. Plan/preview và trace ở cache local không bắt buộc chuyển máy. Đối chiếu `plan.code_binding == live.binding()` sau khi code cuối ổn định: **True**. Options: warn, max_turns null, wait_seconds null; input cap 8500/output 512, search limit 50, cumulative uncapped. Đây là kiểm local nguồn/index/tokenizer/payload, không kiểm deployment/provider.

Một prepare trước đó cũng ready 2.286 tokens nhưng code thay đổi để thêm ghép span; đã bị supersede, không dùng namespace đó chạy thật. Không sửa plan hoặc evidence cũ để khớp code mới.

## Contract đã triển khai và giới hạn cụ thể

- `prioritize_query_results`, `conclude_search_query`, `revisit_source_need`, `read_query_span` được cấp theo đúng state. Query giống hoàn toàn sau conclusion trả lại kết luận cũ, không tạo backend request hoặc survey lại.
- Unknown/passage unresolved vẫn unresolved dù assessment được chấp nhận về protocol. Kết luận partial giữ IDs/counters phần còn tồn; không đổi án chưa đọc thành nhãn âm.
- Source gate giữ aliases cũ cho tests/replay; prompt mới dùng nhu cầu nguồn. `signal_ref` không bắt buộc, span partial không bị khóa bởi full paragraph. Screening coverage theo vùng, không mặc định positive một mệnh đề đã phủ toàn paragraph.
- `read_query_span` chỉ ghép vùng liên tục đã giao của cùng paragraph/hash, tối đa 4 options/8192 bytes, kiểm projected payload fit 8500 trước khi cấp. Không hỗ trợ mệnh đề dài tùy ý vượt context; phải chọn mệnh đề nhỏ đủ ý hoặc giữ unresolved.
- Loop warn không tự stop vì cycle/no-progress/repeated semantic tool rejection; stop mode vẫn có khi chọn rõ. Schema/source drift/provider failure/unknown vẫn giữ đường xử lý kỹ thuật và receipt, không execute action sai.
- Case-level completion còn theo coverage/pending policy; query partial không chứng minh toàn A hay toàn corpus đã hoàn tất. Chưa thay selector bằng một semantic oracle.

## Hạn chế và bước chạy thật

Local fixtures và schema/provenance PASS không chứng minh model biết ưu tiên kết quả, query tốt hoặc quan hệ A→B đúng gold. Survey exposure chỉ là có cơ hội thấy nội dung. Query conclusion partial không phải phủ hết raw. Warn-only đòi AG theo dõi và dừng nếu mất kiểm soát.

Lệnh và checklist giao AG ở [AG_CHECK.md](AG_CHECK.md). Không tự gửi lại unknown admission; giữ usage cả lỗi/retry và latency biết được/unknown riêng. Chưa mở holdout hay báo recall/F1.
