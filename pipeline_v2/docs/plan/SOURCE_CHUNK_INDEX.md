# Contract dự kiến: nguồn, paragraph, passage và hybrid index

Trở về [kế hoạch](README.md). Các field bên dưới là interface đề xuất, chưa phải schema đã triển khai.

## 1. Bốn lớp không được trộn

1. **Raw source:** bytes gốc bất biến, case ID/hash/encoding. Không strip BOM/chuẩn hóa newline trên raw để làm quote khớp.
2. **Structural units:** partition toàn nguồn, gồm heading/paragraph/unnumbered/whitespace/unknown. Mỗi marker `[số]` đầu dòng có unit độc lập, kể cả khi thuộc quotation; quyền sở hữu `current_case/quoted/unknown` là quan sát riêng. Quan hệ quotation là sidecar giữa các unit, không phải containment mặc định.
3. **Retrieval core chunks:** ghép/tách structural units để tìm kiếm. Thiết kế ban đầu có baseline không overlap; profile M2 được triển khai lần này là biến thể overlap khai báo ở Section 3.2, không áp source partition invariant sai cho retrieval view.
4. **Reading context:** parent paragraph, heading, quote attribution, đoạn liền kề hoặc vùng xa mà agent mở theo nhu cầu. Reading context không bị khóa vào kích thước chunk embedding.

Mọi byte của raw phải mở được, kể cả headnote/counsel/unknown không được đưa vào một index view cụ thể. Profile đầu index toàn phần có chữ, giữ `region_type` và evidence; thêm body-only view/filter là ablation được ghi, không drop nguồn hoặc tự nhận mọi heading đã đúng nghĩa.

## 2. Các bản ghi tối thiểu

| Record | Fields cốt lõi |
|---|---|
| Source | `case_id, raw_sha256, byte_length, encoding, char_byte_map_ref, corpus_manifest_id` |
| Structural unit | `unit_id, source_hash, span_bytes, span_chars, order, unit_kind, observed_marker, marker_span_bytes, paragraph_role, role_evidence_refs, language_region, section_path_refs, uncertainties` |
| Quote sidecar | `quoted_unit_id, attribution_unit_id/null, attribution_cue_refs, span_bytes, route_unknown` — quan hệ attribution giữa các unit riêng, không gán containment |
| Metadata | `field, value/null, source_refs, extraction_method/version, confidence_status` |
| Chunk | `chunk_id, source_hash, core_span_refs, parent_unit_ids, section_refs, language_region, split_order, continuation_refs, policy_hash, tokenizer_fingerprint, token_counts` |
| Reading expansion | `chunk_id, parent_container_refs, previous_paragraph_ref/null, next_paragraph_ref/null, source_hash, expansion_policy_hash` — mapping để mở toàn paragraph cha và context lân cận |
| Embedding view | `chunk_id, core_text_hash, prefix_refs/template, context_refs, exact_input_hash, full_token_count, embedding_profile_id` |

ID không chỉ là `(case, paragraph_number)`: bilingual và quoted paragraphs có thể trùng số. Decoder/BOM policy phải được version trong char↔byte mapping: adapter dùng `utf-8-sig` có thể bỏ BOM khỏi decoded view nhưng không được bỏ bytes đó khỏi raw source hoặc lệch địa chỉ. Khi boundary phụ thuộc tokenizer, chunk ID bind tokenizer. View dùng chuỗi normalize/tiền tố phải có raw mappings và provenance riêng; output evidence luôn quay về raw.

Không đặt semantic speaker/holding thành fact từ regex. Chỉ lưu cue/section observation; agent có thể xác minh hoặc giữ unknown sau đọc context. Metadata party/date/citation chỉ đầy đủ khi có evidence; năm xuất hiện trong nội dung không tự là năm quyết định.

## 3. Thuật toán chunking khởi đầu

### 3.1. Nhận diện cấu trúc

