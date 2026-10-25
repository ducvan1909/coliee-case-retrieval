# Agent B — Vòng 4: phản biện chéo thiết kế Agent A

## 1. Căn cứ và phạm vi phản biện

Tôi đã đọc toàn bộ `agent_a_initial.md` và đối chiếu với `agent_b_initial.md`. Hai báo cáo thống nhất ở phần lớn các quyết định nền: source phải bất biến và luôn truy cập được; AU chỉ là lớp dẫn đường có provenance; annotation không được dùng làm hard filter; host phải sở hữu offset, hash, cache và workflow; full KG chưa có bằng chứng đủ mạnh; completion hoặc schema PASS không chứng minh chất lượng ngữ nghĩa.

Vì vậy, tám phản biện dưới đây tập trung vào các điểm có thể làm thiết kế của Agent A thất bại khi chuyển thành hợp đồng triển khai hoặc khi đánh giá. Tôi không tạo bất đồng giả ở những phần hai bên đã có cùng kết luận.

## 2. Tám phản biện quan trọng

### Phản biện 1 — Trigger lazy AU tạo vòng lặp thiên lệch theo retrieval hiện tại

**Nhận định bị phản biện →** Agent A đề xuất chỉ materialize AU khi case được retrieval thường xuyên, passage được đánh giá có giá trị, hoặc case nằm trong ngân sách build được chọn; đây được xem là cách tránh chi phí trích xuất toàn corpus.

**Bằng chứng/phản ví dụ →** Tần suất được retrieval không độc lập với biểu diễn hiện tại. Case đã được BM25/dense tìm thấy sẽ tiếp tục nhận enrichment rồi càng dễ được tìm thấy; case diễn đạt khác query, đoạn hữu ích không có citation, case dài nhưng chỉ có ít AU, hoặc case chưa có annotation sẽ không có cơ hội đi vào vòng enrichment. Đây là feedback loop từ retriever sang KB, không chỉ là tối ưu cache. Một án chứa đúng lập luận nhưng không có citation hoặc dùng thuật ngữ khác query là phản ví dụ trực tiếp: nó cần enrichment để được tìm thấy nhưng lại phải được tìm thấy trước mới được enrichment.

**Hậu quả →** Coverage có thể giảm một cách im lặng trong khi token/query giảm. Kết quả còn làm sai phép so sánh source-only với source+AU vì nhóm được enrich không phải mẫu đại diện cho corpus. Những case dài nhưng ít AU và case AU trống có nguy cơ bị coi là “không có giá trị” dù nguyên nhân thật là trigger không chạm tới chúng.

**Phương án thay thế →** Giữ lazy materialization nhưng tách hai hàng đợi: một hàng đợi khai thác từ retrieval thật và một hàng đợi khám phá được lấy mẫu phân tầng theo độ dài, mật độ citation, jurisdiction/year, ngôn ngữ biểu đạt và trạng thái AU. Luôn dành một ngân sách nhỏ cố định cho hàng đợi khám phá. Raw-source lane vẫn độc lập và mọi case không AU vẫn hợp lệ. Không dùng “retrieved frequently” làm điều kiện duy nhất hoặc điều kiện ngầm để được enrich.

**Phép thử phân xử →** Khóa retriever ban đầu, so sánh ba trigger dưới cùng ngân sách: popularity-only, stratified-only và mixed exploration/exploitation. Đo Recall@50/100/200 riêng cho case chưa có AU, đoạn không citation, case dài ít AU và các strata có tần suất retrieval ban đầu thấp. Nếu popularity-only không làm giảm recall hoặc độ phủ semantic so với mixed trigger thì phản biện này bị bác bỏ.

### Phản biện 2 — Coverage ledger đang trộn “đã định địa chỉ” với “đã đọc ngữ nghĩa”

**Nhận định bị phản biện →** Agent A yêu cầu mỗi paragraph có một trạng thái như `unseen`, `examined_no_item`, `selected`, `uncertain`, `error`, `superseded_by_child`; paragraph không có trạng thái đồng nghĩa case chưa hoàn tất.

