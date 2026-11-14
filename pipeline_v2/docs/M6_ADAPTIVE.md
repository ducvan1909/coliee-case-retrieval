# M6: điều phối thích ứng trên M4

## RT3: bản đồ cấu trúc phân cấp của A (opt-in)

Profile mới có thể khai báo đầy đủ:

```json
"query_navigation": {
  "mode": "hierarchical",
  "max_children": 6,
  "leaf_bytes": 1024,
  "map_max_tokens": 2400,
  "snippet_chars": 96
}
```

Không có trường này thì giữ cách đọc bản đồ phẳng. Adapter
`HierarchicalM3Tools` trong `query_navigation.py` dùng raw/navigation/headings đã
khóa của M3; không thay source reader, chỉ mục, model hay ngân sách. Policy v8
bind config, source/case, cấu trúc và module mới; dùng namespace mới, không resume
run khóa bằng phiên bản cũ.

Map slot ban đầu đề xuất 1.600 token không giữ được literal preview cho mọi child
trong kiểm tra tokenizer thật: chỉ metadata span/hash đã vượt slot khi giữ sáu
child. Main điều chỉnh riêng slot bản đồ lên 2.400 token trong RT3. Tổng payload
vẫn tối đa 7.400, output/request/embedding caps giữ nguyên; đây không phải tăng
ngân sách tổng hoặc thay topology để che lỗi.

Cây interval lazy phủ `[0, len(raw))`, kể cả heading, khoảng trống và đuôi án không
có paragraph. Mỗi nút có tối đa `max_children`; ưu tiên ranh giới cấu trúc gần điểm
chia cân bằng, còn paragraph rất dài chia tại ranh giới UTF-8. Leaf hữu hạn theo
`leaf_bytes`. Ref vùng opaque chứa tree binding và đường đi tất định, có thể resolve
trên tiến trình mới, từ chối source/config/case khác hoặc đường dẫn không tồn tại.
Mỗi vùng ghi byte length, số paragraph giao vùng và số paragraph chỉ phủ một
phần; đây là thống kê cấu trúc theo spans, không phải nhãn nội dung.

Root map hiện toàn A. `expand_query_map(map_ref)` mở cấp nhỏ hơn hoặc quay lại
parent/root; từ parent có thể chọn sibling. `read_query_passages(query_ref)` đọc
raw ở current node hoặc child ngay ở bất kỳ cấp nào, không bắt buộc xuống leaf.
Host chuyển ref thành `hit_spans` cho M3; byte cap và continuation hiện hành giữ
nguyên. M3 có thể trả thêm context theo contract nguồn; coverage tính theo bytes
thực sự giao, không tự coi toàn vùng đã đọc. A ngắn vẫn được giao toàn văn nếu
vừa payload; hierarchical mode không ép seed paragraph như đường cũ.

Map chỉ dùng nhãn trung tính, heading có thật và snippets nguyên văn với raw
spans/hash. Thử ba vị trí đầu/giữa/cuối nếu vừa slot; khi cần dùng một literal
giữa vùng cho mỗi child. Nút trong không lặp snippets của chính nó cạnh snippets
các child. Trang leaf giữ literal của current node. Không tạo nhãn ngữ nghĩa,
tóm tắt model hay trích citation từ map.
Một trang phải vừa `map_max_tokens` theo counter thật của transport, gồm fixed
instructions/chat template trong minimal payload. Khi cần, giảm số/độ dài snippets
và headings, không bỏ child hoặc tạo lỗ coverage. Mọi child (hoặc current leaf)
phải còn literal không rỗng; `snippet_chars=0` bị từ chối. Nếu metadata và literal
tối thiểu vẫn không vừa thì báo unfit, không trả map chỉ có refs. Harness kiểm
tiếp toàn prompt/catalog/schema/raw với payload cap hiện hành; các route map/read
của mọi child được giữ khi trim. Khi có raw A, map dùng một literal tối đa 24 ký
tự mỗi child; dưới áp lực toàn payload có thể thu ngắn thêm nhưng không về rỗng,
để phần raw và tool tìm từ paragraph partial còn vào được lượt tiếp theo.

