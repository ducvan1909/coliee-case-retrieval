# Thử local bounded retrieval — query 043625

Ngày: 2026-11-04. Checkout `E:/Git/coliee-case-retrieval`.

## Kết quả chính

Đã chạy công cụ tìm–đọc trên dữ liệu thật và chấm sau khi khóa dự đoán. Hai cách mở rộng truy vấn đều đưa đủ hai noticed cases vào candidate union, nhưng vòng thích ứng không đưa án đúng vào top5. Trên ca này, query reformulation cố định tốt hơn policy thích ứng ở đầu ra top5. Chưa có bằng chứng nên dùng agent thay pipeline cố định.

| Arm | Policy | Candidate union | Gold trong union | Gold trong top5 | Precision@5 | Recall@5 | F1@5 |
|---|---|---:|---:|---:|---:|---:|---:|
| A | BM25 từ toàn query | 100 | 1/2 | 0/2 | 0 | 0 | 0 |
| B | A + ba truy vấn pháp lý viết sẵn | 129 | 2/2 | 1/2 | 0.20 | 0.50 | 0.2857 |
| C | A + ba search có feedback từ đọc nguồn | 132 | 2/2 | 0/2 | 0 | 0 | 0 |

Candidate-union recall 100% không là final-system recall: chỉ top5 là prediction đã khóa. Không dùng precision/F1 của toàn union trong JSON evaluator để báo chất lượng submission.

## Phạm vi và điều kiện thử

- Chỉ một query train-development `043625`; membership lấy từ registry trước khi đọc targets. Đây là query duy nhất trong các train-development IDs của registry hiện có thuộc danh sách train queries.
- Candidate pool local gồm 7708 train documents, loại query self theo ID. Đây là development protocol, chưa chứng nhận candidate eligibility của run dự thi.
- Index BM25 lexical-only: k1=1.5, b=.75, query term presence binary, tokenizer/stopwords đã khóa; giữ `not` và `or`. Không dense embeddings, AU, graph hoặc reranker neural mới.
- Corpus/index runtime không đọc nhãn. Protocol và truy vấn B được ghi trước khi đọc search results; toàn bộ A/B/C predictions được đóng thành bundle trước khi evaluator mở train target labels. Không đọc test content/labels.
- Controller C là Main trong chat thực sự chọn local tools theo observations. Không là mocked LLM response; cũng không là hệ autonomous bằng model công khai đủ điều kiện COLIEE. Chat controller token/request/latency không có telemetry đầy đủ, phải ghi unknown.
- Baseline top100 và final top5 là diagnostic policy đã chốt trước targets, chưa hiệu chỉnh. B/C dùng cùng RRF công thức: baseline weight1 + mean generated-search rankings weight1, constant60. Search-history features khác nhau nên thí nghiệm gộp reformulation/discovery/query-fusion, chưa cô lập adaptive-discovery gain.

## Những gì thực sự được xây

Package [bounded_retrieval_trial](../bounded_retrieval_trial/README.md):

- `core.py`: index BM25 sparse CPU; search cases/passages; mở source bằng hash và exact codepoint offsets; bounded session, journal, freeze/fallback.
- `__main__.py`: build/init/action/freeze/show, không client model/network.
- Index và session roots chỉ dưới `research_bundle/bounded_retrieval_trial`; nguồn là train cases hoặc fixture synthetic trong subtree đó.
- Giới hạn sáu non-stop actions và ba generated case searches. Duplicate/invalid action không mutate journal. Hết cap hợp lệ giữ discoveries; fallback chủ động trả baseline.
- Raw source và historical artifacts không sửa. `index_v1` tạo trước khi tokenizer profile được bổ sung binding, giữ nguyên nhưng không dùng trong actual session. `index_v2` là profile dùng cho mọi A/B/C prediction.

Index v2: 7708 documents, vocabulary 96830, build 38.188 giây.
Index SHA256: `b2c64df4e18d650a3d9117d244e26ae72c4f953ad701db5a2ee91349261c9503`.
Build v1 trước đó: 40.281 giây; không giấu lần build này trong chi phí chuẩn bị.

## Trace C đã thực hiện

