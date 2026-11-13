# M6: điều phối thích ứng trên M4

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

Schema v3 yêu cầu `search_cases_by_issue(issue, a_paragraph_ref)`. `m6.a_paragraphs` gắn handle đoạn M2 với preview, khoảng byte, source hash và ref của raw excerpt chứa đoạn. Khi giao toàn văn, một raw excerpt có thể cấp nhiều handle. Khi giao một trang nguồn, chỉ cấp handle cho đoạn nằm đầy đủ trong một raw excerpt hiện tại. Nếu thiếu đoạn nguyên vẹn, model có thể mở thêm nguồn hoặc tra citation có sẵn. Host kiểm lại ref và hash đoạn trước khi tìm, ghi `a_paragraph` vào action và source need. Cụm `issue` vẫn là input retrieval. Handle cho biết đoạn model chọn làm căn cứ.

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