Registry chỉ giữ current map, current children và route parent/root thay cho tích
lũy mọi map từng mở. `map_opened` là tool đã mở bản đồ; `map_seen`/`preview_seen`
chỉ ghi sau request receipt xác nhận phản hồi đã về cho payload đó. `raw_read`
là unread/partial/full theo union raw spans trong các payload đã nhận response;
`raw_offered` là none/partial/full của payload đang chuẩn bị. Vì vậy raw vừa mở
nhưng chưa có lượt model tiếp theo vẫn chưa được tính đã đọc. Có thêm cờ
`preview_currently_offered`, `search_used` và totals hữu hạn; đã thấy map không
đồng nghĩa đã đọc/hiểu A. State được dựng lại từ ledger, không cần cache trong RAM.
Để tránh lặp metadata, page giữ `status_defaults`; status hiệu lực của một nút là
defaults cộng `node.status` (các field khác mặc định). Cờ preview đang offer ở cấp
page không được tính thành raw read hoặc seen trước receipt.

Host gắn visit epoch vào binding nội bộ, không thêm tham số model, cho phép quay
lại một vùng cũ mà không mắc duplicate-action. Epoch không được tính là tiến bộ:
map lặp vẫn chịu no-progress cap. Model chỉ được dùng refs của payload/schema
hiện tại; bản đồ/snippets không cấp raw ref để search hoặc assessment.

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m6_query_navigation -v
```

Fixture và replay scripted chỉ xác nhận engineering contract. RT3 chưa chứng minh
model chọn vùng tốt hơn hoặc tăng recall; chưa thêm debug proposition, đổi output/
embedding caps hay hướng dẫn tạo query của các mốc sau.

## RT1: lưu kết quả từng kênh ngoài payload (14/11/2026)

Hybrid adapter v3 lưu nguyên response M3 thành JSON write-once tại
`<run_dir>/retrieval_diagnostics/<operation_sha256>.json`. Envelope giữ query UTF-8
thực sự gửi, hash, query case, limit, action ID, operation ID, M3 request ID và runtime
bindings. `result` giữ mọi channel list, ranks/scores/leads, fused hits, coverage,
timings và query-vector provenance đã trả về, kể cả án ngoài top K giao cho M6.
“Đầy đủ” chỉ bao gồm dữ liệu runtime trả theo các cap hiện hành.

Journal embedding ghi path tương đối/hash/bindings trong `search_returned`, không
đưa các channel lists này vào observation hoặc payload model. Liên kết `action_id`
tới `action_started` trong ledger M6 cho biết query và `args._m6_need` cùng nguồn A
làm căn cứ. RT1 không thêm trường mệnh đề debug, không đổi prompt/schema, caps,
thứ tự/candidate pool hoặc gọi thêm retrieval/embedding.

Nếu lưu local thất bại, retrieval hợp lệ vẫn được trả; receipt ghi
`diagnostic_status=missing` cùng `diagnostic_error_type`. File có sẵn không được
ghi đè hoặc tái dùng. Usage embedding giữ theo ledger hiện hành; thiếu diagnostic
không được coi là 0 usage. Lỗi journal làm mất khả năng ghi receipt vẫn là lỗi
durability hiện hành, không cho phép tự gửi lại action đã admission.

Nếu retrieval lỗi trước khi trả response hoàn chỉnh, diagnostic là `unavailable`.
M3 kế thừa chưa cung cấp các channel trung gian khi dense/embedding lỗi; vì vậy
partial channel results là unknown, không tạo danh sách rỗng hoặc receipt partial
giả. Nếu bị ngắt sau khi lưu file nhưng trước receipt, file mồ côi không tự được
nghiệm thu hoặc dùng để replay; action đã admission vẫn chặn gửi lại.

Kiểm tra read-only (không inference, không gold):

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.retrieval_diagnostics --run-dir <run_dir>
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m6_retrieval_diagnostics pipeline_v2.tests.test_m6_hybrid -v
```

Verifier kiểm containment/path, hash bytes, operation fingerprint, action/query/
request links và bindings với admission/receipt. Nó phát hiện file thiếu/hỏng;
không xác thực lại toàn snapshot M3, không chấm recall hoặc độ đúng semantic.
Run cũ không có diagnostic vẫn được báo `legacy_unavailable`; không tạo evidence
hồi tố. `diagnostic_save_seconds` tách chi phí ghi local khỏi inference; elapsed
toàn lượt tìm hiện bao gồm phần ghi này. Binding code v3 có module diagnostic mới,
vì vậy dùng run namespace mới thay vì resume run đã khóa bằng phiên bản trước.