**Bằng chứng/phản ví dụ →** Thiết kế đồng thời tuyên bố AU được tạo lazy, nhưng điều kiện hoàn tất ở mức từng paragraph dễ buộc hệ thống phải triage toàn bộ case để biến `unseen` thành trạng thái kết thúc. Đó chính là kiểu quét bao phủ nhiều pha mà audit V15 cho thấy tốn token và vẫn có omission. Với case dài nhưng chỉ có ít AU, chi phí ledger semantic có thể gần bằng build-all. Ngược lại, nếu host tự gán mọi paragraph là `unseen`, ledger chỉ chứng minh parser đã liệt kê paragraph chứ không chứng minh model đã đọc hoặc không bỏ sót. Output hợp schema nhưng thiếu AU vẫn có thể đi qua nếu “coverage” chỉ là trường trạng thái được điền đủ.

**Hậu quả →** Hoặc thiết kế mất lợi ích lazy vì phải gọi model trên toàn source, hoặc trạng thái coverage tạo cảm giác hoàn tất giả. Hai ý nghĩa này cũng làm sai cache/resume: `unseen` là trạng thái hợp lệ của KB lazy, nhưng lại bị dùng như lỗi workflow.

**Phương án thay thế →** Tách hai ledger. `address_ledger` do host tạo cho toàn source, chỉ ghi segment id, offset, hash và tính liên tục; nó phải đầy đủ nhưng không hàm ý đã đọc. `semantic_work_ledger` là sparse log cho các bundle thực sự được xử lý, ghi `not_examined`, `candidate`, `accepted_for_index`, `rejected_with_reason`, `uncertain`, `error`. Một case lazy có thể hoàn tất về cấu trúc dù nhiều paragraph chưa được xét ngữ nghĩa; giao diện phải công khai trạng thái đó và raw-source fallback bảo vệ coverage.

**Phép thử phân xử →** Trên tập giữ riêng, so sánh ledger toàn paragraph với sparse semantic ledger dưới cùng recall target. Đo token, request, tỷ lệ omission qua human review, số paragraph bị tuyên bố `examined_no_item` sai và khả năng resume sau lỗi giữa case. Nếu ledger toàn paragraph cho semantic recall cao hơn có ý nghĩa với chi phí lifecycle chấp nhận được, có thể giữ thiết kế A.

### Phản biện 3 — Cửa sổ paragraph liền kề không phải hợp đồng đủ cho attribution và qualification

**Nhận định bị phản biện →** Agent A dùng bundle mặc định gồm paragraph hiện tại, paragraph trước/sau, heading và citation cục bộ; sau đó cho phép mở rộng theo paragraph, section hoặc citation khi cần.

**Bằng chứng/phản ví dụ →** Cơ chế mở rộng đang là khả năng tùy chọn, chưa phải nghĩa vụ kiểm chứng gắn với loại claim. Điều kiện có thể nằm ở nhiều paragraph trước; lời của đương sự hoặc án được trích có thể kéo dài qua nhiều đoạn trước khi tòa hiện tại phản hồi; court response có thể nằm xa citation mention hoặc ở cuối section. Model có thể thấy một mệnh đề đúng trong cửa sổ cục bộ nhưng gán nhầm speaker, bỏ điều kiện, hoặc coi proposition của cited authority là holding của receiving court. Cả ba lỗi đều có thể tạo output hợp schema.

**Hậu quả →** AU ngắn và rẻ nhưng sai về attribution, qualification hoặc treatment. Sai này nguy hiểm hơn omission vì AU được index như tín hiệu có vẻ đã xác minh, dẫn retrieval tới một diễn giải không được source hiện tại chấp nhận.

**Phương án thay thế →** Thay “adjacent context đủ trừ khi model yêu cầu thêm” bằng evidence obligations do host điều khiển. AU proposition cần content witness; attribution cần speaker/voice witness; mệnh đề có dấu hiệu điều kiện cần predecessor/section witness; treatment cần cả citation-side witness và receiving-court-response witness. Host cung cấp các thao tác deterministic như mở rộng đến đầu section, tìm mọi mention của cùng authority và quét forward đến đoạn có court-voice cue. Nếu obligation chưa đủ thì trạng thái phải là provisional, không được `accepted_for_index`.

**Phép thử phân xử →** Lập challenge set gồm điều kiện nằm cách ít nhất hai paragraph, court response nằm xa, chuyển speaker giữa party/cited court/current court và citation không có phản hồi rõ. So sánh fixed-adjacent, model-requested expansion và obligation-driven expansion về lỗi attribution/qualification/treatment, token và latency. Chỉ giữ obligation-driven nếu giảm lỗi đủ bù chi phí.

