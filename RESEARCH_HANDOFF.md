# Tiếp tục nghiên cứu trên máy khác

## Trạng thái nghiên cứu được bàn giao

Hướng hiện hành là authoring AU theo legal point gần KOS, gom rule–rationale–exception và giữ attribution. Chưa thiết kế lại reranker hoặc quyết định nối NN–AU qua Issue.

K0 v2 trên cùng nguồn cũ đã kết thúc thực thi: 3 request, 6.421 input + 81 output = 6.502 token provider; cả ba án trả `insufficient_context`, không sinh AU. 16 scope/58 phần evidence thuộc 011904, 045155 và 099980 giữ unresolved. Đây là vấn đề chất lượng authoring cần nghiên cứu tiếp, không phải kết quả AU đã đạt. Controls giả lập 9/9 hợp giao thức không thay thế đánh giá bản án.

Tài liệu kiến trúc và lịch sử nằm ở `knowledge_base/design/pipeline_redesign_lynx/`. Xem 37–43 để hiểu chuyển hướng và contract trước khi điều chỉnh prompt/model.

## Cài môi trường

Clone repo vào thư mục tùy chọn. Mọi đường dẫn bên dưới được hiểu từ thư mục gốc repo, không từ `knowledge_base/`.

Trên Windows, archive giữ nguyên cây địa chỉ lịch sử nên có tên đường dẫn dài. Dùng cấu hình Git này ngay khi clone:

```powershell
git clone -c core.longpaths=true <repo-url> <thu-muc-repo>
```

Nếu đã clone, đặt `git config core.longpaths true` trước khi checkout snapshot. Đường dẫn tương đối giải quyết việc đổi vị trí repo; cấu hình này giải quyết giới hạn tên đường dẫn của Git trên Windows.

```powershell
cd <thu-muc-repo>
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install `
    -r knowledge_base\requirements.txt `
    -r knowledge_base\pipeline_v1\k0_authoring\requirements.txt
Copy-Item knowledge_base\.env.example knowledge_base\.env
```

Tự điền credential vào `.env` local nếu cần inference; không commit `.env`. Kiểm tra/preflight và đọc lịch sử không cần gọi model. Không chuyển sang endpoint/model khác mà coi là cùng phép thử.

`KB_SOURCE_DIR` và `KB_KOS_DIR` trong file mẫu dùng đường dẫn tương đối. Snapshot K0 đã mang nguồn cần thiết, không cần corpus đầy đủ hoặc thư mục KOS bên ngoài để xem kết quả và kiểm portable. Muốn nghiên cứu corpus/KOS ngoài snapshot, đặt dữ liệu local và cấu hình đường dẫn tương đối phù hợp; dữ liệu không tự có trong clone.

## Kiểm tra ngay sau clone, không inference

```powershell
$wrapper = '.\knowledge_base\pipeline_v1\experiments\run_k0_portable.ps1'
& $wrapper -Command inspect -CheckRuntime
& $wrapper
```

Lệnh đầu đọc lại kết quả thật đã bàn giao và kiểm snapshot/code/tokenizer. Lệnh sau chuẩn bị run portable mới, preflight và dry-run; không gửi request lên Modal. Snapshot mặc định nằm tại `knowledge_base/pipeline_v1/research_snapshots/k0_portable_20261025/`; output mới nằm tại `research_bundle/k0_portable_runs/current/`, được Git bỏ qua.

Có thể kiểm resume bằng mock, không cần credential:

```powershell
& $wrapper -Mock -MaxNewRequests 1
# incomplete / exit 3 ở đây là checkpoint cố ý sau một POST giả lập.
& $wrapper -Mock
```

Sau khi dừng invocation, copy toàn repo cùng thư mục run portable sang vị trí khác rồi gọi lại với cùng đường dẫn tương đối để resume. Không xóa receipt hoặc tạo root khác để né lỗi.

Run thật mới cần `-Execute`, endpoint/credential trong `.env` local và native CPU grammar gate. Đặt `-NativePython` hoặc `K0_NATIVE_PYTHON` trỏ đến môi trường có `xgrammar==0.2.1`, `numpy`, `transformers` và tokenizer tương thích; không có ràng buộc vị trí cài Python của máy cũ. Tham khảo `knowledge_base/pipeline_v1/k0_portable/README.md`. Không chạy lại model chỉ để chuyển môi trường hoặc đọc kết quả cũ.

Kiểm thử lane bàn giao:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_k0_portable -v
```

Các test/pilot lịch sử khác có thể cần artifact ngoài snapshot; không suy rằng toàn bộ experiment cũ đã chạy được chỉ từ kiểm tra portable này.

## Nguyên tắc chuyển môi trường

- Dùng manifest portable mới với đường dẫn POSIX tương đối và base repo rõ ràng; không thay chuỗi `G:\...` hàng loạt trong artifact cũ.
- Giữ nguyên byte/hash của source, payload, receipt và manifest lịch sử. Các đường dẫn tuyệt đối nằm trong bằng chứng gốc chỉ là provenance; không dùng chúng để truy cập file trên máy mới.
- Runtime/platform cũ là thông tin thực thi lịch sử, không phải danh tính nguồn. Khi tạo run mới, khóa nội dung model/prompt/schema/tokenizer và ghi runtime mới riêng.
- Resume portable kiểm binding và receipt trước khi dispatch; kết quả đã hợp lệ không được gửi lại chỉ vì đổi thư mục checkout. Không ghi nhận receipt lịch sử thành inference mới.
- Giữ `.gitattributes`: code và source có binding dùng `-text` để Git không đổi CRLF/LF khi clone, làm lệch hash.
- Script K0 cũ và các output cũ phục vụ tái hiện lịch sử; dùng lane portable cho môi trường mới. Không giả định mọi pilot Plan01–12 đã tự chuyển sang portable.

Commit bàn giao bao gồm việc xóa package `legal_unit/` cũ theo yêu cầu. Các test/entrypoint cũ gọi package đó không còn là hướng triển khai hiện hành.