`AdaptiveHarness` trong `pipeline_v2/m6.py` dùng lại admission, append-only ledger, token accounting, recovery, source verifier và assessment validator M4. M6 không sửa M4/M5 hay snapshot đã seal. Chưa có selector được hiệu chỉnh: mặc định đầu ra `selection_status=pending_selection`, `prediction=null`.

## Tool theo mục đích

Model nhận `available_tools` cùng JSON Schema chỉ chứa các nhánh hợp lệ của **payload hiện tại**. Mỗi tool có mô tả, lúc dùng, kết quả và ví dụ dễ nhầm; schema/catalog và fingerprint được lưu trong request admission trước send.

| Tool model nhận | Model chọn | Host giữ |
|---|---|---|
| `search_cases_by_issue` | Cụm vấn đề và `a_paragraph_ref` từ A | Kênh, limits, loại query khỏi ứng viên, kiểm đoạn A và ghi provenance vào source need |
| `find_citation_matches` | Ref của citation nguyên văn trong A hiện tại | Chuỗi thật, byte spans/hash, matching method và scan limits |
| `continue_citation_search` | Ref trang tìm citation chưa phủ hết | Cursor, citation/need gốc và kích thước trang |
| `read_case_passages` | Candidate ref và trọng tâm đọc | Case ID, lead đã xác minh; mở lead lần đầu, tìm trong B theo focus ở lần sau |
| `read_query_passages` | Ref vùng A hoặc trang bản đồ | Handle/offset, mô tả preview/heading/role và provenance |
| `read_more_context` | Ref ngữ cảnh có mô tả parent/neighbor/continuation | Handle/cursor đã quan sát; không dùng marker cộng/trừ |
| `reload_evidence` | Ref bộ raw evidence cần giao lại | Các source refs đã giao hoặc đang trong payload |
| `assess_case_link` | Pair ref, quan hệ, location, lý do; attribution/evidence bổ sung khi có | Need/candidate ID, refs A/B và validator M4 |
| `review_conflicting_link` | Pair được trigger, nhãn và finding cụ thể | Trigger, tổng cap review, refs và assessment revision |
| `finish_case_review` | Dừng theo policy, không tiến triển hoặc lỗi | Selector, prediction và fallback |

Đặt `adaptive_config.channel=hybrid` để dùng trực tiếp M3 hybrid. Mỗi issue mới được gửi qua query embedding Qwen V2 đã khóa. M3 chạy case BM25, passage BM25 và dense exact trên Qdrant, rồi xếp hạng theo RRF với `k=60`. Giữ trần M3 là 100 án mỗi kênh, 4.096 dense hits và tối đa 20 án sau fusion. Host giữ điểm RRF, thứ hạng từng kênh, coverage và passage refs để đọc nguồn.

`search_cases_by_issue(issue, a_paragraph_ref)` giữ nguyên hai trường model chọn.
`m6.a_paragraphs` gắn ref với phần raw A hiện có, preview, khoảng byte, source hash
và source excerpt. Host kiểm ref và hash trước khi tìm; `issue` tiếp tục là query.

RT2 ngày 14/11/2026 (policy v7) cho phép cả phần paragraph bị cắt làm căn cứ tìm.
Quy tắc cũ chỉ cấp handle khi toàn paragraph nằm trong một raw excerpt được thay
bằng giao không rỗng giữa paragraph M2 và từng excerpt A thuộc
`current_payload_source_refs`, đúng query ID và source hash. Không có raw A hiện
tại thì không cấp ref tìm theo issue. Preview bản đồ vẫn chỉ là điều hướng.

Paragraph đầy đủ giữ handle gốc; phần bị cắt dùng `<handle-gốc>@<start>:<end>`.
Mỗi row có `span_bytes`, `source_ref`, `text_sha256` và preview của đúng phần raw
đó; đồng thời giữ `paragraph_handle`, `paragraph_span_bytes` gốc và
`paragraph_coverage=full|partial`. Source need `a_paragraph` giữ nguyên các field
này để debug và chọn lại đúng phần A bên cạnh B. Ref partial không chứng minh đã
đọc toàn paragraph hoặc đủ ngữ cảnh; model có thể tìm ngay hoặc mở thêm theo nhu cầu.