- Dò marker `[số]` đầu dòng thành ranh giới độc lập. Giá trị/thứ tự số không điều khiển ownership, grouping, reset hoặc language; không dùng bộ đếm paragraph.
- Marker unit có role `current_case/quoted/unknown` theo evidence cục bộ. Quoted/unknown vẫn có ranh giới riêng. Citation `[2012] FC 9` được phân biệt bằng reporter liền kề; `[2012]` đứng riêng không bị loại chỉ vì giá trị năm.
- Không phân giải chắc thì giữ ranh giới marker và role `unknown`; M2 không tự gộp xuyên ranh giới ownership chưa rõ. Chỉ link attribution unit khi cue thực sự thuộc unit đó. Bản dịch đổi vùng theo evidence, không theo `[1]`.
- Dùng fixture từ `061295` để kiểm quotation; `067620` để kiểm song ngữ; `062436` để mở được heading Respondent. Đây là diagnostics đã exposed.

### 3.2. Tạo core passages

1. Giữ nguyên paragraph nếu vừa max-core/full input limit; không tách chỉ vì vượt target mềm.
2. Paragraph ngắn có thể ghép liền kề cùng section/language tới gần target, giữ unit IDs. Không ghép qua heading lớn hoặc hai bản ngôn ngữ. Không ép đạt soft-min nếu làm mất ranh giới cần thiết.
3. Khi có thể, giữ câu attribution với block quotation/citation list; nếu phải tách thì tạo continuation/parent refs và trả cue trong tool metadata. Không hứa mỗi chunk là legal unit hoàn chỉnh.
4. Paragraph quá dài: chia theo sentence boundaries quan sát được, lưu paragraph cha và thứ tự. Sentence tokenizer phải kiểm abbreviations/citations pháp lý. Nếu một câu vẫn quá lớn, tách tại clause/whitespace như fallback có flag, không cắt bỏ phần dư; mở parent bằng nhiều phần khi agent cần.
5. Core baseline không overlap. Variant chỉ thêm context đã khai báo, không đổi core ownership hoặc đếm overlap thành evidence độc lập. Giới hạn overlap một câu/64 tokenizer tokens là profile thử; câu dài hơn thì không lấy nửa câu làm overlap giả.

**Full-input invariant:** tokenize chuỗi thực sự đưa vào model, gồm instruction/query-document prefix, heading, context và special tokens. Phải `full_input_tokens <= effective_model_limit`. Dùng giới hạn nhỏ hơn nếu endpoint/config có cap nhỏ hơn model card. Reject/rechunk input vượt cap; không silently truncate. Model chưa chọn thì chỉ có structural units/chunk draft, dense manifest chưa ready.

**Profile triển khai M2 hiện tại (thay cấu hình khởi đầu ở mục 2, 4, 5 bên trên):** tokenizer chính thức Qwen3-Embedding-4B được pin revision/assets trong `configs/qwen3_embedding_4b_tokenizer.lock.json`. Dùng raw body, không prefix/instruction/chat template, giữ postprocessor chính thức có một token cuối `<|endoftext|>`. Giữ nguyên mỗi navigation unit nếu full input <=448 tokens; không ghép các parent ngắn. Unit dài tách bằng tokenizer offsets với ưu tiên biên whitespace, target mềm 320, overlap mong muốn 128, hard cap full input 448; không nhận các biên này là câu/ngữ nghĩa đã xác minh. Overlap thực tế phải đo và lưu, không mặc định bằng 128. Đây là variant thử local đã trao đổi mới nhất, **không phải baseline không overlap/overlap tối đa64 của đề xuất cũ**; không nhầm 128 overlap với soft-min128 trong bảng kế hoạch ban đầu. Giữ continuation/parent/context refs, không đếm overlap thành evidence độc lập. Chưa có phép đo retrieval để nói overlap128 tốt hơn không overlap.

