# Chẩn đoán dense exact trên Qdrant 1.20.0 ngày 11/11/2026

Timeout tái hiện trong lượt quét dense exact của Qdrant. Dùng cùng vector cache `095448:88b488d43fde1389756a8dd7` và gọi REST trực tiếp để loại các bước xử lý ngoài Qdrant khỏi phép đo. Các phép thử local phát sinh 0 request Modal.

| Phạm vi exact | Kết quả do server báo |
|---|---|
| Các passage trong `095448.txt`, top 20, bỏ payload | HTTP 200, 1,12 giây |
| Filter M3 trên toàn collection, top 4.096, trả payload | HTTP 500, timeout `Search` ở 120 giây |
| Cùng filter M3, top 1, bỏ payload | HTTP 500, timeout `Search` ở 60 giây |
| Bỏ filter, top 1, bỏ payload | HTTP 500, timeout `Search` ở 90 giây |

AG tái hiện qua CLI tích hợp trên cùng checkout và container. Kiểm collection và count trả HTTP 200, sau đó Qdrant trả HTTP 500 với `Search` timeout sau 119,98 giây. Tiến trình thoát mã 1 sau 162,38 giây tính cả mở session, với một lần gọi cached, 0 retry và 0 request Modal. [Receipt chạy lại của AG](hybrid_source_integration_1794384649157994800.json)

Filter M3 giữ 415.653 vectors đủ điều kiện trong 415.693 points. Qdrant thực hiện full scan trong chế độ `exact=true`. Giảm top K thay đổi số kết quả nhưng vẫn cần chấm mọi vector đủ điều kiện. Đối chứng bỏ filter cho thấy filter không phải điều kiện để tái hiện. [Tài liệu Qdrant Search](https://qdrant.tech/documentation/search/) · [Tài liệu storage](https://qdrant.tech/documentation/manage-data/storage/)

Trong 103 giây có mẫu bên trong lần gọi M3 bị timeout, cgroup của Qdrant tăng 348,76 giây CPU, gồm 272,14 giây user và 76,62 giây kernel. Mức dùng trung bình là 3,39 lõi. Đọc block device tăng 187,25 MiB. Chỉ số PSI toàn WSL ghi 1,08 giây `io full` và 0,095 giây `memory full`. Chỉ số `io some` bao gồm cả các khoảng có ít nhất một tác vụ bị chặn. Trong cùng cửa sổ, WSL ghi thêm 21 trang swap-in và 56 trang swap-out. Ảnh chụp `schedstat` trong đối chứng không filter cho thấy ba thread `search-io` đứng đầu theo CPU tích lũy.

Tải CPU của đường quét bên trong Qdrant là dấu hiệu chi phối trong phép đo này. Bộ đếm không cho thấy phần lớn thời gian bị tiêu vào chờ đĩa hoặc swap. WSL có trần 4 GB và phần vector float32 thuần chiếm khoảng 3,96 GiB, nên page cache đầy đủ là bất khả thi trong cấu hình đó. Chưa có phép thử thay đổi RAM được kiểm soát để kết luận đây là nguyên nhân gốc, và chưa có profiling theo hàm để quy phần CPU cao cho một đoạn triển khai cụ thể. Lần cached hybrid sau phục hồi từng hoàn tất dense query trong khoảng 64 giây, vì vậy kết quả cho thấy sự cố hiệu năng phụ thuộc môi trường hoặc trạng thái chạy.

[Các lần gọi có filter](dense_timeout_requests_1794381268935313500.jsonl) · [Đối chứng bỏ filter](dense_timeout_requests_1794381448198802000.jsonl) · [Mẫu tài nguyên](dense_timeout_telemetry_1794381252662.txt) · [Script tái hiện](diagnose_dense_timeout.py)