### Phản biện 4 — “Semantic verifier” chưa có tính độc lập và trạng thái `accepted` đang mạnh hơn bằng chứng

**Nhận định bị phản biện →** Agent A dùng một bước verifier semantic để kiểm tra attribution, điều kiện và duplicate trước khi AU được chấp nhận và cache/index.

**Bằng chứng/phản ví dụ →** Báo cáo chưa chốt verifier dùng evidence khác, prompt khác, model khác hay chỉ đọc lại cùng bundle. Nếu extractor và verifier cùng model, cùng context và cùng framing, lỗi có thể tương quan cao: cả hai cùng nhầm lời đương sự thành lời tòa, cùng bỏ điều kiện ở đoạn trước, cùng không thấy court response nằm xa hoặc cùng chấp nhận concept sai. Một bước gọi thứ hai không tự tạo tính độc lập. Ngoài ra, verifier item-by-item không phát hiện chắc chắn omission vì nó chỉ xem những item extractor đã sinh.

**Hậu quả →** Hệ thống trả thêm token và request nhưng `accepted` vẫn có thể chỉ nghĩa là “hai lần suy luận giống nhau”. Người dùng hoặc retrieval agent có thể hiểu trạng thái này thành kết luận pháp lý đã được xác nhận, trong khi schema PASS và agreement giữa hai call không phải semantic quality.

**Phương án thay thế →** Đổi tên trạng thái thành `accepted_for_index` và lưu vector kiểm tra riêng: `content_supported`, `attribution_supported`, `qualification_checked`, `treatment_two_witness`, `duplicate_status`, mỗi trường trỏ tới exact span. Dùng kiểm tra deterministic cho offset/hash/duplicate; chỉ dùng model review cho nghĩa khó. Khi cần verifier model, thay framing hoặc evidence order và đo error correlation; không bắt buộc model thứ hai nếu không chứng minh được giá trị. Omission phải được đánh giá ở bundle/case level trên mẫu độc lập, không thể suy ra từ item verifier.

**Phép thử phân xử →** So sánh extractor-only, same-model verifier, differently-framed verifier và human-reviewed sample. Đo precision từng chiều, omission recall, tỷ lệ lỗi chung giữa extractor/verifier và token trên mỗi AU hợp lệ. Nếu same-model verifier cải thiện đáng kể semantic precision/recall sau khi tính chi phí và không chỉ tăng schema pass rate, thiết kế A được giữ.

### Phản biện 5 — Sidecar vẫn quá rộng nếu chưa có default-off và tiêu chí kích hoạt từng loại

**Nhận định bị phản biện →** Agent A đề xuất sidecar chọn lọc gồm citation mention, authority identity, speaker, legal function, condition/exception, court response, treatment candidate, concept và structure, được chia Tier 0–3.

**Bằng chứng/phản ví dụ →** Các trường không có cùng độ tin cậy, chi phí hay giá trị retrieval. Offset/heading/citation mention có thể deterministic; speaker và function phụ thuộc văn cảnh; concept dễ gán sai khi thuật ngữ bề mặt giống nhau; treatment cần quan hệ giữa cited proposition và receiving court response. Nếu concept sai được dùng để mở rộng query hoặc ưu tiên AU, nó có thể làm recall xấu hơn source-only. Nếu sidecar được tạo cho mọi paragraph dài chỉ vì case “khó”, preprocessing có thể tốn hơn số lần corpus được dùng lại.

**Hậu quả →** Một “sidecar tùy chọn” trên sơ đồ có thể trở thành gói phụ thuộc mặc định trong runtime, kéo theo model/version invalidation, lỗi cục bộ, retry và chi phí truyền metadata. Khó biết cải thiện đến từ loại annotation nào và khó loại bỏ thành phần gây hại.

**Phương án thay thế →** Mặc định chỉ bật structural map và citation mention/normalization deterministic. Mỗi loại annotation còn lại là một feature flag, có cache namespace, version và ngân sách riêng. Speaker/function, concept và treatment chỉ được bật sau ablation chứng minh đóng góp dưới cùng retrieval budget và semantic non-inferiority. Concept chỉ là query hint có confidence, không được hard filter. Treatment không được loại case vì case distinguished/rejected vẫn có thể là noticed case cần retrieval.