Các phần rời/overlap không chứa nhau vẫn là lựa chọn riêng, không ghép bytes từ
nhiều excerpt. Phần trùng hoặc nằm trọn trong một phần hiện có được bỏ; nếu có
toàn paragraph thì không cấp partial dư thừa. Khi nhiều excerpt cấp cùng một
phần, ưu tiên excerpt ngắn hơn rồi span/ref ổn định, không phụ thuộc thứ tự payload.
Validator kiểm coverage/handle/span gốc nhất quán và tiếp tục kiểm hash phần raw
hiện tại. Chưa thêm mệnh đề debug, bản đồ phân cấp hoặc thay ngân sách trong RT2;
chưa có bằng chứng live rằng đổi hợp đồng này tăng recall. Dùng run namespace
mới vì code/policy binding đã đổi; không resume run khóa dưới v6.

Schema v4 bỏ regex `\S` khỏi các trường văn bản tự do M6 để tránh lỗi chuyển JSON Schema sang grammar. `issue` và `focus` cần ít nhất bốn ký tự và hai từ sau trim. Host từ chối lý do, finding hoặc mô tả bằng chứng thiếu nếu chỉ gồm khoảng trắng. Rà soát các schema decoder của M4 và M5 cho thấy các trường văn bản ở đó dùng giới hạn độ dài và không dùng regex này.

Khi M6 vừa mở B, lượt tiếp theo ưu tiên ghép raw B với đúng đoạn A đã dùng để tìm ra B. Payload bỏ bớt lựa chọn điều hướng khi cần để chừa chỗ cho cặp nguồn. Nếu B phải cắt, phần còn lại vẫn chờ giao. Tool assessment chỉ xuất hiện khi có raw refs hợp lệ của cả hai phía. Nếu không ghép được trong cap, M6 quay về cách giao nguồn thông thường và vẫn ghi trạng thái coverage.

`lexical_both` vẫn là mặc định cho profile local cũ. Các profile BM25 cấp án, BM25 passage và hai kênh lexical vẫn dùng được. Khi đã chọn hybrid, lỗi tìm kiếm đi vào ledger và kết thúc theo policy lỗi hiện hành. Các lịch M5/M6 cần cùng toolbox, giới hạn, budget và selector khi so sánh.

Hybrid yêu cầu `embedding_budget` có `max_requests` và `max_input_tokens`. Host đếm input bằng tokenizer embedding đã khóa và dành ngân sách trước lượt gọi. Khi hết cap, schema loại tool tìm theo issue và vẫn cho model đọc hoặc assess ứng viên đã có. Nếu issue cụ thể vượt số token còn lại, run ghi `embedding_budget:input_token_cap`. `embedding_events.sqlite3` liên kết action M6 với ledger embedding M3. Báo cáo giữ usage khi bước dense lỗi sau embedding và giữ trường chưa rõ ở dạng null. Resume sau action bị ngắt không gửi lại action đó.

Citation matcher chỉ quan sát một số định dạng neutral citation và SCR bằng regex (`m6-citation-regex-v1`). Nó không phát hiện đầy đủ tên án, citation mọi định dạng hoặc xác minh identity. Hit giữ `observed_not_identity_verified`, method, offsets và coverage; trang scan tiếp theo có tool riêng. Không dùng cả paragraph làm citation string.

Source need giữ search intent/route, refs A và source/hash/spans lúc tìm; mỗi candidate giữ các need đưa nó vào pool cùng tối đa ba mô tả lead/rank/score/kênh và preview tối đa 320 ký tự (ghi rõ bị cắt, không phải evidence). Assessment chỉ mở khi current A tương ứng need và current B cùng có trong payload. Nếu raw A bị cắt thành ref mới, need vẫn giữ nguyên, pair ghi `context_coverage=partial`; đây không phải chứng nhận đủ ngữ cảnh.

## Attribution và targeted review

Assessment có thể dùng speaker schema phân nhánh M4: unknown không kèm type; role xác định cần các refs speaker/container/quote chain phù hợp để validator kiểm. Các refs bổ sung phải thuộc A hoặc đúng B của pair, đều hiện diện trong payload. `missing_evidence` là danh sách mô tả context cụ thể cần đọc tiếp; M4 giữ hồ sơ pending. Counterevidence được model chọn bằng current refs đã nằm trong assessment dependencies, host kiểm đúng pair rồi materialize raw records/provenance vào note M4; không chuyển counterevidence thành identity support.

Review trigger hiện gồm quan hệ mâu thuẫn giữa need, context có quoted paragraph và một mẫu audit deterministic trong nhóm chưa trigger. Finding được ghi trong assessment revision; số review dùng chung cap requests/tokens với controller và `max_reviews`. Chưa có trigger sát cutoff vì selector chưa chốt. Trigger quote là heuristic quan sát, reviewer vẫn là model inference, không phải gold hay chứng nhận attribution đúng.