Các số 320/128/448 chưa được tối ưu. Kiểm tokenizer và token histogram trên corpus manifest trước quyết định quy mô embedding. Không dùng số ký tự như cam kết số token. M2 xác minh giới hạn local448; endpoint Modal chưa có nên phải kiểm tương thích input/template/tokenizer và cap endpoint trước khi inference. Không tuyên bố embedding runtime ready từ kiểm local.

### 3.3. Contract chuyển giao M1 Revision 2 → M2

Chốt theo yêu cầu người dùng sau review Revision 2. Đầu vào M2 là bundle `pipeline_v2/artifacts/m1_20261105_v2/`; M1 v1 chỉ để đối chiếu lịch sử. Chấp nhận phần nguồn và ranh giới marker của M1, không coi ownership hoặc language metadata đã được chứng nhận đúng ngữ nghĩa trên toàn corpus.

- **Giữ unknown:** Không loại paragraph khỏi chunking/index chỉ vì `paragraph_role=unknown`, thiếu attribution hoặc thiếu metadata. Unknown thể hiện quyền sở hữu chưa xác định; nguyên văn và ranh giới vẫn có hiệu lực.
- **Giữ ranh giới và provenance:** Paragraph unknown ngắn được phép đứng riêng, không ép ghép để đạt target/soft-min và không tự gộp xuyên ranh giới ownership chưa rõ. Nếu paragraph dài phải tách theo policy token, mọi phần giữ unit cha, raw spans và thứ tự; context trước/sau hoặc câu dẫn là refs riêng, không biến thành ownership đã xác minh.
- **M2 chỉ tạo passage:** Không tự bổ sung LLM, mô hình ngữ nghĩa, speaker/holding classifier hoặc suy nguồn án để giải quyết ownership. Chuyển nguyên trạng role, uncertainty và evidence refs cần thiết tới các bước sau. Agent ở bước đọc/đối chiếu mới phân xử bằng ngữ cảnh, lưu kết luận riêng cùng evidence; không sửa ngầm artifact M1.
- **Tiếng Pháp tạm hoãn:** Chưa sửa hay tối ưu nhận diện tiếng Pháp, chưa thêm language detector, dịch hoặc routing EN/FR trong phạm vi hiện tại. Tiếp tục giữ toàn bộ raw text và các unit hiện có, kể cả tiếng Pháp; không diễn giải việc hoãn là quyền xóa hay chỉ giữ tiếng Anh.
- **Language chỉ là quan sát:** Không dùng `language_region` làm căn cứ duy nhất để lọc nguồn, loại passage hoặc cho phép ghép. Cùng nhãn `en:0` không chứng minh hai unit thực sự cùng ngôn ngữ. Không tuyên bố mọi chunk thuần một ngôn ngữ khi chưa có phép xác minh; chưa mở thêm workload để xử lý giới hạn này.

Gate nghiệm thu M2 phải có fixtures kiểm: unknown vẫn có passage/mapping; unknown ngắn không bị ép ghép; paragraph dài có đầy đủ continuation refs; role/language metadata không trở thành bộ lọc loại nội dung; M1 bytes/hash/units không bị sửa. Kiểm các ca marker từng bị nuốt và bảo đảm mọi core span mở lại đúng raw. Các gate này không phải phép đo ownership accuracy.

### 3.4. Passage tìm kiếm nhỏ, context trả về lớn

Mỗi core passage nhỏ là đơn vị embedding và tìm kiếm; reading context là view riêng mở từ raw source, không cần embedding lại chỉ để trả context lớn. Profile token hiện tại ở Section 3.2; BM25 và dense dùng cùng core IDs/body. Không dùng kích thước context đọc làm kích thước embedding.

**Mặc định khi hit `12b`: trả toàn bộ paragraph cha `[12]`, paragraph trước `[11]` và paragraph sau `[13]`.** Giữ thứ tự nguồn `[11] → [12] → [13]`, đồng thời đánh dấu chính xác span `12b` là phần trúng tìm kiếm. `12a/12b/12c` chỉ là tên minh họa các phần tách từ cùng parent, không phải ID paragraph dựa vào số.

