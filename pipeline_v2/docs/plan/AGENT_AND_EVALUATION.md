# Contract dự kiến: agent, final selection và đánh giá

Trở về [kế hoạch](README.md). Đây là thiết kế chưa triển khai.

## 1. Input và các trách nhiệm

Input runtime: query source hash, candidate/index/profile manifests, model/prompt/tool versions và budget. Không cấp gold, citation map V3, báo cáo đã mở nhãn hoặc tên nguồn được khôi phục từ web.

Một controller nhận source map của A, đọc toàn văn hoặc điều hướng theo chunks khi không vừa input. Lưu phần thực sự được giao, phần bị cắt/chưa đọc. Tạo source needs quanh citation cues **và mệnh đề pháp lý không có marker**. Một need có thể dẫn nhiều candidate; một candidate có thể liên quan nhiều need.

Controller được chọn:

| Action | Contract |
|---|---|
| `search_corpus(intent, channel, text, limit)` | Search toàn universe; preview không phải evidence đã đọc |
| `search_case(case_id, text)` | Search query/candidate đã biết bằng lexical/literal/layout views |
| `open_source(handles)` | Host kiểm hash và dựng raw text; trả heading/container/language/continuation refs |
| `expand_source(handle, direction/target)` | Mở parent, vùng trước/sau, heading, quote attribution hoặc vùng xa |
| `assess_links(context, candidates, source_refs)` | Kết luận có support/counterevidence/unknown; chỉ cite refs đã được giao |
| `stop(reason)` | Dừng hợp lệ, phân biệt complete-policy, budget, no-progress, failure; không chứng nhận corpus completeness |

Policy đọc sau passage hit theo [contract nguồn Section 3.4](SOURCE_CHUNK_INDEX.md): hit `12b` mặc định mở **toàn paragraph cha `[12]` và hai paragraph lân cận `[11]`, `[13]`**, không chỉ trả đoạn nhỏ đã embed. Lân cận lấy theo vị trí trong cùng nguồn, không theo phép cộng/trừ marker. Host giữ rõ hit spans/score và parent/context mở rộng; nhiều hit cùng parent dùng chung vùng đọc đã dedup, không thêm case votes. Context vượt payload cap được chia phần với requested/delivered/pending refs và continuation, không coi context chưa giao là đã đọc. Mapping được chuẩn bị ở M2; search/fetch/delivery thuộc M3–M4.

Đầu vào query theo [Section 3.5 của contract nguồn](SOURCE_CHUNK_INDEX.md): query vừa ngân sách agent có thể đọc toàn văn; query dài nhận bản đồ với handle/heading quan sát/preview nguyên văn/signals/role, context ưu tiên rồi tự mở thêm. Không lặp `Open: ...` từng dòng. `open_query(handle)` là action dự kiến của agent; response do host dựng từ raw parent và hàng xóm. Navigation/preview/anchor records bất biến do M2 chuẩn bị; delivery/coverage là state từng run của M4. Bản đồ phân trang giữ tổng số mục và quyền truy cập phần chưa hiển thị. Không dùng placeholder làm bộ lọc duy nhất; chưa đọc không phải negative. Tokenizer/budget agent và tokenizer embedding là hai profile riêng; chưa chốt thì không tự đặt ngưỡng dài/ngắn bằng số ký tự.

Khi cần so nguồn cạnh tranh, cấp cùng context A và một nhóm nhỏ B có nguồn đã mở; không bắt một winner. Missing context có next action cụ thể, không vòng reasoning tự do không thêm evidence.

## 2. Hồ sơ liên kết gọn

```text
link_hypothesis_id, query_id, source_need_id, candidate_id
A_context_refs, B_passage_refs, identity_support_refs
speaker_status + evidence_refs
container_id, quoted_marker, quote_chain_refs
case_relation: supported | plausible | similarity_only | contradicted | unknown
passage_location: pinpoint | bounded | unresolved
reason, counterevidence, missing_evidence, version
```

Host materialize raw quote/offsets, model không tính số ký tự. Không bắt soạn doctrine/AU tự do. Không nhận một câu “verified” làm bằng chứng; mỗi kết luận phải gắn refs và giới hạn.