## State, caps và selection

Trạng thái M6 được dựng lại từ ledger M4; không dựa transport memory. Query maps, leads, source needs, continuation refs, coverage, assessments, review và usage tồn tại qua resume. Source hash drift đi theo invalidation M4. No-progress tính candidate/raw evidence/assessment mới và navigation/search-coverage mới. Duplicate actions vẫn do M4 chặn. Cap cuối sau open giữ source refs pending/unread, không tính đã đánh giá.

`Budget` bắt buộc được caller cung cấp; không có ngân sách production mặc định. Catalog, source descriptions và raw evidence đều nằm trong payload được tokenizer đếm. `prepare()` chỉ khóa cấu hình và trả preview payload/token count, không admission hoặc send; không dùng prepare cho run đã có request.

Muốn nối selector dùng chung: inject `selector(snapshot)` trả đúng `{prediction, assessment_ids}` và `selector_fingerprint` đã khóa. M4 kiểm active assessment và raw refs hiện tại trước finalization. Model không được tự truyền prediction/cutoff. Baseline fallback chỉ khả dụng khi caller truyền rõ `baseline` cùng `baseline_fingerprint`; không có baseline thì lỗi/budget-stop giữ prediction null và `fallback_unavailable=true`, không giả empty prediction.

## Kiểm local và chạy live

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m6_adaptive pipeline_v2.tests.test_m6_live -v
& .venv/Scripts/python.exe -m pipeline_v2.m6_live --help
```

CLI `pipeline_v2.m6_live` do Main nối vào transport Qwen/tokenizer đã pin. Dùng `prepare` để xem manifest/payload trước, cung cấp budgets tường minh theo `--help`. Người dùng hoặc AG mới chạy lệnh inference `run` theo phân công hiện hành; không tự deploy hoặc đổi model. Giữ manifest, report và events.sqlite3, cả lượt lỗi/unknown receipt. Token usage của replay giả lập phải phân biệt với actual provider usage.

Settings JSON có các trường `query_id`, `tokenizer_dir`, `byte_budget`, `map_limit`, `adaptive_config` và `budget`. Mọi trường budget phải khai báo rõ, kể cả `max_total_tokens` và `max_retries`. Có cấu hình **kiểm tích hợp chưa hiệu chỉnh**, cùng cap với replay local, tại `pipeline_v2/reviews/m6_local_v1/live_preflight_settings.json`; không coi đây là profile production hoặc phép so công bằng với M5. `prepare` đã kiểm nguồn thật và pinned tokenizer, ghi `plan.json`, `first_payload.json` và ledger với **0 request** tại `pipeline_v2/reviews/m6_local_v1/live_preflight_20261112_v1/`.

```powershell
# Chỉ chuẩn bị local; chọn namespace mới nếu chạy lại.
& .venv/Scripts/python.exe -m pipeline_v2.m6_live prepare --settings pipeline_v2/reviews/m6_local_v1/live_preflight_settings.json --run-dir pipeline_v2/reviews/m6_local_v1/live_preflight_20261112_v2

# Người dùng hoặc AG thực thi inference sau khi kiểm plan/payload/caps.
& .venv/Scripts/python.exe -m pipeline_v2.m6_live run --run-dir pipeline_v2/reviews/m6_local_v1/live_preflight_20261112_v2
```

`run` kiểm code/source/index/profile binding và hash preview trước khi xử lý. Resume cùng lệnh giữ ledger/caps và dừng khi receipt unknown, không tự reset hoặc gửi lại request không rõ kết quả. CLI hiện phục vụ gate controller/evidence, chưa nối selector hoặc baseline đã khóa; prediction tiếp tục null. Muốn kiểm semantic phải đối chiếu evidence thật riêng, không lấy schema PASS làm đúng quan hệ A→B.

Chạy hybrid live theo [pilot discovery và quy trình đối chiếu gold](../reviews/m6_discovery_pilot/README.md). Profile chẩn đoán cũ ở `m6_hybrid_local_v1` dùng cap payload 24.000 cho replay local. Pilot giới hạn payload theo cửa sổ 8.192 token của deployment hiện tại.

Triển khai local và protocol tests không nghiệm thu semantic correctness, chất lượng COLIEE hay lợi ích so với M5. Cần nghiệm thu engine live với tool nhiều lựa chọn, selector/baseline chung và phép so discovery/reading theo kế hoạch trước khi chốt toàn M6.
