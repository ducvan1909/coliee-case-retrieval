# Bàn giao Modal mới và pilot v27 bị ngắt tại embedding

Ngày 20/11/2026. Nguồn: báo cáo AG và ledger local. Không có inference/deploy mới trong lần đối chiếu Main.

## Trạng thái đã có evidence

- AG deploy controller và embedding trên profile `g38180254`. Controller pin trong code hiện là `fu-TfWPSIRNQIkZWM1W5O7HEv`; endpoint canary thứ hai PASS, embedding endpoint check PASS theo receipts AG. Không diễn giải endpoint PASS thành bảo đảm mọi request sau đều được cấp worker.
- Controller deploy bằng file path từng lỗi `ModuleNotFoundError: No module named 'app'`. Lệnh module mode AG dùng thành công:

```powershell
& .venv/Scripts/python.exe -m modal deploy -m pipeline_v2.deployments.modal_qwen36_27b.app
```

Đây là lệnh để người dùng/AG thực hiện khi thực sự cần redeploy, không phải yêu cầu deploy lại ngay. Giữ function-ID guard; hydrate deployment đích và cập nhật pin có căn cứ khi ID đổi. Không lưu credentials vào repo.

- Pilot mới `cache/cm4-query-review-v27-ag-20261119-233422075`: Main đối chiếu **16 events**, **4 admissions**, event cuối `action_started(search_corpus)`, không `result.json`.
- Runtime embedding `pipeline_v2/artifacts/m3_full_search_runtime_v1/ac941b59f092456089a9aef8f9ce21a5/ledger.sqlite3`: một attempt **started**, chưa có receipt hoàn tất. 36 tokens là reserved/admitted, chưa chứng minh số thực thi phía remote.
- Theo AG: controller pilot 23.047 input / 397 output, 4 replies; provider latency 51.259,714 ms, transport elapsed 61.209,408 ms. Canary thứ nhất timeout có usage unknown, canary thứ hai 30/7 tokens, endpoint embedding check 35 input tokens, probe chẩn đoán là request riêng. Không gộp hoặc bỏ usage failed/probe.

## Diễn giải và việc tiếp theo

**Chỉ đạo mới của người dùng ngày 20/11: chờ cấp GPU vô hạn.** Khi Modal đang pending/chưa cấp worker, AG giữ request/client gốc và giám sát read-only đến khi có kết quả, không kill/STOP/cancel/redeploy chỉ vì thời gian chờ dài, không phát probe/inference mới để kiểm hàng đợi. Pending scheduler không phải vòng lặp của model. Chỉ dừng nếu người dùng yêu cầu hoặc có terminal error thật; giữ usage unknown tới khi có receipt. Với call cũ còn pending, tiếp tục theo dõi, không chủ động hủy để retry. Xem quy định đầy đủ tại mục 4 của [AG_CHECK](../cm4_query_review_v24/AG_CHECK.md).

1. V27 **chưa được nghiệm thu live về survey/focus**: run chưa nhận hits, chưa dùng next-unseen/priority, chưa đọc B. Không sửa prompt/model/GPU hoặc kết luận v27 thất bại từ lượt bị chặn ngoài này.
2. `PENDING`, không task/container và thời gian chờ dài cho thấy chưa có evidence worker chạy request. Chưa đủ để phân biệt capacity, quota/giới hạn tài khoản hoặc nguyên nhân scheduler khác; AG kiểm thông báo/log/workspace trước khi chốt root cause. Endpoint check trước đó PASS chỉ xác nhận endpoint đã chạy được tại thời điểm check.
3. Kill client không tự chứng minh call server đã được hủy. Báo cáo mới chỉ nêu rõ cancellation cho probe `fc-01M7TCYV4GWYY3NYDREAN145MA`; không có bằng chứng tương đương cho embedding gốc. **Không tự gửi query/probe mới hoặc retry pilot** trước khi xác định trạng thái request gốc, hoặc ghi rõ không thể xác định và để người dùng quyết định.
4. AG cần tìm request/call gốc từ app/input logs, đối chiếu runtime request ID; kiểm đã success/error/cancel hay vẫn pending. Nếu vẫn pending thì tiếp tục chờ vô hạn theo chỉ đạo mới; chỉ hủy khi người dùng yêu cầu rõ ràng, ghi call ID, kết quả hủy và usage biết được/unknown. Không sửa historical `started` thành success/cancel nếu thiếu receipt; không xóa ledger để retry.
5. Khi request cũ đã được xử lý và workspace có thể chạy embedding, dùng **fresh namespace v27** theo AG_CHECK. Không resume session đang dangling action bằng cách bỏ guard. Không cần embed lại corpus hoặc dựng lại Qdrant; giữ 8500/512, top50, uncapped và model/revision hiện hành.

Nút thắt observability: embedding hiện dùng synchronous `.remote()` và local ledger không lưu durable call ID gốc trước khi chờ. Đây là hạn chế cần xem xét riêng cho recovery/cancel; không suy call ID của probe thành call gốc. Chưa thay transport trong đợt đối chiếu này.