- **M2 chuẩn bị mapping:** Mỗi child passage giữ refs tới toàn bộ parent M1 unit đã sinh ra nó, continuation/sibling refs và một paragraph trước/sau trong cùng nguồn. Nếu một core hợp lệ có nhiều parent units, lưu đủ parent refs và lấy context ngoài hai đầu vùng parent; không tự ép ghép unknown để tạo core như vậy. Với hit thuộc vùng không đánh số, dùng container/unit thật và policy lân cận được khai báo, không bịa paragraph number.
- **Lân cận theo vị trí:** `[11]`/`[13]` trong ví dụ là paragraph liền trước/sau theo source order, không tính `12-1`/`12+1`, không tra bằng marker số. Giữ đúng case ID, source hash, offsets và marker lặp/quotation/unknown. Không vượt sang file khác. Đầu/cuối nguồn thiếu hàng xóm thì trả phần hiện có và ghi lý do; heading/whitespace ở giữa vẫn có refs để dựng context đọc.
- **M3–M4 materialize context:** Khi giao kết quả passage hit cho agent, host mở parent đầy đủ cùng hai paragraph lân cận theo policy này. M2 chỉ dựng manifests/refs; việc search, fetch và đưa raw vào payload được thực hiện ở M3–M4. Search response có thể tách preview/ranking khỏi payload đọc, nhưng preview không được coi là đã giao đủ context mặc định.
- **Hit khác context:** Payload giữ `hit_chunk_id`, hit spans/score/rank, parent/context refs, raw text thực sự được giao, `context_requested_refs`, `context_delivered_refs` và `pending_context_refs`. Nhãn phần trả về là `hit`, `parent`, `previous_context`, `next_context`, tách khỏi nhãn ownership `quoted/unknown`. Không biến context lân cận thành hit được chấm điểm hoặc evidence đã được agent đọc.
- **Giới hạn payload:** Context yêu cầu luôn gồm full parent + trước/sau. Nếu vượt cap, chia thành nhiều phần có continuation và báo phần chưa giao; ưu tiên phần chứa hit, hoàn tất parent rồi context lân cận. Không truncate ngầm hoặc báo đã trả đủ `[11]–[13]` khi mới giao một phần. Agent có thể open/reload phần pending; chỉ raw đã có trong payload hiện tại mới đủ điều kiện dùng khi assess.
- **Khử trùng:** Nếu nhiều hit thuộc cùng `[12]`, giữ từng hit nhỏ để truy vết nhưng chỉ giao một vùng parent/context chung khi trùng source spans; gộp vùng đọc chồng nhau và giữ mapping từng hit. Mở rộng context không làm tăng retrieval score, case votes hoặc số evidence độc lập.

Gate M2 kiểm mapping `12b → full [12] + previous [11] + next [13]` bằng offsets, gồm số nhảy/lặp, unknown, quoted, đầu/cuối file và source drift. Gate M3–M4 kiểm materialize đúng raw, dedup nhiều hit cùng parent và giao context dài theo nhiều phần với ledger requested/delivered/pending trung thực. Chưa chạy embedding/index/agent trong lần cập nhật thiết kế này.

### 3.5. Mapping và preview phục vụ agent đọc query

Mục này đã triển khai navigation/preview độc lập tokenizer; các bundle cũ giữ nguyên trạng thái checkpoint. Người dùng sau đó chốt Qwen3-Embedding-4B và cho phép hoàn tất token passages theo profile riêng ở Section 3.2. Tokenizer agent và budget giao payload vẫn chờ M4. Không tạo character chunks rồi gọi là token-valid passages. M2 không gọi LLM để tóm tắt hoặc suy ownership.