**Phép thử phân xử →** Chạy incremental arms: source-only; +structure/citation; +speaker/function; +concept; +treatment, đồng thời chạy leave-one-component-out. Báo cáo Recall@50/100/200, attribution/treatment errors, total lifecycle token, latency và invalidation cost. Riêng concept phải có tập paraphrase và false-friend; nếu không tăng recall ổn định thì bỏ.

### Phản biện 6 — Quota cố định cho hai lane chưa bảo đảm hiệu quả và có thể che lỗi hợp nhất

**Nhận định bị phản biện →** Agent A bảo vệ raw-source fallback bằng dual-lane retrieval với quota độc lập cho source và AU, sau đó hợp nhất; cách này nhằm giữ case không có AU.

**Bằng chứng/phản ví dụ →** Quota cố định bảo vệ coverage tối thiểu nhưng không tự tối ưu recall dưới giới hạn K. Query có tín hiệu lexical mạnh có thể cần nhiều source hits; query diễn đạt ở mức proposition có thể hưởng lợi từ nhiều AU hits. Chia K cứng làm mất ứng viên tốt của lane phù hợp. Duplicate cùng case giữa hai lane cũng tiêu ngân sách nếu union diễn ra sau cắt quota. Case có adverse authority hoặc bị distinguish/reject vẫn phải được giữ dù treatment score thấp; một merge rule không rõ có thể vô tình demote chúng. Case không citation nhưng có lập luận hữu ích chỉ xuất hiện ở source lane.

**Hậu quả →** Combined retrieval có thể kém lane tốt nhất dù dùng nhiều index và tăng latency. Kết quả tổng thể che subgroup failure: AU-rich tăng nhưng AU-free, no-citation hoặc adverse-treatment giảm.

**Phương án thay thế →** Truy vấn hai lane song song, deduplicate theo case/evidence trước khi cắt K cuối và dùng rank fusion đã khóa tham số. Đặt một source floor nhỏ để bảo đảm fallback, phần ngân sách còn lại phân bổ thích nghi theo score dispersion/overlap đã hiệu chỉnh trên calibration, không theo nhãn gold. Treatment chỉ là metadata giải thích, không là dấu loại trừ. Luôn báo cáo source-only, AU-only và combined cùng compute budget.

**Phép thử phân xử →** So sánh fixed quota, adaptive quota và union-then-RRF dưới cùng số hit được đọc và cùng latency budget. Đo toàn tập cùng các subgroup: không AU, không citation, concept mismatch, long-few-AU, distinguished/rejected và citation bị che. Nếu fixed quota đạt recall và độ ổn định tốt ngang hoặc hơn, ưu tiên nó vì đơn giản hơn.

### Phản biện 7 — “Heading-only reject” cần là demotion cấu trúc, không phải quy tắc loại nội dung

**Nhận định bị phản biện →** Agent A yêu cầu heading-only phải bị reject trong bước kiểm tra sau mỗi case.

**Bằng chứng/phản ví dụ →** Nhiều heading chỉ là nhãn mục và không nên thành AU, nhưng một heading có thể chứa chuẩn pháp lý, kết luận ngắn, điều kiện hoặc tên issue cần thiết để hiểu paragraph sau. Một đoạn không citation vẫn có thể chứa lập luận hữu ích; tương tự, một segment được parser gắn `heading` không đồng nghĩa không có nội dung pháp lý. Parser HTML/text cũng có thể gắn nhầm paragraph ngắn thành heading.

**Hậu quả →** Hard reject theo loại cấu trúc gây false negative và trái với nguyên tắc annotation không làm mất source. Nó cũng có thể làm mất điều kiện đặt ở heading trước body hoặc khiến exact-span reconstruction thiếu tiêu đề định nghĩa phạm vi.

**Phương án thay thế →** Gắn `structure_only=true` và demote khỏi AU candidate khi heading không có proposition, nhưng giữ nó trong source index và context expansion. Cho phép ghép heading với paragraph kế tiếp bằng provenance hai span. Chỉ reject AU heading sau kiểm tra nội dung, không dựa duy nhất vào nhãn parser; lỗi phân loại heading phải có đường quay về source.

**Phép thử phân xử →** Lấy mẫu phân tầng heading ngắn/dài, heading có modal/legal cue và parser-ambiguous segment. Đo số heading chứa proposition/condition hữu ích, tác động Recall@K và số false AU. Nếu không có heading hữu ích và demotion không cải thiện recall, quy tắc reject đơn giản của A là đủ.

