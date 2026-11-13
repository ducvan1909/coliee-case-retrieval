# Canary XGrammar cho trường issue

Schema thử nghiệm bỏ riêng `pattern: "\\S"` khỏi `issue`, giữ kiểu string và giới hạn 4–160 ký tự. Prompt, model, tên tool, handle, và kiểm tra sau trim tại host giữ nguyên. Đây là phép thử riêng cho issue. Các trường khác dùng schema riêng và chưa được kiểm bởi canary này.

[Issue XGrammar #895](https://github.com/mlc-ai/xgrammar/issues/895) báo việc bỏ qua giới hạn độ dài khi có pattern. [PR #896](https://github.com/mlc-ai/xgrammar/pull/896) bổ sung cảnh báo. Giả thuyết cho v11 là grammar từ pattern một ký tự chỉ cho phép một ký tự trong chuỗi JSON. Xác minh trên runtime trước khi diễn giải hành vi model.

AG lấy ID container phục vụ app Qwen đang chạy bằng `modal container list`. Chạy matcher ngay trong container đó, lưu stdout và ID container. Probe kiểm chuỗi hoàn chỉnh ở mức grammar, ghi phiên bản XGrammar và vLLM, không load model hoặc phát sinh inference.

```powershell
$pilot = 'pipeline_v2/reviews/m6_discovery_pilot'
$probe = Get-Content -Raw "$pilot/probe_issue_grammar.py"
$encodedProbe = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($probe))
$remoteCode = "import base64; exec(compile(base64.b64decode('$encodedProbe'), 'probe_issue_grammar.py', 'exec'))"
# Đặt $container thành ID thật của container app đang phục vụ.
& .venv/Scripts/modal.exe container exec --no-pty $container python -c $remoteCode
```

Nếu không còn container sống, có thể chạy script trong bản sao **cùng image digest** và ghi rõ đây là kiểm cùng image, chưa xác minh process live. Nếu probe lỗi, lưu lỗi và phiên bản thay vì diễn giải như grammar đã từ chối chuỗi.

| Schema | Kết quả ủng hộ giả thuyết với `w` | Với `standard of review` |
|---|---|---|
| Cũ | Nhận | Từ chối |
| Bỏ pattern | Từ chối | Nhận |

Sau khi đọc kết quả matcher, AG chạy một án `017984.txt` trong namespace riêng đã chuẩn bị:

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir "$pilot/runs_v12/017984.txt"
```

Đọc `request_result.m6_reply.raw_action` và so với `action_started.action.args.text` nếu search đã được thực thi. Nếu cụm hợp lệ và bám đoạn A, xem kết quả hybrid. Nếu cụm hợp lệ nhưng lạc đề, giữ log để đánh giá hướng dẫn tạo truy vấn riêng. Nếu còn một ký tự, xác minh backend và schema đã nhận, rồi thử văn bản tự do trên cùng đoạn A bằng một phép thử riêng. Endpoint hiện tại yêu cầu schema, nên lượt văn bản tự do cần đường canary riêng nếu tới bước đó.

## Kết quả AG ngày 13/11

Sandbox cùng image digest báo vLLM 0.19.1 và XGrammar 0.1.33. Matcher cũ nhận `w` và từ chối `standard of review`. Bỏ pattern đảo kết quả đúng như dự kiến. Đây là phép thử grammar cùng image, không phải kiểm trực tiếp bên trong process đang phục vụ.

Lượt live v12 trên `017984.txt` sinh `retroactive application of immigration regulations` với handle `p000003`. Ledger xác nhận schema qua kiểm tra và action giữ nguyên cụm tìm. Controller dùng 4.945 input, 54 output token và 0 retry. Embedding thành công với 39 input token và khoảng 49,59 giây RPC. Hybrid dừng với `HTTPError` sau đó. [Ledger v12](runs_v12/017984.txt/events.sqlite3) · [Report v12](runs_v12/017984.txt/report_1794542392001352600.json)

Ledger v12 không có HTTP status, endpoint hay thông báo server, nên chưa thể xác nhận Qdrant timeout. Nếu AG có quyền đọc Docker logs, trước tiên đối chiếu cửa sổ `2026-11-13T03:55:57Z` đến `2026-11-13T03:59:53Z` để tìm lỗi cùng thời điểm. Có thể dùng lệnh dưới từ repo root. Giữ kết quả trong thư mục chẩn đoán mới.

```powershell
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml logs --since 2026-11-13T03:55:57Z --until 2026-11-13T03:59:53Z
```

Khi cần tái hiện live, dùng run mới đã chuẩn bị cho cùng một query. Ledger `embedding_events.sqlite3` và report sẽ ghi `http_status`, `http_endpoint` và `http_timeout_reported` khi có phản hồi HTTP lỗi. Giữ cả receipt embedding và thời gian search. Chỉ chạy hai query còn lại sau khi query đầu trả được kết quả tìm.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir "$pilot/runs_v13/017984.txt"
```

## Kết quả v13 và phép kiểm Qdrant tiếp theo

V13 xác nhận Qdrant trả HTTP 500 có báo timeout tại `points/query` trong dense exact search. Một request controller và một embedding đã thành công. Embedding dùng 39 input token và 21,38 giây RPC. Toàn action hybrid mất 178,33 giây, gồm cả embedding và các bước khác ngoài truy vấn Qdrant. Hybrid không trả ứng viên. [Report v13](runs_v13/017984.txt/report_1794544536684265700.json)

Kiểm riêng dense exact bằng vector cache trước khi mở lại pilot. Lệnh sau chạy truy vấn hẹp và truy vấn toàn corpus, lưu HTTP status, thông báo lỗi và thời gian từng probe. Không gọi controller hoặc embedding. Nếu chuyển sang Linux hoặc OCI CPU, khôi phục cùng collection rồi chạy lại đối chứng để so thời gian với máy hiện tại.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m3_completion_v1.diagnose_dense_timeout
```

Khi exact search qua ổn định, chuẩn bị namespace mới và chạy lại một query M6 để kiểm bước mở nguồn và assessment.

## Chạy lại với timeout 240 giây

Lượt v15 dùng cùng query và ngân sách M6 như v13. Riêng truy vấn dense exact của M6 dùng timeout Qdrant 240 giây và HTTP client 255 giây. M3 giữ nguyên binding của sparse artifact. Preflight v14 đã dừng trước khi gọi model vì thay timeout trực tiếp trong M3 làm lệch binding. AG chạy riêng query đầu trong v15 và giữ cả usage lẫn receipt HTTP nếu lỗi.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir "pipeline_v2/reviews/m6_discovery_pilot/runs_v15/017984.txt"
```