**Chính sách query cho M4:** Query vừa ngân sách đọc đã khóa có thể giao toàn văn; query dài giao bản đồ và context ưu tiên, sau đó agent tìm/mở thêm theo nhu cầu. Ngưỡng dài/ngắn dùng tokenizer agent, không dùng tokenizer embedding. Dấu viện dẫn là điểm ưu tiên, không khóa quyền đọc hoặc tìm kiếm chỉ trong vùng có dấu. Toàn bộ query vẫn có thể được tìm bằng công cụ; coverage phân biệt chưa giao/đã giao một phần/đã giao đủ. M2 chuẩn bị dữ liệu bất biến, M4 quản lý payload và trạng thái đọc theo từng run.

**Navigation record:** Mỗi paragraph và vùng có nội dung không đánh số có `handle, case_id, source_hash, unit_id, source_order, span_bytes, unit_kind, observed_marker, section_refs, paragraph_role, uncertainties, previous_paragraph_ref/null, next_paragraph_ref/null, preview_refs, anchor_refs`. Với vùng không đánh số, role/marker không có thì giữ null hoặc unknown đúng loại, không bịa paragraph. Handle ngắn ổn định trong một phiên bản nguồn/profile, được scope bằng case/hash; marker chỉ hiển thị. Whitespace giữ nguyên trong raw nhưng không cần một dòng navigation riêng. Heading quan sát được có refs để nhóm hoặc mở ngữ cảnh, không tự thành cây mục pháp lý đã xác minh.

Chỉ mục paragraph lân cận dựng theo source order, bỏ qua whitespace và heading khi đếm paragraph. Không dùng trực tiếp `before/after` M1 vì API đó đếm structural units. Nội dung không đánh số có container và chính sách lân cận được khai báo riêng, không giả là paragraph có số. Khi core chunk đã có, nó giữ core spans, parent refs, split order, continuation/sibling refs và reading-expansion refs như Section 3.4. Trong giai đoạn chưa tokenizer chỉ lưu mapping unit/container; không cấp chunk ID giả cho child chưa được sinh.

**Preview nguyên văn:** Có hai loại `opening` và `anchor`. Opening lấy phần đầu có nội dung sau marker; dòng chỉ gồm whitespace/marker/placeholder có thể được bỏ qua khi chọn preview theo policy được version. Không bỏ nội dung đó khỏi nguồn hoặc chunking scope. Nếu không còn nội dung phù hợp thì preview rỗng với lý do, không sinh câu thay thế. Anchor preview lấy vùng quanh placeholder hoặc câu dẫn quotation quan sát được. Placeholder chung chỉ là dấu che nội dung, không tự chứng minh citation.

Profile hiển thị: opening lấy cửa sổ nội dung tối đa 240 Unicode codepoints, không dừng ở dấu chấm đầu tiên hoặc tại chức danh/tên viết tắt/số thứ tự. Sau khi bỏ placeholder để xét dòng mở đầu, dòng phải còn chữ/số có nội dung; dấu câu/ngoặc đơn lẻ không đủ để giữ dòng. Việc bỏ qua chỉ áp dụng khi chọn view, không sửa raw. Anchor hướng tới 120 codepoints mỗi phía nhưng tổng snippet tối đa 240 codepoints, tính cả cue. Ưu tiên biên whitespace hoặc tag trọn vẹn trong cap; nếu từ/tag dài hơn cap thì giữ ref đầy đủ và báo clipping, không rewrite text. Các giá trị là profile hiển thị, không phải ngưỡng tối ưu hoặc số token.

Khử trùng trước khi chọn tối đa hai snippet: dùng content-start sau marker/các dòng đã bỏ qua để anchor gần đầu không kéo prefix trở lại; kiểm containment hai chiều, giữ view bao phủ hữu ích hơn và gộp union khi vẫn vừa cap. Slot còn lại ưu tiên bổ sung anchors chưa được thể hiện, tie-break theo source order; không dùng hai slot cho hai view mà một view nằm hoàn toàn trong view kia. Anchor trước vùng opening hoặc không được chọn hiển thị vẫn giữ đầy đủ trong catalog. Flags `truncated/start_clipped/end_clipped` mô tả phạm vi nội dung bị lược; `partial_sentence=null` và `boundary_status=content_window_not_sentence_verified` thể hiện chưa đánh giá ranh giới câu, không suy câu hoàn chỉnh từ dấu chấm hoặc từ việc đã lấy hết một unit.