1. Search theo điểm công bố thông tin mật/khả năng trả lời cáo buộc; trả top20.
2. Mở nguyên văn passage của ba candidates đầu để so sánh thay vì chốt top1.
3. Search passage trong `065387` để làm rõ context/authority. Kết quả cho thấy nhiều câu rất gần query; đây chưa đủ chứng minh candidate là noticed case.
4. Từ observations, đổi truy vấn sang `Demaria penitentiary choir school disclosure substance information informant blanket claim`; không có query này trong B predeclared list.
5. Chuyển sang point mootness/annual review để tránh chỉ xét một legal point.
6. Mở thêm ba passages, chạm cap và freeze theo `budget_stop`.

Tổng C: ba case searches, một passage search, hai batch open; sáu passages nguyên văn, 6216 ký tự source. Final observations của action6 chỉ được Main đọc sau khi host đã freeze; chúng không cập nhật score và không tạo thêm action/model call miễn phí. Status là budget-stop, không phải đã đọc hết query hay xác nhận đủ legal points.

Top5 đã khóa:

- A: `065387, 028494, 078017, 077675, 067093`.
- B: `065387, 078017, 056205, 057969, 045835`.
- C: `065387, 045835, 078017, 065909, 079008`.

Sau freeze, evaluator mới mở targets: `085382, 057969`.

| Target | A rank trong pool | B rank | C rank |
|---|---:|---:|---:|
| 085382 | Không trong top100 | 104 | 48 |
| 057969 | 7 | 4 | 6 |

Không đổi top-K, search queries hay weights sau khi thấy các thứ hạng này. Query hiện đã exposed và không được dùng như blind confirmation ở lần sửa policy sau.

## Bài học mới từ actual run

**Khám phá và chọn cuối là hai vấn đề riêng.** `085382` ngoài baseline top100 nhưng xuất hiện hạng5 trong search đầu; cả B và C đã thu hồi nó. RRF cuối vẫn đặt nó hạng104/48. Candidate discovery có tín hiệu hữu ích trên ca này; selection/query fusion chưa chuyển được tín hiệu thành prediction.

**Fusion thử nghiệm có thiên lệch cấu trúc chống ứng viên mới.** Với ba searches, một candidate mới chỉ xuất hiện ở một search có điểm tối đa `1/(3×61) ≈ .00546`, thấp hơn điểm tối thiểu của mọi baseline top100 là `1/160 = .00625`, ngay cả khi baseline case không xuất hiện trong search bổ sung nào. Vì thế candidate kiểu này không thể vượt baseline top100 theo công thức đã khóa. Đây là lỗi lựa chọn policy fusion của prototype, không là bằng chứng agent đọc hiểu kém hay adaptive retrieval vô ích. Cần đối chứng fusion không áp trần này hoặc scorer độc lập trên queries mới; không sửa alpha/top-K trên ca đã xem nhãn rồi báo lại như kết quả blind.

**Lặp cùng chủ đề/đoạn quote không phân biệt được noticed relation.** Nhiều candidates trả cùng đoạn về confidential information. Việc tăng trọng số theo số truy vấn cùng một point có thể khuếch đại các án lặp doctrine thay vì án query thực sự viện dẫn. Đây là giải thích cơ chế phù hợp trace, chưa có ablation nhân quả.

**Có near-duplicate theo nội dung ngoài self-ID.** `065387` đứng đầu cả ba arms nhưng không thuộc hai targets. Chẩn đoán sau freeze cho thấy 98.56% unique word-5grams của query xuất hiện trong candidate, Jaccard 90.26% sau lowercase ASCII tokenization. Raw hashes khác nhau nên kiểm exact duplicates trước đây không phát hiện trường hợp này. Cần kiểm case identity/phiên bản và protocol trước khi thiết kế chống near-duplicate; không tự loại mọi near-duplicate hay sửa gold để cải thiện điểm.

**Passage ranking có thể chọn mẩu quá ngắn.** Search về mootness trả một snippet chỉ là tiểu mục luật `c) order a new review...`; nó có từ khóa nhưng chưa giúp phân biệt mootness. Source splitting đúng offsets không đủ chứng minh passage hữu dụng. Nên kiểm passage grouping/context expansion trên dev ở vòng thiết kế tiếp.