### Phản biện 8 — Lazy cache trong evaluation có thể gây leakage và break-even chưa tính trạng thái corpus thay đổi

**Nhận định bị phản biện →** Agent A đề xuất materialize AU khi retrieval cần, cache kết quả và tính break-even theo chi phí build so với số lần tái sử dụng.

**Bằng chứng/phản ví dụ →** Nếu held-out query kích hoạt enrichment rồi các query sau dùng cache đó, index thay đổi trong lúc đánh giá; thứ tự query trở thành biến ẩn. Với query bị che một citation, enrichment tạo từ bản corpus có citation không bị che có thể vô tình khôi phục trực tiếp đáp án nếu hợp đồng masking không tách query evidence, source evidence và gold. Một citation bị che trong source hoặc một source version khác cũng làm cache cũ không hợp lệ. Công thức break-even chỉ theo token thành công sẽ bỏ qua failed calls, retry, semantic repair, local preprocessing, storage, index rebuild và latency lạnh/ấm.

**Hậu quả →** Kết quả retrieval không tái lập, có nguy cơ leakage, và con số amortization quá lạc quan. Một run “ấm” có thể trông rẻ chỉ vì đã hưởng artifact sinh từ chính tập đánh giá trước đó. Việc attribution/treatment đúng trên unmasked evidence không chứng minh pipeline tuân thủ điều kiện masked query.

**Phương án thay thế →** Đánh giá trên snapshot KB/index đóng băng trước khi chạy holdout; cấm materialization từ held-out query ghi ngược vào snapshot dùng chấm điểm. Đo riêng cold run, warm production simulation và offline build. Cache key phải chứa source hash/version, segmentation version, stage, tool/model/prompt/schema version và masking policy. Báo cáo mọi request, retry/repair, run lỗi và run hoàn tất. Với masked query, không dùng bản query không che hoặc gold; corpus evidence hợp lệ phải được phân biệt rõ với dữ liệu bị cấm, và ablation thêm trường hợp citation bị che trong source.

**Phép thử phân xử →** Chạy cùng tập query theo nhiều thứ tự trên snapshot frozen và mutable; so sánh output, recall, token và cache hit. Thực hiện audit provenance cho mọi authority được phục hồi trong masked-query experiment. Tính break-even với tổng chi phí lifecycle quan sát được. Nếu mutable lazy cache không làm kết quả phụ thuộc thứ tự và không có leakage, có thể dùng nó trong evaluation; nếu không, chỉ dùng trong mô phỏng production tách biệt.

## 3. Kiểm tra độ phủ tám tình huống bắt buộc

| Tình huống | Phản biện xử lý | Cách bảo vệ trong đề xuất sửa |
|---|---:|---|
| Đoạn không citation nhưng có lập luận hữu ích | 1, 6, 7 | Source lane độc lập; exploration queue; không loại theo citation/heading |
| Lời đương sự bị hiểu thành lời tòa | 3, 4 | Attribution obligation và exact witness; verifier theo chiều riêng |
| Điều kiện nằm ở đoạn trước | 3, 7 | Section/predecessor expansion; heading được giữ làm context |
| Court response nằm xa citation | 3, 4 | Hai witness cho treatment; tìm mọi mention và quét forward |
| Concept sai | 5, 6 | Concept default-off, chỉ là hint, có ablation và source fallback |
| Source dài nhưng ít AU | 1, 2 | Stratified exploration; sparse semantic ledger, không quét toàn case bắt buộc |
| Một citation bị che | 6, 8 | Frozen snapshot, provenance audit, tách query/corpus/gold và source-mask ablation |
| Output hợp schema nhưng bỏ sót | 2, 4 | Không suy semantic completeness từ ledger/schema; đánh giá omission độc lập |

Hai tình huống liên quan cũng được giữ rõ: case bị distinguish/reject không bị treatment filter loại ở Phản biện 5–6; annotation thiếu hoặc lỗi không làm case biến mất vì source lane và `open_span` vẫn hoạt động.

## 4. Steelman: phiên bản mạnh nhất của thiết kế Agent A

Phiên bản mạnh nhất của Agent A không phải một hệ thống “annotation trước, retrieval sau”. Nó là source-first KB với ba mức trách nhiệm tách rõ:

