# Chuyển môi trường nghiên cứu bằng đường dẫn tương đối

Ngày 2026-10-25. Phạm vi là lane K0 v2 hiện hành và bộ bằng chứng để tiếp tục nghiên cứu trên máy khác; không tái thiết kế authoring AU hoặc tự chạy inference.

## Quyết định

Không thay chuỗi đường dẫn trong manifest/receipt đã khóa SHA. Tạo manifest portable dẫn xuất, đường dẫn POSIX tương đối với repo root, và archive nguyên byte các source/manifest/payload/receipt được tham chiếu. Đường dẫn tuyệt đối còn trong archive và thông tin môi trường gốc chỉ là provenance, không dùng để tìm file hoặc làm điều kiện runtime trên máy mới.

`k0_portable` dùng resolver có base repo rõ ràng, độc lập working directory. Từ chối đường dẫn tuyệt đối/drive/UNC, backslash, `..` và symlink/junction thoát vùng. Binding mới dùng đường dẫn tương đối và hash nội dung; tiếp tục khóa model, revision, prompt/schema và tokenizer. Platform, executable path và thư mục checkout không quyết định danh tính nguồn.

Nguồn vẫn đúng union16scope/58phần evidence/3án của K0 cũ. Controls được kiểm từ nguồn/schema/receipt lưu sẵn, không gọi evaluator cũ có ràng buộc platform và không gửi lại 9 request. Kết quả thật K0 v2 được đọc như lịch sử: 3 request, 6.502 token, 0 AU, chưa đạt chất lượng; không nhập thành inference của run mới.

## Resume và giới hạn

Chỉ checkpoint portable mới có thể resume trực tiếp sau khi chuyển thư mục. Lịch sử K0 cũ được đọc offline, không đổi danh tính/job ID hoặc budget cũ để giả thành run mới. Run portable có workload digest riêng; receipt hợp lệ của chính nó được reconcile trước dispatch. Giữ riêng mock/live, caps và usage chưa biết. Một run mới không được dùng để né cap hoặc retry mù cho run cũ.

Code K0/controls cũ giữ nguyên. Adapter portable chạy namespace riêng. Native CPU adapter đọc tokenizer đã pin trong repo và dùng môi trường được chọn rõ ràng, không phụ thuộc `outputs/grammar_diagnostic_deps` của máy gốc. Đổi môi trường không chứng minh decoder endpoint hay ngữ nghĩa đã đúng.

## Git và bàn giao

Snapshot nằm ngoài thư mục live `outputs`, dưới `pipeline_v1/research_snapshots/`. Chỉ archive cần thiết, không đưa toàn bộ output thử nghiệm, venv, package cache hoặc credential lên Git. `.gitattributes` đặt `-text` cho code/source/artifact có SHA để CRLF/LF không đổi khi clone. `.env` local dùng đường dẫn dữ liệu tương đối; file mẫu không còn đường dẫn ổ đĩa G.

Theo yêu cầu người dùng, commit bàn giao gộp cả 13 file xóa trong package `legal_unit/` cũ. Không giữ package đó làm đường chạy thay thế cho pipeline hiện hành.

Xem hướng dẫn cài, kiểm local và lệnh chạy trong `RESEARCH_HANDOFF.md` ở repo root. Nghiệm thu bằng checkout ở vị trí khác, không có `outputs` gốc, kiểm source/code/receipt/tokenizer, path traversal và mock resume không gọi lại receipt đã hợp lệ. Không gọi model/deploy để nghiệm thu chuyển môi trường.

## Kiểm tra đã thực thi

4/4 test portable PASS trên bản cuối, gồm clone tối thiểu code/bundle, CWD Unicode riêng, chặn đọc repo gốc, source/code/receipt/tokenizer bị sửa và resume sau chuyển thư mục. Native CPU adapter PASS 4 grammar/7 positive/10 negative, khoảng12giây sau khi tắt JIT Torch DLPack tùy chọn; không thay grammar hoặc EOS. Một phép gọi đầu thiếu input và một lượt import dependency bị kẹt JIT đã được giữ là kiểm tra local thất bại/dừng, không có inference.

Snapshot giữ238file archive nguyên byte và152binding code/asset. Kiểm credential không thấy key local hoặc mẫu key phổ biến trong tập file bàn giao. Kết quả kiểm chi tiết tại `research_snapshots/k0_portable_20261025/HANDOFF_VALIDATION.json`; các kết quả này không chứng minh chất lượng AU.