Mỗi preview có `preview_id, preview_kind, case_id, source_hash, unit_id, span_bytes, text_sha256, selection_method, preview_profile_hash, partial_sentence, anchor_ref/null` cùng nguyên văn hoặc ref để dựng nguyên văn. Mỗi snippet phải khớp exact raw slice. Nếu có nhiều lát cắt, lưu từng lát riêng; dấu `…`, nhãn và định dạng UI nằm ngoài raw text. Anchor record giữ loại, raw evidence span và phương pháp/version, không tự gán speaker, holding, noticed relation hoặc danh tính án nguồn.

Một preview có thể nối nhiều `anchor_refs`; với mỗi ref ghi visibility full/partial, không đòi full cue phải vừa preview mới giữ liên kết. Với cue M1 đi qua nhiều unit, giữ `source_anchor` chứa full raw span/hash và các unit refs liên quan; per-unit anchor fragments giữ intersection spans cùng `source_anchor_ref` và original cue span. Cue nằm ở heading hoặc whitespace vẫn mở được qua source-anchor catalog, không bị mất chỉ vì không có paragraph attribution. Catalog source anchors và per-unit anchors đều có cách inspect/phân trang, độc lập display limit của preview. Bỏ marker khỏi opening không tự làm `truncated=true`; clipping phải tính theo meaningful content-start/end được khai báo. Không nâng source clipping thành khẳng định ranh giới câu.

**Bản đồ gửi agent:** Một dòng minh họa gồm handle, marker, heading quan sát, preview, signals và role; không lặp `Open: ...` trên từng dòng. Bản đồ lớn được nhóm theo heading quan sát hoặc phân trang có offset/cursor, phạm vi, tổng số mục và cách lấy trang tiếp. Không mất quyền mở vùng chưa hiển thị hoặc dùng tóm tắt sinh tự động thay raw evidence.

**Tool M4 dự kiến:** Agent gọi `open_query(handle)`; host trả full paragraph/container cùng context lân cận theo Section 3.4. Đây là action của agent và response của host, không phải dòng output prediction. Preview không chứng minh agent đã đọc đầy đủ unit. M2 có thể cung cấp CLI/API inspect mapping và mở raw context để kiểm local; không gọi đó là live agent delivery hoặc ghi trạng thái đã đọc cố định vào manifest.

**Artifact:** `navigation_manifest`, `preview_manifest`, `anchor_manifest`, parent/context mapping, profiles, seal và coverage report; cho phép layout per-case kèm registry để tránh một JSON khổng lồ. `chunk_manifest` và `embedding_input_manifest` chỉ ready khi token policy/model/tokenizer tương ứng đã khóa. Navigation/preview có thể ready riêng; token counts chưa đo để null, không thay bằng ký tự hoặc tokenizer khác. Token count preview cho agent cũng tách khỏi token count embedding; full-payload accounting thuộc M4.

**Gate nghiệm thu:** coverage đủ paragraph/unnumbered có nội dung kể cả unknown/quoted; handle duy nhất đúng source/profile; hàng xóm đúng source order với số nhảy/lặp và đầu/cuối file; heading/whitespace không làm lệch số paragraph; preview khớp raw hash/spans và cap codepoints; anchor không mất sau display limit; placeholder-only skip chỉ đổi view; pagination truy cập được đủ record; source/config/artifact drift và tamper bị từ chối. Khi có tokenizer, bổ sung gate child → full parent + hai hàng xóm, continuation đầy đủ và token overflow. Không coi navigation PASS là toàn M2 hoặc embedding ready. Giữ các giới hạn ownership và tiếng Pháp ở Section 3.3.

## 4. BM25 và dense dùng chung nền

### BM25

