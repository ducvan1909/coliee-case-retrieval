# BM25 sparse tính sẵn điểm

Đợt triển khai ngày 10/11/2026 dùng dạng mảng sparse theo từ để giảm chi phí đọc từng dòng SQLite. Hai kênh case và passage có dữ liệu và thống kê riêng. Mỗi posting chứa ID tài liệu dạng `uint32` và điểm đóng góp BM25 `float64`. Mảng `uint64` chỉ vùng postings của mỗi từ.

Với số postings đã kiểm kê, phần mảng chính dự kiến 282,31 MiB cho passage và 85,18 MiB cho case. Con số này chưa gồm vocabulary, ID mapping, headers và metadata. Reader mở các file `.npy` bằng `mmap` chỉ đọc. Mảng tổng điểm passage dài 415.693 phần tử chiếm khoảng 3,17 MiB. Cache hệ điều hành và dữ liệu runtime cần được đo riêng khi công bố RAM.

Builder lấy thống kê, df và postings từ SQLite đã seal. Duyệt postings theo lô và ghi vào các vùng định trước, rồi kiểm đủ df, ID, tính duy nhất và thứ tự trong từng từ. Artifact chỉ dùng được sau khi ghi manifest và seal hoàn tất. Khi nguồn, analyzer, tham số hoặc code bị thay đổi, reader kiểm provenance và yêu cầu snapshot mới.

Reader giữ nguyên analyzer, công thức BM25, float64, sorted unique query terms, query-case exclusion và tie-break theo ID. Mỗi truy vấn cộng contribution đã lưu, lấy top passage hoặc best passage mỗi case, rồi mở metadata cho các kết quả giữ lại. Corpus metadata và nguồn vẫn có hash và UTF-8 offsets để mở evidence.

Kiểm tra gồm oracle scalar độc lập, fixture Unicode/negation/ties/OOV, mất hoặc hỏng file, artifact build dở, và đối chiếu 8 query lexical đã khóa ở cả hai kênh. Hybrid được đo lại bằng ba vector cache và raw span đã dùng trước đó. Các phép đo này chạy local. Query embedding thật qua Modal có lệnh riêng do người dùng hoặc AG thực hiện.

Nguồn thiết kế tham khảo gồm [BM25S](https://arxiv.org/abs/2407.03618) và [NumPy memory mapping](https://numpy.org/doc/stable/reference/generated/numpy.load.html). Cấu hình và công thức của hệ thống hiện tại được dùng làm oracle nghiệm thu.

## Sử dụng

Artifact toàn corpus đã dựng tại `pipeline_v2/artifacts/m3_sparse_20261110_v1/`. Tổng các file đã seal là 403.896.521 bytes, khoảng 385 MiB. Walltime build là 258,67 giây và có 0 request model. Code đã khóa tại `dd4eeb17401cbda28f9a14d7f9300fffde3765397e94e9bfe775385c7f2e5c7e`. [Build receipt](../reviews/m3_sparse_validation_v1/build_command_receipt.json).

Từ repo root, dùng CLI để thử reader hoặc diagnostic hybrid bằng vector cache.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse search --channel passage --query "standard of review" --query-case 095448.txt --limit 100 --unique-cases

& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse diagnostic-hybrid --query "standard of review" --query-case 095448.txt --passage-id 095448:88b488d43fde1389756a8dd7
```

Nhiều truy vấn nên dùng chung `SparseSession` hoặc `SparseHybridSession` trong một process. Mở session vẫn kiểm full snapshot và seal, bao gồm đọc các file để hash và kiểm mảng. Quá trình này có thể đưa nhiều mapped pages vào RAM. Hệ điều hành có quyền thu hồi các trang file. `mmap` không đặt hard RAM cap cho process.

Kiểm thử độc lập và regression đạt 37/37. Trên toàn corpus, 8 truy vấn × 2 kênh khớp thứ hạng và điểm với oracle scalar cho cả top 4.096 tài liệu và top 100 án duy nhất. Sai số điểm lớn nhất quan sát được là 0. Median top 100 án sau khi mở session là 0,117 giây ở kênh case và 0,166 giây ở kênh passage. [Báo cáo tests](M3_SPARSE_TEST_REPORT.md) · [Benchmark lexical](../reviews/m3_sparse_validation_v1/actual_benchmark.json).

Ba truy vấn hybrid trên Qdrant thật dùng lại cùng văn bản truy vấn và vector chẩn đoán. Kết quả từng kênh và top 20 sau RRF khớp bản SQLite. Các số sau tính bằng giây, tách thời gian mở session.

| Truy vấn | Tổng BM25 SQLite → sparse | Tổng hybrid SQLite → sparse |
|---|---:|---:|
| V01 | 73,04 → 0,41 | 90,64 → 32,79 |
| V02 | 196,56 → 0,61 | 216,65 → 11,46 |
| V03 | 337,55 → 0,54 | 346,96 → 7,37 |

Mở session sparse hybrid mất 35,25 giây trong lần đo này. Dense exact search và kiểm tra evidence chiếm phần lớn thời gian mỗi truy vấn. Thời gian dense thay đổi giữa các lượt, nên dùng cột BM25 để đánh giá riêng phần thay reader. Benchmark có 0 request model và đo truy hồi bằng vector cache. Chất lượng COLIEE và truy vấn embedding thật thuộc các phép thử riêng. [Đối chiếu hybrid](../reviews/m3_sparse_validation_v1/local_acceptance.json).

Peak working set của tiến trình Python là khoảng 523 MiB. Sau ba truy vấn, working set tại các điểm đo nằm trong khoảng 212–289 MiB. Phép đo gồm các trang file đang resident và dữ liệu tiến trình, tách riêng RAM của Docker/Qdrant. [Số đo bộ nhớ](../reviews/m3_sparse_validation_v1/hybrid_memory.json) · [Prompt AG review](AG_REVIEW_M3_SPARSE_PROMPT.md).

AG đã review độc lập bản code đã khóa và artifact toàn train. Correctness, index integrity và corpus parity đều PASS, với 6/6 nhóm kiểm thử độc lập và 0 lỗi production chặn nghiệm thu. Đối chứng 1.593.478 postings có sai số điểm bằng 0. Ghi nhận kỹ thuật gồm startup kiểm toàn snapshot, guard lặp trên đường truy vấn và heap tăng tạm khi revalidate. Các ghi nhận này được theo dõi khi tích hợp harness. Hybrid hiện được nghiệm thu ở phạm vi vector cache local. [Báo cáo AG](../reviews/m3_sparse_ag_review_v1/REPORT.md) · [Findings](../reviews/m3_sparse_ag_review_v1/findings.json).
