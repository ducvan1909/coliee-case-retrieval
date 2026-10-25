# Kiểm kê corpus, tài nguyên và mẫu nghiên cứu vòng 2

## 1. Phạm vi và cách đo

Kiểm kê ngày 2026-09-30 trên `data/task1_train_files_2026` và `data/task1_test_files_2026`. Script chỉ đọc file, giải mã UTF-8 có BOM, đếm ký tự và dò một số pattern cấu trúc. Không dùng train labels, noticed-case gold hoặc artifact KOS để chọn mẫu.

Các phép dò marker, heading và citation chỉ dùng để mô tả corpus và tạo slice kiểm thử. Chúng không phải nhãn đúng/sai và không được dùng làm cổng tạo annotation hay AU.

## 2. Quy mô đo được

| Chỉ số | Giá trị |
|---|---:|
| Tổng file án | 9.556 |
| Train | 7.708 |
| Test | 1.848 |
| Tổng ký tự giải mã | 279.096.251 |
| P10 độ dài | 8.418 ký tự |
| Trung vị | 22.021,5 ký tự |
| P90 | 53.268 ký tự |
| P95 | 73.298 ký tự |
| P99 | 146.898 ký tự |
| Nhóm trùng exact theo SHA-256 | 0 |
| Không có standalone `[n]` theo phép dò | 1.721 |
| Không có standalone `[n]` nhưng có pattern citation | 242 |

Kết luận trực tiếp: marker không đủ làm cổng cứng. Tình trạng 242 án chỉ là lower bound phụ thuộc pattern dò; không chứng minh 1.479 án còn lại không có citation hoặc không có nội dung pháp lý hữu ích.

## 3. Tài nguyên máy quan sát được

| Thành phần | Giá trị |
|---|---|
| CPU | Intel Core i5-10400, 12 logical processors |
| GPU | NVIDIA GeForce GTX 1650, 4.096 MiB |
| Hệ điều hành | Windows 10 Pro |
| RAM | Chưa đọc được bằng WMI do `Access denied`; phải đo lại trước benchmark |

GPU 4 GB không đủ để mặc định một transformer dài hoặc LLM lớn chạy toàn corpus. Mọi model local phải đo throughput, peak RAM/VRAM, batch size và fallback CPU trên đúng máy này hoặc môi trường triển khai đã khóa.

## 4. Mẫu 60 án đã khóa

Quy tắc: trong mỗi split, xếp theo byte length, chia ba dải bằng số lượng; trong mỗi `(split, band)`, xếp theo SHA-256 của `lynx-round2:{split}:{band}:{case_id}` và lấy 10 án. Cứ phần tử thứ ba vào development. Kết quả có 20 development và 40 holdout. Holdout không được dùng để sửa rule, prompt, threshold, label mapping hoặc model.

| Tập | Split | Dải | Case IDs |
|---|---|---|---|
| Development | train | short | 011680, 073214, 040898, 050313 |
| Holdout | train | short | 068905, 004750, 087182, 027941, 099523, 034757 |
| Development | train | medium | 034501, 093150, 083288 |
| Holdout | train | medium | 033849, 089468, 019072, 063124, 013378, 065768, 020779 |
| Development | train | long | 047415, 006725, 043625 |
| Holdout | train | long | 030153, 086137, 016637, 073619, 049829, 014163, 012639 |
| Development | test | short | 097712, 048676, 094658, 016218 |
| Holdout | test | short | 040589, 070983, 040305, 090645, 005174, 074351 |
| Development | test | medium | 026464, 014017, 027593 |
| Holdout | test | medium | 078012, 067062, 050647, 034828, 073623, 027582, 025471 |
| Development | test | long | 060339, 043490, 096254 |
| Holdout | test | long | 086515, 017964, 092684, 052918, 093995, 077956, 086623 |

## 5. Mẫu bổ sung theo hiện tượng

Mẫu 60 án bảo đảm split và độ dài, chưa bảo đảm đủ ca thiếu marker, citation không marker, speaker mơ hồ hoặc court response xa. Trước khi annotate, chọn thêm các slice hiện tượng bằng rule không dùng nhãn. Nếu một slice không đủ trong 60 án, bổ sung case chỉ cho kiểm thử hiện tượng và báo tách khỏi metric chính; không thay case holdout sau khi đã xem kết quả.

Năm án calibration `099980`, `013948`, `045155`, `011904`, `013009` chỉ dùng tái hiện lỗi và sửa hợp đồng. Chúng không thuộc tập xác nhận chất lượng.
