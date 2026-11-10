# M3 hybrid search trên full train

Hybrid dùng một `HybridSession` cho nhiều truy vấn. Case BM25 và passage BM25 dùng reader đã nghiệm thu. Dense tìm chính xác trên Qdrant local, còn query embedding thật dùng app V2 đang có. Phạm vi là tích hợp ba kênh và gộp theo bản án. Phrase, identity, context delivery và đánh giá COLIEE thuộc các bước riêng.

Mỗi kênh đóng góp tối đa 100 bản án khác query case. Passage và dense lấy hit đại diện cho từng bản án. Dense đọc tối đa 4.096 raw hits trong một lượt tìm và báo khi giới hạn đó làm hụt số án. RRF dùng `k=60`, một phiếu mỗi kênh, mặc định trả 20 án. Điểm dùng để xếp hạng ứng viên cần đọc tiếp.

Dense lọc query case và fingerprint trước khi lấy top hits. Session kiểm schema và exact count trước query embedding thật, đối chiếu ID/payload của toàn bộ dense hits với metadata đã seal, rồi đối chiếu cosine với cache cho các hit đại diện và hit ở biên. Receipt full verify là bằng chứng lịch sử. Kiểm tra theo request chỉ bao phủ schema, count và các hit đã trả. Trường coverage ghi giới hạn quét, budget thiếu và khả năng có đồng hạng ở biên.

Chạy các lệnh từ repo root. Phép đo local dùng ba vector passage đã khóa trong manifest chẩn đoán trước đó, lấy đúng raw span tương ứng làm câu BM25. Cả ba truy vấn dùng chung session. Báo riêng thời gian mở session, từng kênh và tổng thời gian một request. Output JSONL phải là đường dẫn mới.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.reviews.m3_hybrid_validation_v1.benchmark_cached --output pipeline_v2/reviews/m3_hybrid_validation_v1/qdrant_cached_benchmark.jsonl
```

Một lượt kiểm query embedding thật do người dùng hoặc AG chủ động chạy khi Qdrant đã sẵn sàng. Lệnh dùng query template V2 và phát sinh một request Modal nếu qua các kiểm tra local. `--query-case` là ID án train cần loại khỏi kết quả. Ledger riêng của request nằm tại `pipeline_v2/artifacts/m3_full_search_runtime_v1/<request_id>/ledger.sqlite3`.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_hybrid search --query "standard of review" --query-case 095448.txt --limit 20
```

Khi giao AG, đọc kế hoạch M3 full search, tài liệu này và kết quả kiểm thử local. Kiểm lại exclusion ở từng kênh, trần 100 án trước fusion, coverage khi 4.096 raw hits chưa đủ án, và phép tính RRF độc lập. Chạy cached benchmark trước, sau đó dùng đúng một query embedding thật như lệnh trên nếu bước local đạt. Ghi command, exit code, latency, token/unknown usage và report trong thư mục review mới. Phân biệt benchmark cached vector với query embedding thật và phân biệt RRF ranking với chất lượng COLIEE.

Kiểm thử độc lập đạt 25/25, gồm 11 test hybrid và 14 regression lexical. Main bổ sung và chạy riêng kiểm thử chặn query embedding khi count live sai. Cả hai test readiness đạt. Các test mô phỏng transport và dùng ledger tạm để kiểm token chưa biết khi request lỗi. Lệnh tái hiện:

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m3_hybrid_fusion pipeline_v2.tests.test_m3_hybrid_dense pipeline_v2.tests.test_m3_lexical_reader -v
```

Ngày 10/11/2026, Docker Desktop báo lỗi lúc tạo socket `dockerInference`, và kết nối local tới cổng 6333 bị từ chối. Main dùng cosine tham chiếu tính từ đủ 415.693 vector trong cache, rồi phát lại các hits qua adapter để kiểm ranking với BM25 thật. Cả ba truy vấn đạt exclusion, trần 100 án mỗi kênh và RRF top 20. Chi phí mở session là 50,45 giây. Passage BM25 chiếm 31,75–58,69 giây mỗi truy vấn. Phép đo này gồm chi phí replay và kiểm kết quả, vì vậy latency Qdrant cần đo lại bằng lệnh local ở trên. [Kết quả replay](../reviews/m3_hybrid_validation_v1/offline_cached_benchmark.jsonl).

Sau khi Docker hoạt động lại, benchmark qua Qdrant thật hoàn tất 3/3 truy vấn. Collection có 415.693 điểm. Mỗi kênh trả 100 án hợp lệ, và cả ba top 20 sau fusion có cùng thứ tự với tham chiếu offline. Cả 300 passage đại diện dense xuất hiện trong tham chiếu, với sai lệch cosine tối đa 1,54 × 10⁻⁷. Phép đo dùng vector cache và ghi 0 request model. [Kết quả Qdrant thật](../reviews/m3_hybrid_validation_v1/qdrant_cached_benchmark.jsonl).

Session mở trong 63,72 giây. Bảng ghi thời gian theo giây của từng truy vấn, tách khỏi thời gian mở session. Tổng hybrid bao gồm kiểm schema/count, payload/cache và fusion.

| Truy vấn | Case BM25 | Passage BM25 | Qdrant exact | Tổng hybrid |
|---|---:|---:|---:|---:|
| V01 | 8,27 | 64,77 | 13,79 | 90,64 |
| V02 | 8,95 | 187,61 | 15,86 | 216,65 |
| V03 | 3,39 | 334,15 | 5,22 | 346,96 |

Passage BM25 chiếm 71–96% thời gian mỗi truy vấn trong lần chạy này. Đây là ba truy vấn chẩn đoán khác nhau, chạy tuần tự trong một session. Kết quả chưa tách ảnh hưởng riêng của độ dài truy vấn, cache và tải hệ thống. Latency RPC của query embedding V2 cần lượt đo riêng.