- Index case-level và global passage-level. Legal-text analyzer giữ Unicode EN/FR và negation; version tokenizer/stopwords.
- Tách field cho exact identifiers/citation, số đoạn và tên có nguồn. Không dùng analyzer `[a-z]+` cho citation numbers.
- Heading/metadata là field riêng hoặc boost khai báo, không chèn toàn bộ metadata vào mọi body làm lệch tf/length.
- Raw ID không được dùng làm predictor nhãn. Literal/normalized phrase search phải giữ mapping về raw, không dùng normalized text làm quote gốc.

### Dense

- Baseline dùng cùng core body/IDs với BM25. Prefix chỉ ngắn, từ heading/language/source có sẵn; không LLM-generated legal summary trong vòng đầu.
- Pin model/tokenizer/revision, input type/query-document prompt, pooling, vector dimension, precision, normalization, similarity metric và endpoint/context caps.
- Khả năng ngôn ngữ của model được khai báo trong profile; nếu về sau có routing thì phải công khai. Theo phạm vi hiện tại ở Section 3.3, chưa bổ sung xử lý riêng tiếng Pháp và không dùng language metadata chưa xác minh để lọc nguồn. Không nối nguyên hai bản dịch để vô tình làm tràn limit; không tự dịch bằng LLM rồi coi là nguồn.
- Cache vectors theo exact input + model/profile fingerprint; lưu trạng thái pending/success/error và accounting cho mỗi attempt. Resume không coi file vector có mặt là đã đủ completeness.
- Không tự chọn late/contextual chunk embedding làm mặc định; đó là variant riêng khi baseline và tài nguyên cho phép.

## 5. Hybrid và ánh xạ về case

Mỗi channel trả passage handle, case ID, score/rank, index/profile, preview và `must_open_before_citing`.

- Với cùng query/search intent: chuyển passage hits thành unique-case rank bằng best hit của từng case; giữ top evidence handles. Đây là policy thử, vẫn phải báo thiên lệch theo độ dài/số chunks.
- Fusion khởi đầu trên case ranks: `sum_j w_j/(60 + rank_j(case))`, missing channel đóng góp 0. Các channel cố định là case BM25, passage BM25, dense passage; weight ghi trong profile.
- Không sum mọi chunk, overlap hoặc mọi câu search agent như phiếu độc lập. Search history chỉ mở rộng union; selector cuối dùng common evidence/features.
- Fetch thêm hit để đạt K unique cases trong scan cap đã khóa; nếu không đạt thì báo thực tế. So channel ở cùng K unique cases, kèm số chunk hits và cost, không so K chunks với K cases.
- Giữ union trước cap và pool sau cap để evaluator đo mất gold ở đâu. Cap và finalist policy phải công bố; không nhét gold vào pool runtime.
- Candidate manifest quyết định eligibility; không gộp train/test hoặc tự mở corpus vì có file trên đĩa.

## 6. Artifact và gate M1–M3

Artifact dự kiến: `source_registry`, `structure_maps`, `metadata`, `chunk_manifest`, `embedding_input_manifest`, `vector_attempt_ledger`, `index_manifest`, `retrieval_profile`, `coverage_and_token_report`.

Gate bắt buộc:

- Source round-trip toàn bytes; char↔byte với CRLF/Unicode/BOM.
- Root paragraph khác quoted marker và bilingual duplicate; unknown fallback không mất nguồn.
- Long sentence và prefix làm overflow phải bị phát hiện; không index âm thầm bản cắt.
- BM25/dense core IDs/body khớp; citation digits/EN-FR accents/negation search được.
- Global passage search tìm được fixture khi chưa biết case ID.
- Duplicate/overlap không sinh nhiều case votes; every index hit mở đúng source/hash.
- Vector coverage đủ manifest mới ready; lỗi/retry/resume/cost reconcile được.

Những gate này kiểm tính toàn vẹn và khả năng vận hành; không chứng minh semantic chunk tốt hoặc noticed prediction đúng.
