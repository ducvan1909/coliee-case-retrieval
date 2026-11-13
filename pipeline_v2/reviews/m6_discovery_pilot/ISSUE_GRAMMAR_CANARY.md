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