**Adaptive policy này chưa thắng fixed queries.** C dành hai search vào disclosure, còn B dành một search riêng cho deference. Hai policy phân bổ attention khác nhau và dùng tài nguyên khác; không thể quy chênh lệch chỉ cho model, tool loop hoặc một câu search. Không mở rộng workload theo giả định agent tốt hơn.

## Kiểm thử, accounting và giới hạn

Tester độc lập chạy `.venv/Scripts/python.exe -m unittest tests.test_bounded_retrieval_trial -v`: **13/13 PASS**, 0.64 giây trên code cuối. Bao phủ synthetic ranking/self exclusion/ties, CRLF/codepoint/hash, exact bounded partition, forged handles/source drift/path escape, invalid actions không mutate, normalized duplicate search, caps, RRF, freeze/replay/fallback và event tamper. Đây là kiểm local invariants, không chứng nhận semantic relevance hay end-to-end quality.

Main kiểm metric evaluator bằng fixture positive/empty/duplicate trước mở nhãn; đúng P/R/F1 và duplicate rejection. Real evaluator chạy sau frozen bundle. Implementer kiểm compile, CLI help, synthetic smoke, source/index revalidation. Không chạy lại các tests cũ không liên quan.

Tester còn audit actual artifacts: seals/index/baseline identity, tính lại RRF và P/R/F1, xác minh sáu spans với raw source. Audit phát hiện diagnostic v1 đếm source chars sai hai ký tự do script chẩn đoán đọc event UTF-8 bằng default Windows encoding. Main xác nhận, giữ v1 và tạo diagnostic v2 explicit UTF-8; runtime vốn dùng UTF-8 rõ ràng, source delivery/predictions/metrics không bị đổi.

- External provider inference requests: **0**; deploy: **0**. Controller chat usage/billing: **unknown**, không ghi token0 hoặc free.
- B: ba local search actions; C: sáu local actions. Logged action-body seconds B=.624, C=.532, không gồm index/session reload, process startup hoặc chat controller. Chúng không là end-to-end latency và không chứng minh C nhanh/rẻ hơn.
- B command wall 9.125s; tổng các command invocations C khoảng19.3s, chưa gồm thời gian reasoning/đọc của controller. Hai cách gọi process khác nhau nên không benchmark throughput/latency từ các con số này.
- Một query, BM25 baseline cụ thể, top5 chưa calibrated, không paired uncertainty, không holdout mới và không open-model autonomous runner. Chưa có kết luận chất lượng corpus hay khả năng dự thi.

## Artifacts và tái hiện

Protocol: `research_bundle/bounded_retrieval_trial/protocol_043625_v1.json`.
Sessions: `fixed_043625_v1/`, `adaptive_043625_v1/` cùng root.
Predictions: `predictions_043625_v1.json`, SHA256 `d670008f12e8b537da4e4e30f3c251d50ca5d749629a5379e2d49c38d8ec0585`.
Evaluation: `evaluation_043625_v1.json`; diagnostics/ranks/source similarity/producer hashes: `diagnostics_043625_v2.json` (v1 giữ nguyên với correction provenance ở v2).
Post-freeze evaluator: [evaluate_bounded_retrieval_trial.py](../experiments/evaluate_bounded_retrieval_trial.py).

Build/init/action/freeze instructions ở package README. Existing artifact roots write-once; không chạy lại fixed-arm script vào cùng root hoặc sửa prediction. Re-evaluation để kiểm lại dùng output path mới; không cần inference hoặc index rebuild.

## Quyết định sau thử

Giữ prototype và công cụ nguồn; **chưa mở rộng agent**. Ưu tiên sửa thiết kế fusion bất lợi cho án mới bằng phép thử mới, kiểm passage/context và một scorer query–candidate chung có khả năng phân biệt near-duplicate/quote echo với noticed relation, trước khi tăng số vòng agent hoặc thêm graph/AU. Việc thay/chuẩn bị scorer phải là thí nghiệm mới được mô tả rõ, không sửa kết quả lần này.

Nếu thử tiếp trên queries khác, khóa policy trước và dùng train-development chưa exposed; so fixed-query với adaptive trên cùng điều kiện scoring. Chỉ đầu tư autonomous open-model adapter sau khi quyết định rõ phép thử nó cần phân xử. Đây là hướng tiếp theo từ evidence, chưa triển khai hoặc cấp inference scope trong báo cáo này.