Source identity, passage pinpoint và legal relevance là các trục khác nhau. Một candidate chưa định vị được passage vẫn có thể là noticed. B trích C không tự loại B; A/B cùng trích C cũng không chứng minh A→B. Lời đương sự, adopted reasoning và quotation phải tách rõ, không ép mọi nguồn thành holding của B.

## 3. Final selector và baseline

- Giữ baseline độc lập được sinh trước vòng agent, có prediction policy đã calibrated trong discovery; top5 cũ chỉ là diagnostic.
- Aggregate unique `(query,candidate)`: giữ evidence mạnh/yếu/mâu thuẫn từ các context, không đếm một quote lặp thành nhiều chứng cứ.
- Final scorer nhận cùng pair/evidence/profile phải áp cùng policy, không thưởng candidate vì được tìm nhiều lần hay có mặt baseline. Có thể dùng retrieval signals cùng source hypotheses; model confidence không mặc định là xác suất calibrated.
- Số noticed biến thiên. Chốt rule/threshold trên discovery; không gạt unknown tự động, không ép một candidate/context. Đo ảnh hưởng final selection riêng thay vì chỉ báo union recall.
- Nếu controller lỗi, dùng baseline fallback đã khóa; lưu lý do và chấm query đó trong end-to-end denominator. Candidate union giữ baseline không có nghĩa final F1 được bảo đảm.
- Targeted reviewer khi attribution/voice/source conflicts hoặc pair sát cutoff; có audit mẫu cả phần không trigger. Reviewer đưa finding/ref, không chỉ agree; reviewer không là human gold và không sửa vô hạn.

## 4. State, delivery và lỗi

State: query source needs; observed/unread source; candidate union; source basket; assessment revisions/dependencies; usage; pending operations; frozen prediction.

Vòng hợp lệ: action → tool execution → observation queued → model lượt sau nhận observation → assessment. Không cite nguồn mới chỉ được yêu cầu trong cùng lượt. Nếu hết cap sau open cuối, hoặc dành lượt đọc đã dự toán, hoặc đánh dấu observation unread; không tính như đã tác động prediction.

Mỗi lượt assess hoặc quyết định cuối phụ thuộc nguồn phải nhận lại raw excerpts liên quan trong payload hiện tại, hoặc thực hiện reload trước khi quyết định. Host ghi `current_payload_source_refs` và phần bị lược/cắt. Lịch sử đã đọc, cache hoặc source notes không thay raw evidence khi text đã rời context; token đọc lại vẫn được hạch toán.

Run namespace write-once, attempt events append-only; source/index/profile/model/prompt fingerprints đầy đủ. Model output mới không overwrite history. Source/context đổi phải invalidate assessment phụ thuộc; không dùng semantic cache với evidence cũ khác input.

Admission ghi trước send, response/unknown timeout được phân biệt; recovery không tự gửi duplicate request hoặc reset budget. Retry chỉ cho lỗi transport/provider retryable trong cap đã khóa; malformed/schema/semantic failures không tự repair miễn phí. Chiến lược repair nếu thử phải là policy version riêng.

Tính đủ controller/selector/reviewer/embedding requests, tokens, latency, lỗi, retry, repeated source và fallback. Unknown telemetry là null; local CPU time, readiness và model latency không gộp tùy ý.

## 5. Nhánh thử nghiệm

### 5.1. Kiểm local trước live model

Tạo fixtures/replay cho:
- Query dài/reading bị cắt, nguồn song ngữ, quoted paragraph trùng số.
- Zero hits; wrong/missing candidate; chưa mở hit mà cite; source hash drift.
- Lỗi output/unknown provider receipt; resume giữ caps; duplicate action; cache stale.
- Last open chưa giao; budget stop; fallback; aggregation cùng B qua nhiều context.
- Metric perfect/empty/FP/FN; gold ngoài pool; query lỗi không biến mất.

Không đánh dấu live agent ready từ FakeTransport hoặc CLI tool tests. Live adapter và source evidence selector là phần mới phải được nghiệm thu riêng.

### 5.2. Retrieval-only

So case BM25, passage BM25, dense passage và hybrid ở cùng unique-case K/profile. Báo recall@K, recall union trước cap, recall pool sau cap, số chunks/index size/build latency/embedding cost. Retrieval-only không gọi thêm LLM đọc nguồn, nhưng embedding/index build vẫn phải hạch toán và đúng authorization.