1. Host giữ source bất biến, segment/offset/hash, version, provenance và API mở exact span/context.
2. Retriever luôn có source-only lane hoàn chỉnh; AU là materialized view chọn lọc để giảm text phải đọc lại, không phải đơn vị duy nhất có thể được tìm.
3. Annotation sidecar là chỉ mục phụ có confidence/provenance; từng loại được đưa vào qua ablation, và lỗi annotation không được trở thành lỗi coverage.

Trong cách hiểu mạnh nhất, coverage ledger của A là công cụ quan sát những gì đã hoặc chưa được xử lý, không phải bằng chứng mọi paragraph đã được đọc đúng. `verified AU` chỉ có nghĩa đã đáp ứng một tập kiểm tra công khai để được index, không phải holding pháp lý đã được xác nhận. Cơ chế mở rộng context không phụ thuộc hoàn toàn vào model mà được host kích hoạt khi claim có attribution, condition hoặc treatment obligation. Dual-lane retrieval được chấm cùng các subgroup AU-free và adverse-treatment. Nếu triển khai theo cách này, thiết kế A giải quyết đúng phần lớn thất bại V13–V15 mà không lặp lại dynamic global schema hoặc full-corpus multi-pass extraction.

Đóng góp mạnh nhất của A so với báo cáo B ban đầu là trình tự ablation cụ thể từ B0 đến B5 và việc mô tả các trạng thái paragraph/error chi tiết hơn. Đây là nền tốt để biến bất đồng thành thí nghiệm thay vì ghép mọi enrichment vào một pipeline.

## 5. Những điểm tôi thay đổi quan điểm sau khi đọc Agent A

1. **Chuyển từ offline fixed two-call làm ứng viên chính sang lazy AU có exploration.** Báo cáo B ban đầu thiên về pipeline hai call cố định trên các candidate bundle đã chọn. A đúng ở chỗ chưa có bằng chứng đủ để trả chi phí AU trên toàn corpus. Tôi giữ hai call như một arm thực nghiệm, không còn xem đó là mặc định.

2. **Giữ coverage ledger nhưng hạ ý nghĩa của nó.** Ban đầu tôi ưu tiên batch checkpoint và omission audit hơn trạng thái paragraph. Sau thiết kế A, tôi cho rằng ledger mức segment hữu ích cho resume và phát hiện khoảng trống workflow, miễn là tách address coverage khỏi semantic examination và không biến `unseen` thành lỗi của KB lazy.

3. **Chấp nhận ablation theo từng loại sidecar thay vì một gói enrichment.** Chuỗi B0–B5 của A tốt hơn cách gom annotation bundle trong thiết kế B ban đầu vì nó cho phép loại concept hoặc treatment nếu gây hại dù structure/citation có ích.

4. **Mở rộng context phải là API hạng nhất.** Thiết kế A nêu rõ mở theo paragraph, section và citation. Tôi nâng phần này từ cơ chế hỗ trợ thành evidence resolver có nghĩa vụ cụ thể; retrieval interface không nên chỉ trả snippet cố định.

Tôi chưa thay đổi quan điểm ở ba điểm: source-only fallback phải luôn độc lập; full KG và model phụ chưa được mặc định; schema/completion/provider success không được dùng làm proxy cho semantic quality.

## 6. Thiết kế Agent B đã sửa

### 6.1. Kiến trúc khuyến nghị

Thiết kế sửa, gọi tạm là **source-first retrieval với sparse verified views**, gồm sáu lớp. Chỉ hai lớp đầu là bắt buộc để có baseline chạy được; các lớp sau phải vượt qua decision gate.

#### Lớp 0 — Canonical source và structural manifest

- Lưu source nguyên văn, `case_id`, `source_version`, content hash và provenance.
- Host tạo paragraph/sentence spans, heading map, citation mentions có thể nhận diện deterministic và quan hệ parent/child.
- `address_ledger` chứng minh offset liên tục, hash đúng và source bất biến; không tuyên bố đã hiểu ngữ nghĩa.
- Mọi artifact downstream có fingerprint gồm source hash, segmentation version, tool/model/prompt/schema version và masking policy.

#### Lớp 1 — Baseline source-only

- Index paragraph và cửa sổ source bằng BM25+dense hiện có; không cần AU hoặc annotation.
- Query hai retriever nếu hạ tầng đã có, hợp nhất theo case và giữ evidence span.
- Cung cấp `search_source`, `get_case`, `open_span`, `expand_context`.
- Đây là baseline bắt buộc và cũng là fallback production. Nếu enrichment không vượt baseline dưới cùng budget thì dừng ở đây.

