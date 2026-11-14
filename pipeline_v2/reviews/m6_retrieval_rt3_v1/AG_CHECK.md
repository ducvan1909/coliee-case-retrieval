# AG kiểm RT3 — bản đồ cấu trúc A phân cấp

Lưu ý bàn giao Git: người dùng không yêu cầu chuyển các run/receipts/inventory thử nghiệm cũ. Các tham chiếu lịch sử bên dưới có thể chỉ tồn tại ở máy nguồn; không phải dependency để chạy probe mới. Dùng hướng dẫn `docs/RETRIEVAL_HANDOFF_20261114.md` và profile ctx8500 cho công việc tiếp quản; `local_settings.json` ở đây giữ regression cap 7.400.

Ngày 14/11/2026. Bắt đầu sau nghiệm thu RT2 tại `reviews/m6_retrieval_rt2_v1/main_acceptance.json`. Chỉ kiểm engineering/navigation, không triển khai RT4/RT5 hoặc gọi inference.

## Phạm vi

Profile mới opt-in `query_navigation.mode=hierarchical`. Cây nguồn phủ toàn raw A, có heading/snippets literal kèm spans/hash; model được mở rộng bản đồ hoặc đọc raw ở bất kỳ cấp nào, quay về cha/gốc, chuyển vùng và đọc continuation. Không xử lý ngữ nghĩa trước, không trích citation mới bằng regex, không đổi K/caps/model/selector. Profile không bật tùy chọn giữ navigation cũ.

## Kiểm local

```powershell
Set-Location E:\Git\coliee-case-retrieval
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m6_query_navigation pipeline_v2.tests.test_m6_paragraph_anchor pipeline_v2.tests.test_m6_adaptive pipeline_v2.tests.test_m6_live -v
```

Review độc lập: phủ heading/gap/đuôi nguồn; không mất phần giữa/cuối; giant paragraph và UTF-8 không làm split rỗng hoặc recursion không kết thúc; refs bind nguồn/config và stateless resume; preview không thành evidence; mỗi trang và final payload có giới hạn; trạng thái đã fetch khác với model đã nhận. Mở cùng map nhiều lần không được tự tạo progress vô hạn.

Review cuối bắt buộc chú ý ba sửa sau khi reviewer subagent bị giới hạn sử dụng: ưu tiên giữ continuation khi trim expansions, không xử lý reload refs như dictionary context, và giữ hierarchical read routes trong đường fit cặp A/B. Kiểm trên bản có hashes khớp `local_verification.json`. Tập test M6 toàn bộ Main đạt 73 (1 skip); AG có thể chạy toàn tập nếu muốn xác nhận final regression. Một skip là thiếu ledger lịch sử, không phải PASS ngầm.

Đặc biệt kiểm bản đồ có nội dung literal cho từng vùng con. Chỉ vừa cap nhưng snippets/heading bị lược hết không đủ để nghiệm thu. Renderer phải giữ ít nhất một trích đoạn literal cho mỗi lựa chọn vùng hoặc báo unfit; sparse heading thật của M2 nằm trong trường `headings`, không chỉ navigation rows. Nếu trạng thái dùng defaults cấp trang để gọn token, đọc defaults kết hợp với status riêng của từng nút; không hiểu status vắng mặt là đã đọc.

## Prepare payload thật với 0 inference

Cần corpus/sparse/navigation đã seal và tokenizer controller pin. Không cần Qdrant cho settings lexical này.

```powershell
$rt3Prepare = 'cache/m6-retrieval-rt3-ag-prepare-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.m6_live prepare --settings pipeline_v2/reviews/m6_retrieval_rt3_v1/local_settings.json --run-dir $rt3Prepare
if ($LASTEXITCODE -ne 0) { throw 'RT3 prepare loi; giu run/log' }
Get-Content "$rt3Prepare/plan.json"
Get-Content "$rt3Prepare/first_payload.json"
```

Kiểm `preflight_status=ready`, số token thật không quá 7.400, payload có tool/refs mở rộng và đọc vùng, tổng các vùng cấp gốc phủ source byte range. Map không bị biến thành raw evidence. Không chạy `m6_live run` trên profile này: prepare là gate kỹ thuật, chưa phải profile live đã hiệu chỉnh.

## Kiểm corpus và luồng điều hướng giả lập

```powershell
$rt3Probe = 'cache/m6-retrieval-rt3-ag-probe-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m6_retrieval_rt3_v1.check_navigation_corpus --run-dir $rt3Probe
if ($LASTEXITCODE -ne 0) { throw 'RT3 corpus/navigation probe loi; giu report va log' }
Get-Content "$rt3Probe/report.json"
```

Probe duyệt cây ba nguồn discovery, kiểm mọi vùng lá phân hoạch toàn raw source và từng trang giữ text literal/offset/hash trong map token cap; kiểm heading literal thật khi có. Sau đó controller giả lập thực hiện tám lượt mở rộng → đọc raw → continuation → về cha → vùng khác → đọc raw → về gốc → dừng. Kiểm final payload bằng tokenizer thật, raw coverage sau receipt và resume không gọi thêm.

Probe có 0 controller/embedding/retrieval requests thật, không cần Qdrant. Phải ghi rõ hành động scripted, không diễn giải thành model chọn vùng tốt hoặc recall tăng. Lưu cùng run `report.json`, `first_payload.json`, thư mục `navigation/` (ledger) và kiểm code/tokenizer fingerprints với bản đang review.

Main đã chạy bản cuối PASS 159 trang trên ba án và luồng 8 bước cộng đọc root trực tiếp. Peak payload 7.398/7.400 rất sát trần; AG cần đối chiếu lại và giữ mọi fail/unfit nếu môi trường/profile khác, không tự tăng cap. Run Main và cả các lần lỗi trước đó được liệt kê trong `local_verification.json`.

## Trả evidence và dừng

Trả tests/stdout/stderr/exit code, run prepare và corpus probe, payload/report, code/tokenizer fingerprints. Giữ lỗi/unfit và namespace riêng, không sửa seal/hash hoặc tăng cap để làm PASS. Main đối chiếu evidence trước khi mở RT4; AG không sửa production hoặc chạy Modal/deploy.
