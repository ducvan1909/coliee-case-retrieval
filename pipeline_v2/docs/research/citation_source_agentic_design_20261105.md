# Đề xuất hệ thống agentic truy nguồn citation cho COLIEE Task 1

Ngày: 05/11/2026. Checkout: `E:/Git/coliee-case-retrieval`.
Trạng thái: đề xuất thiết kế; chưa sửa runtime, chạy inference, deploy hoặc mở workload.

## 1. Quyết định đề xuất

**Giữ truy hồi cơ sở, thêm một agent tìm–đọc–đối chiếu nguồn theo ngữ cảnh; đầu ra evidence phải được bước chọn án thực sự sử dụng.** Agent tự chọn hành động tiếp theo trong ngân sách, không buộc mọi query qua cùng số lượt hoặc phải tạo AU đầy đủ.

Đơn vị làm việc là **một nhu cầu tìm nguồn trong query**, không phải toàn bản án bị nén thành một embedding hoặc một bản tóm tắt. Kết quả cuối vẫn là tập noticed case IDs ở cấp query–candidate.

[Task 1 chính thức](https://coliee.org/COLIEE2026/tasks/task1) định nghĩa noticed theo quan hệ được query viện dẫn. [Đánh giá chính thức](https://coliee.org/COLIEE2026/evaluation) dùng micro-P/R/F1. Nhãn chuẩn vẫn quyết định điểm; sự hợp lý pháp lý và độ đúng của hồ sơ nguồn là diagnostic riêng.

Đây là kiến trúc để kiểm chứng, chưa có bằng chứng thắng pipeline cố định.

## 2. Bài học thực tế dẫn tới thiết kế

| Quan sát | Hệ quả thiết kế |
|---|---|
| Batch V3 xác định lại Baron/Mizani/Ghaedi nhờ vị trí citation trong A | Lập giả thuyết nguồn tại A trước, rồi tìm đoạn B; không lấy đoạn B giống nhất để suy ngược nguồn |
| Phần lớn kết quả V3 của Abdallah có citation index hỗ trợ | Tách discovery mở gold/nguồn ngoài khỏi runtime corpus-only; không coi 18/19 là accuracy hoặc khả năng giải khi bị che |
| Một đoạn A viện dẫn nhiều B; B có thể trích C | Quan hệ nhiều–nhiều; tách A→B với B→C; không loại mọi nguồn trung gian |
| Nhầm lời đương sự, số đoạn lồng, danh tính và bản song ngữ | Giữ heading, voice, quotation container, language, identity evidence; model không tự tính offsets |
| BM25 top30 của mẫu rule study chỉ có khoảng 30% gold | Tìm ở cấp passage/nguyên tắc và nhiều search intent; không coi top30 là trần cứng cho mọi query |
| Trial 043625 đã tìm thêm gold nhưng final RRF không đưa nó lên | Tách discovery với selection; không để lịch sử search/baseline rank quyết định thay evidence |
| Packet thiếu context và tool result từng chưa tới lượt model tiếp | Có open/expand, delivery ledger; search preview hoặc nguồn chỉ mới yêu cầu không được dùng làm evidence |
| Reviewer trước có thể đồng thuận với diễn giải sai | Review phải đưa source support/counterevidence; agreement và schema PASS không là chứng nhận ngữ nghĩa |

Nguồn: [tiêu chí noticed](../NOTICED_CASE_CRITERIA.md), [V3](../coliee_task1_verified_gold_passages_v3/REPORT.md), [trial 043625](bounded_agentic_retrieval_trial_20261104.md), [causal audit](au_pipeline_causal_audit_20261031.md), [thiết kế bounded trước](bounded_agentic_retrieval_design_20261104.md).

## 3. Luồng vận hành

```text
Query + candidate manifest
  ├─ Truy hồi cơ sở → baseline độc lập
  └─ Đọc query/lập nhu cầu nguồn
       → tìm toàn corpus → union ứng viên
       → mở đoạn A/B, mở rộng ngữ cảnh
       → đối chiếu các nguồn cạnh tranh
       → hồ sơ nguồn + điều còn thiếu
       ↺ tìm/đọc tiếp nếu cần và còn ngân sách
  → đánh giá quan hệ query–candidate bằng evidence
  → chọn số án biến thiên theo policy đã khóa
  → niêm phong prediction → evaluator mở gold
```

Một controller cho mỗi query là đủ ở phiên bản đầu. Reader, searcher, verifier là các trách nhiệm logic; chưa cần ba model hoặc một agent cho mỗi candidate. Có thể batch công việc độc lập, nhưng mỗi quyết định vẫn phải giữ context nguồn riêng.

### 3.1. Nguồn và chỉ mục

- Giữ raw source bất biến, hash và handles. Index là view tìm kiếm, không thay văn bản gốc.
- Chỉ mục cơ sở ở cấp case; bổ sung **global passage search** để tìm đoạn trong case chưa biết ID. Chỉ dùng search passage trong case đã biết sẽ bỏ lỡ đúng vấn đề discovery.
- Có view cho nguyên tắc/ngữ cảnh citation, phrase và metadata quan sát được. Citation, tên thẩm phán, năm hoặc bản song ngữ là tín hiệu; missing metadata không tự loại candidate.
- Không tự lọc bằng “cùng topic stream”, Jaccard cao hoặc năm lớn nhất xuất hiện trong text. Duplicate identity, ngày quyết định và độ giống từ là ba thông tin khác nhau.
- Không cần AU toàn corpus, citation graph hoặc thay reranker ở bước đầu. Embedding/semantic channel là thí nghiệm bổ sung nếu lexical passage search còn thiếu recall.

### 3.2. Agent đọc query: xác định cần tìm nguồn cho điều gì

Đọc query theo structural map, có quyền mở toàn văn và vùng xa. Tạo `source_need` gọn:

- context handle trong A, heading/language;
- nội dung hoặc vấn đề cần nguồn, kèm nguyên văn;
- attribution/pinpoint/voice/quotation cues quan sát được;
- phần còn chưa rõ và search intent ban đầu.

Không đòi một AU hoàn chỉnh, không viết lại doctrine trước khi tìm. Voice do model suy ra phải có evidence và có thể unknown. Placeholder là cue, không phải ranh giới đầy đủ: phải xét cả đoạn không có marker, danh sách nhiều án và citation lồng.

Các source needs có thể gộp/tách sau khi đọc thêm. Coverage ledger phân biệt đã đọc, đã tìm, có ứng viên, còn mơ hồ và chưa khảo sát; không gọi “hoàn tất” chỉ vì mọi ô đều có tên.

### 3.3. Tìm và đọc thích ứng

Controller có các tool tối thiểu:

| Tool | Mục đích |
|---|---|
| `search_corpus` | Tìm cases/passages bằng vấn đề, phrase hoặc attribution; trả handles và preview |
| `search_case` | Tìm trong query/candidate đã biết, kể cả layout/suppression-tolerant search |
| `open_source` | Mở nguyên văn bằng handle, kèm heading/định vị và dấu phần bị lược |
| `expand_source` | Lấy antecedent, phần kết luận, paragraph container hoặc heading còn thiếu |
| `record_hypothesis` | Lưu liên kết tạm thời và evidence đã thực sự được giao |
| `stop` | Dừng có lý do; không đồng nghĩa chứng nhận đủ mọi noticed case |

Agent được đổi search từ nội dung pháp lý sang đoạn trích, thẩm phán hoặc tình tiết khi evidence cho thấy cần thiết. Không tìm lặp nhiều cách cho cùng một point trong khi các point khác chưa khảo sát mà không ghi lý do.

Union gồm baseline và ứng viên mới. Nếu cần cap, policy giữ/chọn ứng viên phải khóa trước, không ưu tiên mặc định toàn bộ baseline khiến án mới không thể vượt. Ghi recall trước/sau cap ở evaluator. Một candidate được tìm một lần vẫn phải có cơ hội được chọn bằng evidence mạnh.

Zero hits hoặc budget stop không biến candidate thành negative. Tool result phải vào lượt model tiếp theo trước khi được dùng; kết quả chưa giao phải đánh dấu unread. Khi cần đánh giá sau lần open cuối, phải còn ngân sách cho lượt đọc/ra quyết định đó.

### 3.4. Đối chiếu nguồn cạnh tranh

Với cùng một source need, đặt vài candidate gần nhau để đối chiếu, thay vì hỏi từng cặp “có liên quan không?”. Cho phép không chọn, chọn nhiều hoặc yêu cầu thêm context. Số candidate/batch là profile cần đo, không phải một hằng số chất lượng.

Hồ sơ tối thiểu:

```text
context_A_handle + candidate_case_id + passage_B_handles
case_attribution_support / counterevidence / unresolved
speaker + paragraph_container + quoted_paragraph + quote_chain
relationship_reason + missing_evidence + next_action
```

Host dựng quote/offsets từ handles. Giữ riêng **bằng chứng A→B** và **độ chắc chắn passage trong B**. Không bắt passage_verified mới được positive: references bị che có thể khiến không xác định được pinpoint dù B là gold. Ngược lại, câu trùng không tự xác nhận A→B.

Không yêu cầu B là tác giả đầu tiên của nguyên tắc. B→C không chứng minh A→B, nhưng cũng không phủ định A→B. Citation trong lời đương sự hoặc án bị phân biệt vẫn được xét, ghi đúng cách tòa xử lý.

### 3.5. Chọn án cuối

Đây là thành phần còn thiếu quan trọng của prototype hiện tại: **bước chốt phải đọc các hồ sơ nguồn**, không chỉ RRF các lần search.

- Một quyết định cuối cho mỗi `(query_id, candidate_id)`, tổng hợp evidence từ mọi context; không đếm trùng candidate hoặc bỏ các context mâu thuẫn.
- Phân biệt source-supported, plausible/unresolved, similarity-only và contradicted. Những mức này là model judgment, không phải xác suất đã calibrated.
- Dùng một scorer/selection contract chung có baseline features và evidence, khóa trên discovery trước khi đo. Ngưỡng chọn phải hiệu chỉnh bằng nhãn train; số noticed biến thiên, không dùng top5 chẩn đoán làm policy mặc định.
- Scorer nhận cùng dữ liệu phải cho cùng policy bất kể candidate được phát hiện sớm/muộn hoặc qua bao nhiêu lần search. Lặp cùng quote/point không tạo thêm phiếu độc lập.
- Unresolved không tự thành negative và vẫn được scorer xét. Hợp nhất baseline không bảo đảm F1 không giảm; khi controller lỗi có thể dùng baseline fallback đã khóa và chấm cả query lỗi.

Review riêng chỉ bật cho mâu thuẫn, attribution yếu hoặc các quyết định có ảnh hưởng lớn; thêm audit mẫu cả hồ sơ không bị trigger. Reviewer phải kiểm nguồn và nêu finding, không chỉ retain. Không mở vòng author→review→repair vô hạn.

## 4. Phân cách khám phá và runtime

| Khám phá/chuẩn bị | Runtime đo prediction |
|---|---|
| Được dùng gold, citation index hoặc án không che để hiểu/kiểm hồ sơ | Chỉ corpus và tools thuộc run manifest; không labels, hồ sơ gold-exposed, vLex hoặc bản khôi phục citation |
| Có thể tạo bộ diagnostic về actor/quotation/source confusion | Diagnostic không tự thành human passage gold hoặc holdout chưa exposed |
| Tài liệu semantic do model lập cần review | Annotation lưu trữ không thay raw evidence |

Giữ clues song ngữ vốn có trong corpus cho run chính nếu protocol cho phép; báo ablation che clues riêng để biết gain đến từ rò rỉ định danh hay khả năng đọc nguồn. Không trình bày gain index-assisted như corpus-only reasoning.

## 5. Tái dùng code và phần phải bổ sung

| Thành phần | Hiện trạng và hướng dùng |
|---|---|
| `bounded_retrieval_trial/core.py` | Có BM25 case/search trong case/open, sealed session và replay. Chưa có model client, global passage index hoặc scorer dùng evidence; giữ nguyên bản cũ làm diagnostic |
| `case_agent_c/navigation.py` | Có search/open/expand theo source handles và views giữ mapping; tái dùng qua adapter |
| `case_agent_c/session.py` | Có basket, pending và delivery ledger; dispatch hiện chỉ FakeTransport, không phải live runner sẵn sàng |
| AU/source stores | Tái dùng source identity và materialization nếu contract tương thích; không ép retrieval đi qua toàn bộ AU authoring/review |

Khi triển khai cần namespace mới cho controller contract/live adapter, global passage retrieval và final evidence scorer. Không sửa ngầm C/D hoặc kết quả lịch sử.

Hai module navigation/trial hiện dùng codepoint offsets; batch passage dùng UTF-8 bytes. Host phải sở hữu mapping char↔byte và language/quotation-aware source IDs, không đổi tên trường rồi coi hai đơn vị là một.

## 6. Ngân sách và state

Khóa profile gồm token/call budget, search/open caps, candidate/evidence caps, max review và retry trước run. Chọn số cụ thể sau preflight payload; không bê cap 6 action/3 search hoặc output 800 token từ thử cũ sang mọi query.

Agent được tự phân bổ trong cap; host chịu trách nhiệm admission, stop và resume. State lưu source needs, candidate union, evidence đã giao, hypotheses còn thiếu và decision revisions. Cache theo source/query/model/prompt/tool-profile hashes; kết luận semantic cũ không được dùng với context đã đổi.

Ghi request/token/latency cả lỗi, retry và nguồn đọc lặp. Tách cold readiness, tool time và model inference; telemetry thiếu là unknown, không phải 0. Không dùng self-report hoặc hash để chứng minh model đã đọc hiểu hoặc chưa từng thấy gold.

## 7. Phép thử tối thiểu để quyết định có triển khai tiếp

1. **Kiểm local không inference:** replay open→delivery→read, paragraph lồng/song ngữ, zero hits, source drift, duplicate identity, output lỗi, stop trước khi đọc observation cuối, budget/resume. Kiểm scorer bằng fixtures nhưng không coi đó là semantic test.
2. **Kiểm đóng góp discovery:** baseline raw; fixed source-needs/search; adaptive search. Cùng index, model/profile, cap và final scorer; mỗi `(A,B)` qua cùng policy lấy evidence để không trộn lợi ích tìm candidate với lợi ích đọc thêm.
3. **Kiểm đóng góp đọc nguồn:** khóa candidate pool, so fixed passages với adaptive open/expand, cùng scorer và ngân sách. Không dùng kết quả thí nghiệm này như end-to-end recall.

Bắt đầu cohort feasibility mới khoảng 10–20 train queries chưa dùng để chỉnh prompt; chốt exposure ledger, split và prediction trước evaluator. Số này chưa bảo đảm statistical power. Dữ liệu 19 cặp đã mở gold chỉ dùng diagnostic, không là xác nhận độc lập.

Metric chính: micro-P/R/F1 theo unique query–candidate trên toàn bộ gold, kể cả gold ngoài pool và queries fallback/lỗi. Báo candidate recall trước/sau cap, lost gold ở selection, mức cải thiện paired và chi phí thực. Nếu báo macro, công bố quy ước mẫu số 0 và số query rỗng; không dùng empty/empty=1 để quảng bá khả năng tìm gold.

Trên discovery làm ablation đủ để biết attribution, passage evidence, source reading và review có ích hay chỉ tăng chi phí. Không chỉnh bằng holdout rồi gọi đó là xác nhận. Adaptive chỉ đáng giữ khi cải thiện chất lượng hoặc giảm chi phí ở chất lượng tương đương so với fixed policy; nếu fixed tốt hơn/rẻ hơn thì giữ fixed.

## 8. Phạm vi đề xuất

Giữ một controller/query, source navigation thật, hồ sơ citation gọn và final selection dùng evidence. Hoãn nhiều agent runtime, all-corpus AU, graph, tự sửa nhiều vòng và đổi reranker. Các phần hoãn có thể được thử sau nếu phép đo chỉ rõ nút thắt.

Chưa có rollout hay paid inference được thực hiện trong công việc thiết kế này.