#### Lớp 2 — Candidate queue cho enrichment

- Hàng đợi exploitation nhận các span được retrieval, mở context nhiều hoặc gây bất đồng source/AU.
- Hàng đợi exploration lấy mẫu phân tầng từ corpus, kể cả case chưa từng được retrieval, no-citation và long-few-AU.
- Candidate chỉ là công việc chờ xử lý, không được dùng như semantic label.
- Ngân sách và nguồn trigger được log để đo bias.

#### Lớp 3 — Evidence resolver

- Host bắt đầu bằng bundle nhỏ, nhưng không coi paragraph liền kề là đủ mặc định.
- Mỗi loại đề xuất sinh evidence obligations:
  - proposition: exact content witness;
  - attribution: speaker/current-court witness;
  - condition/exception: dependency witness trong predecessor hoặc section;
  - treatment: citation-side witness và receiving-court-response witness;
  - concept: supporting phrase và confidence, không là kết luận pháp lý.
- Resolver có thao tác mở predecessor/successor, section, mọi mention của authority và forward response. Thiếu witness tạo `provisional`, không tạo `accepted_for_index`.

#### Lớp 4 — Sparse AU materialization và verification

- Extractor dùng fixed batch schema nhỏ, giới hạn số item và output; host không gửi dynamic global enum.
- Structural validator kiểm offset/hash/source quote/duplicate trước.
- Semantic review chỉ chạy cho candidate khó hoặc có obligation chưa rõ; không bắt buộc call thứ hai cho mọi item.
- Lưu vector kiểm tra theo chiều thay vì một cờ `verified` duy nhất.
- `semantic_work_ledger` chỉ ghi bundle đã xử lý. Batch commit atomic; lỗi batch không xóa AU hợp lệ của batch khác.

#### Lớp 5 — Optional sidecars

- Mặc định bật: structure và citation mention/authority normalization deterministic nếu độ chính xác đủ.
- Mặc định tắt cho tới khi qua ablation: speaker/function, condition tag, concept và treatment candidate.
- Mỗi sidecar có namespace/version/cache riêng; có thể rebuild hoặc vô hiệu hóa độc lập.
- Annotation chỉ hỗ trợ ranking, navigation và context expansion; không hard filter.

#### Lớp 6 — Retrieval hợp nhất

- Chạy source lane và AU lane song song; source lane có floor để case AU trống không biến mất.
- Deduplicate theo case/evidence trước khi cắt K cuối; rank fusion và adaptive allocation chỉ dùng tham số khóa trên calibration.
- `search_au` trả proposition cùng exact witness và verification dimensions.
- Treatment, speaker và concept được hiển thị như predicted metadata với confidence/provenance. Case bị distinguished hoặc rejected vẫn là ứng viên retrieval.

### 6.2. Dữ liệu lâu dài, dữ liệu suy ra và trạng thái tạm

| Nhóm | Nội dung | Quy tắc |
|---|---|---|
| Canonical lâu dài | source, case metadata, version, hash, offsets | Bất biến theo source version |
| Derived có version | structural map, citation map, AU, sidecars, index | Rebuild được; không sửa canonical source |
| Trạng thái công việc | candidate queue, semantic ledger, retry/error, budget | Không dùng làm evidence pháp lý |
| Query-time tạm | query representation, lane scores, fusion trace, opened spans | Không ghi ngược vào evaluation snapshot |

### 6.3. Failure contract, cache, invalidation và resume

- Phân loại tối thiểu: `provider_unavailable`, `empty_or_whitespace`, `constrained_decoding`, `schema_invalid`, `source_mismatch`, `semantic_uncertain`, `workflow_incomplete`.
- Retry chỉ dành cho lỗi có khả năng tạm thời hoặc parse có chiến lược sửa cụ thể; semantic uncertainty không retry vô hạn.
- Cache hit chỉ hợp lệ khi toàn bộ fingerprint khớp. Thay source, segmentation, prompt/schema/model hoặc masking policy sẽ invalid artifact liên quan.
- Resume từ batch atomic cuối; idempotency key ngăn apply lặp. Một batch lỗi không làm mất source hit hay AU đã commit ở batch khác.
- Báo cáo run lỗi tách khỏi run hoàn tất; provider completion và schema PASS là telemetry, không phải semantic score.