Baseline chunk dùng chung; thử tối đa một variant để biết tác động segmentation/context. Không đồng thời thay model, chunking, query formulation và fusion rồi quy gain cho embedding.

### 5.3. Tách discovery khỏi reading

**Discovery comparison:** fixed source-centric search với adaptive search; cùng channels/tools/model profile, trần budget và final scorer. Mọi finalist pair qua cùng evidence-acquisition policy phụ thuộc `(A,B)` chứ không đường discovery. Báo cả usage thực; cùng cap không đồng nghĩa equal-cost.

**Reading comparison:** khóa candidate pool, so fixed passages với adaptive open/expand. Cùng final scorer và budget; kết quả chỉ giải thích đọc evidence, không tự chứng minh corpus retrieval.

Baseline cố định phải có decomposition/context queries và toolbox hợp lý, không chỉ BM25 toàn văn yếu. Không bật nhiều reviewer hoặc graph để adaptive có thêm compute không được báo.

## 6. Split, freeze và chấm

- Nhập exposure history của rule study (cả 40 query), các pilot/source batches, `043625`, KOS/calibration và các run đã dùng gold/test. Không đụng test labels; không đổi registry reserved holdout cũ.
- Sample theo eligibility và exposure trước khi xem chất lượng retrieval; dedupe/group các quyết định trùng identity nếu xác minh được, không chỉ raw hashes. Không xóa near-duplicate candidates khỏi corpus chỉ để tăng điểm; báo shared-case dependencies giữa query splits.
- Cohort feasibility 20 query (10 discovery/10 holdout), chưa bảo đảm tính đại diện/power. Dành holdout cho một lần xác nhận bộ policy đã khóa. Nếu phải sửa sau đó, đánh dấu exposed và dùng cohort mới khi được mở scope.
- Freeze corpus/candidate universe, chunk/tokenizer, model/embedding inputs, indices, prompts, tools, budgets, fusion, evidence policy, scorer/cutoff và predictions trước khi evaluator mở holdout gold.
- Gold evaluator tách khỏi solver inputs/access. Hash hay cờ `gold_accessed=false` không chứng minh lịch sử mù; báo đúng cách ly thực tế và lưu tool trace nếu có.

Metric chính:

1. Micro-P/R/F1 trên unique query–candidate, **toàn bộ gold**, gold ngoài pool là FN.
2. Candidate recall trước/sau caps; gold tìm được nhưng rơi ở selector; false positives do same-doctrine/quote echo.
3. Error/fallback/partial/budget-stop rates; không chỉ chấm runs thành công.
4. Tất cả chi phí actual, kể cả embedding/scorer/reviewer/lỗi/retry và phần không quan sát được.
5. Context-source diagnostics về actor/pinpoint/route tách riêng. Không lấy 40 context records làm 40 cặp document duy nhất hoặc gọi model annotations là passage gold.

Nếu báo macro, nêu zero-denominator convention và sensitivity; không dùng empty/empty=1 để diễn giải khả năng tìm gold. Báo paired per-query differences/uncertainty đúng cỡ mẫu; không chọn winner chỉ từ một case.

## 7. Go/no-go và bàn giao

- Giữ dense/hybrid nếu có lợi recall/F1 hoặc economics theo objective đã khóa; không giả định semantic luôn thắng lexical.
- Giữ adaptive nếu có lợi chất lượng hoặc chi phí ở chất lượng tương đương so với fixed source-centric baseline. Chưa rõ thì báo chưa đủ evidence, không coi không-significant là tương đương.
- Union recall tăng nhưng final F1 không tăng: điều tra selector/evidence trong phép thử riêng, không mở graph/agent count để chữa chung.
- Không chỉnh gold, không biến case-source unresolved thành annotation-noise đã xác nhận.

Bàn giao khi thực thi: protocol/profile manifests; source/chunk/index inventories; frozen predictions và hashes; complete attempts/delivery ledgers; metric JSON; report sinh từ JSON; error examples có raw refs; giới hạn và quyết định bước tiếp. Báo cáo không dùng câu viết tay trái với artifact cuối.
