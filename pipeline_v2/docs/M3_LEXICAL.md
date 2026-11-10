# Reader BM25 local tối ưu

Phạm vi người dùng giao: tăng tốc reader BM25 rồi kiểm tính đúng và số đo thực tế. Đây là một phần chuẩn bị full search; chưa triển khai dense/fusion, phrase/identity hay controller M4 theo draft full search.

Thiết kế mới dùng nguyên SQLite đã seal, không rebuild database: preload ánh xạ ID/length/case, bỏ JOIN trong vòng từ khóa, đọc postings theo lô có giới hạn và tính BM25 bằng NumPy float64. Công thức/analyzer/exclusion/tie-breaking phải khớp reader cũ trong tolerance đã khai báo. Giảm score vòng Python có thể cải thiện thêm so với phương án C của AG, nhưng SQL/I/O vẫn có thể chi phối; chỉ công bố mức tăng tốc sau khi đo.

Namespace mới `full_search/lexical.py`, CLI `m3_lexical.py`, profile `configs/m3_lexical.json`. Giữ nguyên code/config/run full ingestion và pilot. Không cần Modal, GPU, credentials, re-embedding hoặc Qdrant. Mở session kiểm snapshot/hash/provenance một lần, ghi riêng chi phí startup; query tiếp theo không hash lại4,36GB.

Profile ban đầu đề xuất cache128MiB/mmap512MiB để đo, không coi đây là RAM hard cap hoặc cấu hình tối ưu đã chứng minh. SQLite báo actualPRAGMA; hệ điều hành có thể giữ thêm pagecache. Request lexical chỉ trả ranking/leads, không xác nhận nguồn noticed hoặc quyết định pháp lý.

Code đã freeze tại `3633aa881ef8ff7f739a87c5c174b00faff82f59f656466a70d3804f7c0856bf`. Kiểm thử độc lập đạt 32/32, gồm 14 test reader và 18 regression V2. [Báo cáo kiểm thử](M3_LEXICAL_TEST_REPORT.md).

## Kết quả trên toàn corpus

Tám truy vấn đã khóa, mỗi truy vấn chạy ở cả kênh case và passage với giới hạn 4.096 hits. Cả 16 phép so sánh khớp thứ tự ID và điểm số với cách tính scalar độc lập. Sai lệch điểm tối đa bằng 0. Thời gian mở session, gồm kiểm snapshot và preload, là 78,44 giây trong lần đo này. [Kết quả chi tiết](../reviews/m3_lexical_validation_v1/actual_benchmark.json).

| Kênh | Scalar median | Reader mới median | Lượt lặp reader mới median |
|---|---:|---:|---:|
| Case | 0,43 giây | 1,23 giây | 0,26 giây |
| Passage | 15,27 giây | 18,08 giây | 13,11 giây |

Lượt lặp passage trải từ 2,17 đến 77,08 giây. So sánh trong lần đo này chưa xác lập lợi ích tốc độ riêng của NumPy. Reader mới tính cả kiểm snapshot nhẹ và đọc metadata kết quả trong mỗi truy vấn, còn scalar chỉ tính và xếp hạng điểm. Các lượt dùng cache ở trạng thái khác nhau. Mốc 7,55 giây của phương án C do AG đo với cấu hình SQLite khác. Khi chọn cấu hình cho full search, cần đo lại cùng ranh giới công việc và điều kiện bộ nhớ. [Phạm vi phép đo](../reviews/m3_lexical_validation_v1/BENCHMARK_PROTOCOL.md).

## Nghiệm thu sau review AG ngày 10/11/2026

Chấp nhận reader làm thành phần lexical của M3. Fingerprint code hiện tại khớp bản đã review. AG ghi nhận 32/32 tests hiện có và 8/8 tests độc lập PASS. Main đối chiếu artifact đo thật. Cả 16 cặp truy vấn và kênh khớp thứ tự ID và điểm ở cả chế độ raw top 4.096 và 100 unique cases. [Báo cáo AG](../reviews/m3_lexical_ag_review_v1/REPORT.md) · [Số đo chi tiết](../reviews/m3_lexical_ag_review_v1/bounded_benchmark_results.json).

Trong phép đo AG, phần tính điểm và chọn top-k passage nhanh hơn khoảng 2,35 lần theo median của tỷ lệ từng truy vấn. Truy vấn passage lấy 100 án có median 9,31 giây, phần đọc postings vẫn chiếm nhiều thời gian nhất. Fetch metadata giảm từ khoảng 723 ms xuống 4,68 ms khi yêu cầu ít kết quả hơn. Hai giới hạn này trả số lượng và loại kết quả khác nhau. Thứ tự chạy và trạng thái cache có thể giải thích một phần dao động. Phép đo chưa cô lập được tác động riêng của cache lên tổng latency.

Giữ cấu hình hiện tại làm mốc tích hợp và tái sử dụng session. Khi nối hybrid, đo thời gian toàn trình gồm guard và các kênh cùng hoạt động. Phần guard khoảng 87 ms đã đo nằm ngoài timer nội bộ của reader. Kiểm tra lợi ích của tối ưu I/O trên workload kết hợp trước khi chốt cấu hình SQLite khác.

## Sử dụng

Chạy từ repo root:

```powershell
# Tối đa100án khác querycase, mỗi án lấy best passage hit:
& .venv/Scripts/python.exe -m pipeline_v2.m3_lexical search --channel passage --query "standard of review" --query-case 000002.txt --limit 100 --unique-cases

# Raw top passage hits, có thể nhiều hits cùng án:
& .venv/Scripts/python.exe -m pipeline_v2.m3_lexical search --channel passage --query "standard of review" --query-case 000002.txt --limit 100
```

Mỗi standaloneCLI mở/verify snapshot và preload lại. Muốn nhiều query nhanh, giữ `LexicalSession` trong cùng process rồi gọi `session.search(...)`, cuối cùng `close()`. Chi phí mở session không nằm trong query timings nhưng vẫn tính trong CLI timer. `--unique-cases` chọn best passage mỗi án từ toàn bộ positive scores; đây là lexical ranking, không phải fusion hoặc noticed prediction.

CLI `revalidate` kiểm lại snapshot, không gọi model hoặc DBvector. Source/index được coi bất biến giữa các lượt search; phát hiện input/code/profile drift thì invalidate, nhưng không hứa phát hiện mọi thay đổi SQLite live chưa revalidate. Không chạy writer vào snapshot đang search.

[Prompt AG review phần đã triển khai](AG_REVIEW_M3_LEXICAL_PROMPT.md). Các phần dense, phrase, identity, context delivery và fusion trong draft fullsearch vẫn chờ phân xử kế hoạch, chưa thuộc reader này.