### 6.4. Interface tối thiểu cho retrieval

| Tool | Đầu vào chính | Đầu ra bắt buộc |
|---|---|---|
| `search_source` | query, K, optional filters | case id, source version, exact span, score, index version |
| `search_au` | query, K, verification threshold tùy chọn | AU, exact witness, dimensions, confidence, score |
| `get_case` | case id, source version | metadata, source status, annotation coverage/status |
| `open_span` | case id, source version, offsets | exact immutable text, hash, provenance |
| `expand_context` | span, direction/mode/budget | adjacent/section/citation-linked spans và lý do mở |
| `get_annotations` | span hoặc case id, type | predicted metadata, confidence, generator/version, evidence |

Tool contract phải cho phép retrieval agent bắt đầu từ source hit, xem AU như đường tắt, rồi quay lại exact source để kiểm chứng. Không endpoint nào được trả một annotation dự đoán như fact đã được tòa xác nhận.

### 6.5. Evaluation và decision gates

1. **B0 — source-only frozen baseline.** Đo Recall@50/100/200, token/query, latency và subgroup failures.
2. **B1 — lazy AU với popularity-only trigger.** Dùng để kiểm tra giả thuyết tối giản của A.
3. **B2 — lazy AU với mixed exploration/exploitation.** Quyết định trigger nào giữ coverage tốt hơn dưới cùng ngân sách.
4. **B3 — + deterministic structure/citation.** Đây là enrichment có xác suất được giữ cao nhất nhưng vẫn phải đo.
5. **B4 — + obligation-driven semantic review.** So với extractor-only và same-model verifier.
6. **B5a/B5b/B5c — lần lượt +speaker/function, +concept, +treatment.** Không gộp ba loại vào một arm.

Tất cả arm dùng snapshot source/index khóa trước holdout. Năm án calibration chỉ dùng phân tích lỗi và chỉnh hợp đồng; tập xác nhận độc lập phải được khóa trước khi xem kết quả. Báo cáo cold build, warm reuse, failed runs và completed runs riêng. Mục tiêu giảm 30% tổng token chỉ được công nhận nếu retrieval và semantic metrics không suy giảm ngoài ngưỡng non-inferiority được đăng ký trước.

Mỗi thành phần được giữ khi thỏa một trong hai điều kiện: tăng retrieval/semantic quality dưới cùng lifecycle budget, hoặc giảm lifecycle token/latency rõ ràng mà giữ chất lượng tương đương. Consensus của hai agent, schema pass hoặc completion rate không thay thế điều kiện này.

### 6.6. Break-even đã sửa

Với component enrichment `c`, đo:

`C_build,c = token + request + retry/repair + local compute + index/storage + failed-run allocation`

`S_query,c = median cost baseline/query - median cost enriched/query`, chỉ tính khi chất lượng non-inferior.

`Q_break-even,c = C_build,c / S_query,c` khi `S_query,c > 0`.

Đối với lazy component, `C_build,c` phải được báo theo cả cold sequence và steady-state, cùng phân phối số lần một artifact được tái sử dụng. Nếu `S_query,c <= 0`, component không có điểm hòa vốn về chi phí và chỉ có thể được giữ nếu tăng chất lượng đủ để biện minh. Không dùng reserve USD/request làm actual cost.

## 7. Kết luận quyết định của Agent B sau phản biện

Tôi chấp nhận lõi kiến trúc của Agent A sau bốn sửa đổi bắt buộc: trigger lazy phải có exploration; coverage ledger phải tách structural và semantic; context expansion phải dựa trên evidence obligations; evaluation phải dùng snapshot đóng băng và accounting lifecycle đầy đủ. Tôi chưa chấp nhận speaker/function, concept, treatment sidecar hoặc semantic verifier như thành phần mặc định. Chúng là các ablation độc lập.

Baseline được khuyến nghị để triển khai trước là canonical source + structural manifest + source-only retrieval + exact-span/context tools. Kiến trúc ứng viên tiếp theo là lazy sparse AU với mixed candidate queue và obligation-driven verification. Full KG, build-all AU và model phụ không nằm trong kiến trúc khuyến nghị hiện tại vì chưa có bằng chứng cho điểm hòa vốn hoặc cải thiện coverage trên English Canadian case law của COLIEE.
