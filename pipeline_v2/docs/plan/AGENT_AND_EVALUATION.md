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

### 1.1. Giao diện tool theo mục đích của controller

Các action ở mục 1 là công cụ nội bộ. Khi thiết kế giao diện cho controller thích ứng, dùng tên theo quyết định nghiệp vụ và ánh xạ về công cụ M3/M4 đã nghiệm thu. Mỗi tool có mô tả ngắn về lúc dùng, lúc chuyển sang tool dễ nhầm, tham số model cần chọn và ý nghĩa kết quả. Thêm ví dụ đúng và ví dụ dễ nhầm khi định dạng hoặc ngữ cảnh ảnh hưởng đến kết quả. Chỉ đưa mô tả và schema của các tool khả dụng trong lượt hiện tại. [OpenAI tool choice](https://developers.openai.com/api/docs/guides/function-calling#tool-choice) · [Claude tool definitions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)

| Tool dự kiến cho model | Khi nào khả dụng và model chọn gì | Host thực thi và trả gì |
|---|---|---|
| `search_cases_by_issue(issue)` | Có vấn đề pháp lý cần tìm ứng viên. Model viết cụm tìm theo ngữ cảnh A. Khi đã có chuỗi viện dẫn nguyên văn và cần xác định đích, dùng nhánh tra viện dẫn. | Dùng `search_corpus` với retriever, kênh, giới hạn và dedup theo profile. Trả các án ứng viên, preview và ref để mở nếu có. Preview là tín hiệu truy hồi. |
| `find_citation_matches(citation_ref)` | Có ref tới một citation nguyên văn trong đoạn A đã giao. Model chọn citation đang cần tra. | Host lấy đúng chuỗi từ nguồn đã bind hash và dùng `search_identity` hoặc `search_phrase` để tìm dấu vết văn bản. Trả ứng viên, vị trí khớp và độ phủ. Kết quả hiện hành là quan sát. Tên `resolve_case_citation` và trạng thái `resolved` dành cho bước có quy tắc xác minh danh tính đích. Nhiều đích còn hợp lý thì giữ `ambiguous`, thiếu căn cứ thì giữ `unresolved`. |
| `read_case_passages(candidate_ref, focus)` | Đã có ứng viên trong state và cần tìm đoạn về một vấn đề cụ thể trong án đó. Model chọn ứng viên và trọng tâm đọc. | Dùng `search_case` trong đúng án rồi mở đoạn theo policy đã khóa. Nếu hit đã có `open_ref` thích hợp và bước mở là bắt buộc, host gọi `open_source` trực tiếp. Trả raw text, refs, byte spans, provenance và phần còn chờ. |

Model chọn vấn đề, citation hoặc ứng viên cần đọc sâu. Host giữ retriever, `top_k`, cap lượt, budget, source hash, offset và ánh xạ ref trong run. Nếu hợp đồng ngoài cần `case_id`, chỉ chấp nhận án có trong state và kiểm nó khớp với ref đã cấp. Citation ref phải trỏ tới nguồn A đã giao trong payload. Áp dụng bộ lọc action theo mục 2.1 trước khi sinh và kiểm lại tham số theo state trước khi chạy tool. Lịch tìm/đọc cố định của M5 vẫn do host điều phối. Lượt nghiệm thu M4 dùng phần giao diện phù hợp với lịch một hit. Khi chỉ có một `open_ref` được phép, model gọi `read_case_passages` với args rỗng và host điền ref đã xác minh. Các lựa chọn tra citation và chọn trọng tâm đọc thuộc giao diện thích ứng.

Trên discovery, dùng fixture có tập action và tham số chấp nhận được theo trạng thái. Bao gồm vấn đề chưa có citation, citation mơ hồ, ref từ án khác, candidate chưa được cấp và hit đã mở được. Báo tỷ lệ chọn đúng tool ở lượt có lựa chọn, tỷ lệ tham số đúng ngữ cảnh, lỗi schema, số lượt và token. Với bước host ép hoặc chạy trực tiếp, báo mức tuân thủ riêng. Đo chất lượng truy hồi và quan hệ A→B trên gold theo các mục 5–6.

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

### 2.1. Ràng buộc đầu ra và kiểm bằng chứng cho M4/M5

M4 định nghĩa contract assessment dùng chung và áp dụng ba lớp dưới đây. Khi M5 bắt đầu assess các hồ sơ từ lịch cố định, dùng cùng contract và validator với M4. Hồ sơ chỉ có điểm retrieval giữ `case_relation=unknown` và chờ bằng chứng.

1. **Ràng buộc lúc sinh.** Khai báo tổ hợp hợp lệ theo nghĩa của từng trường. Nếu `type` chỉ có nghĩa sau khi biết `role`, schema phân nhánh theo `role`. Nhánh `unknown` bỏ `type`, các nhánh có role xác định chỉ nhận type tương ứng. Giữ riêng các trục độc lập như `case_relation` và `passage_location`. Ví dụ `unknown` đi cùng `pinpoint` khi đã định vị được đoạn nhưng còn thiếu căn cứ về quan hệ A→B. Gửi schema vào structured decoding của engine, dùng schema theo nhánh kiểu discriminated union khi các nhánh có tập trường khác nhau. Model chỉ sinh nhãn, refs và nhận định cần suy luận. Host điền ID, phiên bản, raw quote và offsets từ dữ liệu đã xác thực. [Pydantic unions](https://docs.pydantic.dev/latest/concepts/unions/) · [vLLM structured outputs](https://docs.vllm.ai/en/v0.19.1/examples/offline_inference/structured_outputs/)
2. **Kiểm tất định trước khi ghi assessment.** Host kiểm lại schema, các quy tắc liên trường và các ràng buộc theo state. Refs phải thuộc raw text trong payload hiện tại, đúng vai trò A/B, đúng nguồn và provenance. Quy tắc về speaker, container hoặc quote chain dùng refs tương ứng khi kết luận phụ thuộc vào chúng. Các kiểm tra phụ thuộc state chạy trong validator ứng dụng. Assessment qua các kiểm tra này vẫn cần đối chiếu bằng chứng có nhãn khi đánh giá đúng sai về attribution và quan hệ pháp lý. [Pydantic model validators](https://docs.pydantic.dev/latest/concepts/validators/)
3. **Điều phối theo kết quả kiểm.** Chấp nhận assessment hợp lệ. Nếu thiếu nguồn thì giữ hồ sơ ở trạng thái chờ bằng chứng, ghi phần thiếu và chỉ mở thêm nếu lịch/budget cho phép. Nếu output sai schema, mâu thuẫn giữa các trường hoặc viện dẫn ref sai, ghi lỗi vào ledger và từ chối assessment đó. Dùng fallback đã khóa khi đủ điều kiện. Mặc định 0 lần gọi model để sửa các lỗi này. Retry lỗi transport/provider vẫn theo quy tắc ở mục 4. [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output) · [LangGraph workflows](https://docs.langchain.com/oss/python/langgraph/workflows-agents)

Khóa phiên bản schema và validator cùng model, prompt và ngân sách. Dùng cùng bộ kiểm cho fixture, replay và adapter live để đối chiếu tỷ lệ đạt ở lần đầu.

Trước mỗi request có tool, host xác định action khả dụng từ trạng thái đã xác minh và payload sẽ giao. Engine nhận schema chỉ gồm các nhánh khả dụng. Host kiểm lại action theo chính schema của lượt đó trước khi thực thi và ghi policy cùng schema fingerprint vào hồ sơ run. Lượt nghiệm thu M4 một cặp giới hạn theo thứ tự tìm một hit → mở nguồn → nạp lại raw refs nếu cần → assessment → dừng. Hit có `open_ref` khóa nhánh tìm lại. Assessment cần raw refs A/B trong payload hiện tại. M5 dùng lịch tìm và mở nguồn đã cố định rồi mới chuyển hồ sơ sang assessment.

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
- Tổ hợp phụ thuộc bị cấm như `role=unknown` kèm `type` chỉ có nghĩa khi biết role. Tổ hợp độc lập hợp lệ như `case_relation=unknown` và `passage_location=pinpoint`. JSON đúng schema nhưng ref sai án, sai provenance hoặc chưa được giao.
- Hồ sơ chỉ có retrieval, hồ sơ thiếu bằng chứng và output bị validator từ chối đều đi đúng nhánh đã định. Assert số request sửa output bằng 0 và ledger ghi đúng lý do.
- Lỗi output/unknown provider receipt; resume giữ caps; duplicate action; cache stale.
- Last open chưa giao; budget stop; fallback; aggregation cùng B qua nhiều context.
- Metric perfect/empty/FP/FN; gold ngoài pool; query lỗi không biến mất.

Không đánh dấu live agent ready từ FakeTransport hoặc CLI tool tests. Live adapter và source evidence selector là phần mới phải được nghiệm thu riêng.

Trước khi so mô hình, kiểm schema theo nhánh trên đúng model/engine/backend bằng fixture có nhánh hợp lệ và prompt cố yêu cầu tổ hợp cấm. Dùng cap token, timeout và 0 retry sửa output. Canary schema đơn giản chỉ xác nhận đường gọi structured decoding. Báo tỷ lệ qua schema lần đầu, tỷ lệ qua validator theo state, tỷ lệ chờ bằng chứng và lỗi theo loại, kèm requests, tokens và latency cả lượt lỗi. Đo độ đúng về attribution/quan hệ A→B riêng trên mẫu có nhãn.

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
