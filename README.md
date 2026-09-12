# COLIEE Case Retrieval

Kho mã nguồn nghiên cứu và phát triển hệ thống cho
[COLIEE 2026 Task 1 — Legal Case Retrieval (CL-IR)](https://coliee.org/COLIEE2026/tasks/task1).

## Bài toán

COLIEE Task 1 yêu cầu tìm các bản án đã được một bản án truy vấn viện dẫn
(*noticed cases*) trong một tập án lệ cho trước.

Gọi:

- `q` là một bản án truy vấn;
- `C` là tập các bản án ứng viên;
- `N(q)` là tập bản án trong `C` được `q` viện dẫn.

Mục tiêu của hệ thống là dự đoán:

```text
N(q) = {c thuộc C | q viện dẫn c}
```

Các thông tin nhận diện trực tiếp những bản án được viện dẫn đã bị ẩn khỏi nội
dung truy vấn. Trong dữ liệu đang sử dụng, nhiều vị trí bị ẩn được biểu diễn
bằng token `FRAGMENT_SUPPRESSED`. Token này chỉ là tín hiệu ngữ cảnh: số lần nó
xuất hiện không nhất thiết bằng số bản án cần trả về.

Đây là bài toán **truy hồi văn bản pháp lý trên tập đóng, đa nhãn**. Nó không
phải tìm kiếm web, hỏi đáp pháp luật hay phân loại mỗi truy vấn vào đúng một
nhãn.

## Dữ liệu vào và đầu ra

Corpus gồm các bản án bằng tiếng Anh của Tòa án Liên bang Canada.

- **Tập huấn luyện:** các tệp văn bản án lệ và một tệp JSON ánh xạ mỗi query
  tới danh sách noticed cases tương ứng.
- **Tập kiểm thử:** cung cấp các query nhưng không cung cấp nhãn cho hệ thống
  tại thời điểm dự đoán.
- **Đầu ra:** với mỗi query, hệ thống trả về một danh sách case ID có độ dài
  biến thiên.

Ví dụ nhãn huấn luyện:

```json
{
  "000001.txt": ["000005.txt", "012101.txt"],
  "003423.txt": ["398421.txt", "012101.txt"]
}
```

Định dạng một dòng của tệp nộp Task 1:

```text
<query_id> <retrieved_case_id> <run_tag>
```

Ví dụ:

```text
000001 000018 runA
000001 000045 runA
000002 000433 runA
```

## Đánh giá

Kết quả chính thức được đánh giá bằng **micro-Precision**, **micro-Recall** và
**micro-F1** trên toàn bộ các cặp `(query_id, noticed_case_id)`:

```text
Precision = số cặp dự đoán đúng / tổng số cặp được dự đoán
Recall    = số cặp dự đoán đúng / tổng số cặp đúng
F1        = 2 × Precision × Recall / (Precision + Recall)
```

Micro-F1 là mục tiêu cuối. `Recall@K` của tầng sinh ứng viên chỉ đo khả năng
đưa án đúng vào candidate pool; nó không phải điểm F1 của hệ thống hoàn chỉnh.

## Những thách thức chính

- Bản án dài và không có cấu trúc trình bày hoàn toàn đồng nhất.
- Thông tin trích dẫn trực tiếp đã bị che khỏi query.
- Mỗi query chỉ có ít noticed cases trong một tập ứng viên lớn.
- Liên quan về chủ đề chưa đủ để kết luận có quan hệ viện dẫn.
- Số kết quả đúng thay đổi theo từng query, nên hệ thống phải cân bằng recall
  và precision khi chọn danh sách cuối.

Một pipeline truy hồi hoàn chỉnh thường phải giải quyết ba tầng riêng biệt:

```text
Query case
   → sinh candidate pool
   → xếp hạng lại candidate
   → chọn tập kết quả cuối
   → noticed case IDs
```

Nếu một noticed case không vào candidate pool, các tầng sau không thể phục hồi
nó. Ngược lại, trả về quá nhiều candidate có thể tăng recall nhưng làm giảm
precision và micro-F1.

## Ràng buộc thực nghiệm

- Hệ thống phải chạy tự động; không được điều chỉnh hệ thống dựa trên việc đọc
  thủ công các test query.
- Test labels chỉ được dùng để đánh giá sau khi dự đoán đã được khóa, không
  được dùng để chọn retriever, reranker, threshold hoặc số kết quả trả về.
- Theo quy định COLIEE 2026, chỉ được dùng LLM có mô hình hoặc dữ liệu huấn
  luyện được công khai; mô hình đóng không được phép.

## Tài liệu chính thức

- [Task 1: Legal Case Retrieval](https://coliee.org/COLIEE2026/tasks/task1)
- [Task 1 corpus format](https://coliee.org/COLIEE2026/corpus/task1)
- [Evaluation](https://coliee.org/COLIEE2026/evaluation)
- [Submission guidelines](https://coliee.org/COLIEE2026/submission)
- [COLIEE 2026 rules](https://coliee.org/COLIEE2026/rules)
