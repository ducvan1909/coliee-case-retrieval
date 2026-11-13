# Kiểm thử phần triển khai M3 ngày 11–12/11/2026

M3 đạt nghiệm thu kỹ thuật ngày 12/11/2026. Các công cụ tìm và mở nguồn đạt kiểm thử local, cached hybrid đạt ba lượt trên máy hiện tại, và AG chạy thành công một query embedding thật theo manifest. [Quyết định thiết kế](../../docs/plan/M3_SOURCE_TOOLS_S0.md) · [Hướng dẫn sử dụng](../../docs/M3_SOURCE_TOOLS.md) · [Receipt nghiệm thu](real_query_execution/main_acceptance.json)

| Kiểm tra | Kết quả |
|---|---|
| Fixture và regression liên quan | 54/54 đạt, gồm 13 test source tools và kiểm thử admission của lệnh Modal. |
| CLI `case-map` | Trả 2/35 units của `095448.txt`. Tổng 37,3 giây, trong đó mở session khoảng 36,9 giây. |
| Phrase exact trên toàn corpus | Quét đủ 7.708 án qua 61 trang. Kết quả khớp phép tìm trực tiếp trên raw bytes. |
| Mở nguồn thực | `041666.txt/p000417` trả đủ 85.010 byte qua 21 trang, giữ cả hai vùng pending quanh middle hit. `055641.txt/p000351` trả đủ 1.407 byte. Các fragment và metadata đối chiếu raw/M1. |
| Qdrant sau phục hồi | Full verify đạt đủ 415.693 points, lần cached hybrid lúc phục hồi trả 20 án và qua kiểm tra độc lập. |
| Hai lần kiểm tra tích hợp với timeout mặc định | HTTP 500 do `Search` hết 120 giây. Collection vẫn `green`. Cả hai lần kết thúc trước bước mở nguồn. |
| Chẩn đoán với timeout 300 giây | Cùng truy vấn cached, giữ exact search. Qdrant trả HTTP 500 sau 300 giây. Giới hạn này chỉ áp trong tiến trình chẩn đoán. [Kết quả](hybrid_source_integration_1794379857797010000.json) |
| Mở nguồn từ kết quả hybrid đã xác minh | Đọc lại kết quả cached hybrid lúc phục hồi, mở passage leads của 3 án đứng đầu và đối chiếu raw bytes/hash. Một án vượt ngân sách 4.096 byte và trả đúng các khoảng pending. Snapshot dùng chung vẫn hoạt động sau khi đóng source tools. [Kết quả](hybrid_source_integration_1794379707166488300.json) |

Regression giữ bằng chứng lỗi `open_ref` trước sửa và xác nhận tất cả tool search mở được bằng `open_source(**open_ref)` sau sửa. Một fixture cũ đã được chỉnh để chuẩn hóa đường dẫn tạm Windows giống constructor thật. [Kiểm thử độc lập](../m3_source_tools_validation_v1/REPORT.md)

Đối chứng REST tái hiện timeout trong full scan của Qdrant, kể cả khi chỉ trả top 1, bỏ payload và bỏ filter. Số đo cho thấy tải CPU kéo dài trong lượt quét, với ít thời gian toàn hệ thống chờ I/O và swap. Trần RAM WSL 4 GB là yếu tố cần kiểm bằng phép thử có kiểm soát. [Chẩn đoán timeout](DENSE_TIMEOUT.md)

Ngày 12/11, AG chạy ba lượt liên tiếp trên `DUCVAN` sau khi khởi động Docker Desktop. Theo báo cáo AG, Docker thấy 6 vCPU và 4.108.464.128 byte RAM. Collection `green` với 415.693 points. Cả ba lượt trả 20 ứng viên, mở được nguồn của cùng ba án đứng đầu và phát sinh 0 request Modal, 0 retry. Dense exact lần lượt mất 30,20, 12,40 và 42,11 giây. Đây là kết quả trên máy hiện tại. Đợt chạy này chưa có số đo đối chứng từ máy cũ hoặc phép thử cô lập tác động của việc khởi động Docker. [Lượt 1](hybrid_source_integration_1794445870392634700.json) · [Lượt 2](hybrid_source_integration_1794445927075006800.json) · [Lượt 3](hybrid_source_integration_1794446016624091500.json)

AG chạy đúng một query thật cho `017984.txt` thuộc discovery cohort. Lệnh exit `0`. Mỗi kênh trả 100 án duy nhất và loại query case khỏi tập 7.707 án hợp lệ. Main tính lại thứ tự và điểm RRF top 20, đối chiếu 200 passage leads với M2 đã seal và các byte nguồn, rồi kiểm ledger chỉ đọc. Ledger ghi 1 request thành công, 184 input tokens, 184 padded tokens, 0 retry và đủ số liệu thời gian cho attempt. Main phát sinh 0 request Modal khi kiểm receipt. [Kết quả live](real_query_execution/stdout.json) · [Usage và exit code](real_query_execution/command_receipt.json) · [Kiểm tra của Main](real_query_execution/main_acceptance.json)

Tổng thời gian là 575,51 giây. Mở session mất 72,96 giây, RPC Modal đo phía client mất 481,24 giây và dense exact Qdrant mất 13,09 giây. Modal báo 0,82 giây xử lý remote và 13,84 giây nạp model. Receipt chưa giải thích được phần chênh lệch còn lại trong thời gian RPC phía client.

Khi chuẩn bị manifest lần hai, trường `revision` của model đã bị ghi đè bởi số phiên bản manifest `2`. Main xác nhận model revision thực tế từ profile đã khóa, manifest gốc được lưu và descriptor trong ledger. Cả ba khớp `5cf2132abc99cad020ac570b19d031efec650f2b`. Phép thử xác nhận vận hành end-to-end trên một query. Đánh giá quan hệ viện dẫn và F1 thuộc phạm vi M7.

Lệnh AG đã chạy được lưu để đối chiếu với admission.

```powershell
& .venv/Scripts/python.exe pipeline_v2/reviews/m3_completion_v1/run_real_query.py --execute
```

[Manifest](real_query_manifest.json) · [Regression cuối](regression_postfix_receipt.json) · [Kiểm corpus](local_acceptance_1794379357340697300.json) · [Quét phrase](corpus_phrase_acceptance_1794378234702085300.json) · [Timeout lần hai](hybrid_source_integration_1794379111801554800.json) · [Phục hồi Qdrant](../qdrant_restore_20261111_v1/REPORT.md)
