# Đưa cách soạn AU của KOS vào pipeline và cải tiến

Ngày 2026-10-24. Đây là **thiết kế tiếp theo**, chưa sửa runtime K0, prompt, grammar, endpoint hoặc artifact đã chạy. Bổ sung cho 04/05/09/37; không mở K1, retrieval, matching NN–AU hay reranker.

## 1. Bằng chứng và vấn đề thực tế

Nguồn KOS local được kiểm tra trực tiếp:

- [SCHEMA.md](G:/Legal-AI/kos_sample/SCHEMA.md): nội dung AU gồm Claim, Evidence span, Why notice-worthy và Limits; metadata tách khỏi substance.
- [Log family000002](G:/Legal-AI/kos_sample/_meta/extract_log_000002_family_20260826.md): agent chọn doctrine spans, soạn body, giữ giới hạn và không nối các Need thiếu doctrinal overlap. Log này không chứng minh recall hoặc entailment.
- [AU011904 no-danger](G:/Legal-AI/kos_sample/cases/011904/authority_units/au-011904-exhaustion-not-danger.md): ví dụ gom rule, rationale và exception thành điểm có thể viện dẫn.
- [Priority lịch sử](G:/Legal-AI/kos_sample/_meta/s1d_extract_priority.md) yêu cầu min5AU/case; [log000031](G:/Legal-AI/kos_sample/_meta/extract_log_000031_family_20260827.md) ghi 5AU mỗi candidate. Không tiếp nhận quota này: nó không chứng minh coverage và có thể khuyến khích chọn miễn cưỡng.

Skill/prompt gốc mà schema dẫn tới không có trong checkout local. Extract strategy v1 tự ghi đã superseded; không suy ra workflow hay model hiện tại của KOS từ tài liệu lịch sử. Không sao chép gold-family selection, KOS answers/labels hoặc masked authority identity vào authoring.

K0 đã thực thi: 5 request hợp giao thức nhưng0AU; nguồn thực sự có legal points. Diagnostic riêng cho thấy CPU replay cho phép AU không rỗng, synthetic có grammar trả0AU, bỏ grammar thì có rule/exception nhưng sai envelope, real one-turn cũng0AU. Không chạm output cap. Nguồn: `pipeline_v1/outputs/k0_ready_20261023/live/run.json` và `pipeline_v1/outputs/k0_diagnostic_v3_20261023/EVALUATION.md`. Đây là bằng chứng cần sửa cách hướng dẫn/kiểm tra, **chưa chứng minh grammar hỏng hoặc model đủ năng lực authoring bản án**.

## 2. Phương án được chọn

```text
Source bất biến + địa chỉ local
  → CaseWork / catalog nguồn đã mở
  → agent đọc và soạn legal point theo mẫu KOS đã đơn giản hóa
      ↔ mở/tìm nguồn khi thiếu thông tin, trong scope và budget
  → host kiểm wire/evidence và commit từng AU
  → ghi nhận phạm vi đã xem và kết quả có AU / không có AU / bất định
  → nếu kết quả rỗng đáng nghi: một lượt validate có giới hạn
      → giữ nguyên / bổ sung AU có evidence / giữ bất định
  → snapshot draft có reading state và trạng thái review riêng
```

Không thêm planner hoặc verifier toàn corpus. Bước validate là nhánh có điều kiện, không thêm một vòng cho mọi AU. Positive control phải qua trước khi đưa nhánh thiết kế mới chạy trên án thật.

## 3. Cách soạn điểm pháp lý

Trong một lượt đọc, agent thực hiện cùng một nhiệm vụ soạn nội dung, không trả checklist dài:

1. Xác định điểm mà vụ khác có thể viện dẫn: rule, test, interpretation, application có lập luận, rationale hoặc exception có substance. Xét cả nội dung không marker/citation.
2. Soạn Claim đủ nghĩa: ai có quyền/nghĩa vụ, phép kiểm tra nào, khi nào áp dụng; giữ người phát biểu và trạng thái adoption/reporting.
3. Gom rationale/exception trực tiếp làm rõ Claim; tách các quyền, nghĩa vụ hoặc test độc lập. Không ghép chỉ vì cùng Issue, không tách theo câu hay block.
4. Chọn evidence đã mở hỗ trợ cả Claim và Limits. Context thuần không tự là AU; citation hoặc tên điều luật không tự chứng minh substance. Party argument không được nâng thành holding; khi nguồn chỉ có lời bên và chưa rõ treatment thì giữ bất định hoặc mở thêm.

Wire AU tiếp tục giữ `claim`, `kind` nullable, `evidence_ids`, `limits` nullable; optional revision theo contract hiện có. Không buộc model đếm offset hoặc lặp case/hash. Host dựng provenance từ catalog. `Why notice-worthy` là câu hỏi lựa chọn trong hướng dẫn, **không thêm một đoạn output bắt buộc**. Không thêm speaker/condition/Issue classifier hoặc NER mặc định.

## 4. Dạy contract thay vì ép số lượng

Prompt authoring mới dùng ví dụ **JSON đầy đủ**, cùng envelope thật, thay vì chỉ liệt kê tên field. Có ba ví dụ ngắn, tổng hợp và độc lập với tập đánh giá:

- Có AU: một point gồm rule và exception, Claim/Evidence/Limits đúng kiểu.
- Không có AU: một đoạn chỉ ghi sự kiện hoặc thủ tục thuần, trả AU rỗng với lý do phù hợp.
- Bất định: reported argument thiếu phản hồi tòa hoặc thiếu premise; chọn mở nguồn/needs_context, không bịa rule và không kết luận no-AU.

Ví dụ nằm ngoài SOURCE, ghi rõ IDs minh họa không phải evidence của case. Không đưa KOS Claim hoặc lời giải failure set vào prompt. Ngoài thử đủ ba ví dụ, có đối chứng chỉ một ví dụ dương để đo chi phí bổ sung; không mặc định càng nhiều few-shot càng tốt.

Giữ `aus` có thể rỗng, không min1AU trên source thật, không min5AU/case, không target số AU bằng KOS. Multi-AU vẫn được phép; transport cap không là quota. Positive control có đúng một AU trên nguồn tổng hợp chỉ kiểm khả năng thực thi, không áp dụng thành quota trên bản án.

Claim500/Limits250 tiếp tục chỉ cảnh báo; không shortening/repair vì dài. Truncation không là bằng chứng no-AU và không được đánh dấu đã đánh giá xong.

## 5. Kết quả đọc: tách thông tin đã biết khỏi lời tự báo

Không thêm phân loại bắt buộc cho từng sentence/block. Chỉ ghi kết quả đối với **scope mà agent đang thực sự đánh giá**, không áp dụng cho toàn case còn chưa đọc.

`ReadAssessment` là record host lưu ngoài AU:

| Trường | Quyết định |
|---|---|
| case/source/request/scope refs | Host suy từ catalog và response; không yêu cầu model lặp |
| result | `has_au`, `no_au_candidate`, `uncertain` |
| reason | Enum ngắn hoặc null, không yêu cầu giải thích tự do |
| basis | `author_self_report` hoặc `agent_checked`; không human gold |
| checked_request_id | Null hoặc receipt của một lượt validate |

`has_au` chỉ nói có AU được đề xuất, không xác nhận đã tìm đủ hoặc đúng semantic. `no_au_candidate` là nhận định âm cần giữ provenance, không là bằng chứng vắng AU tuyệt đối. `uncertain` không được tính thành negative. Source chưa đọc vẫn `not_assessed`, nằm trong ReadLedger, không cần model phát sinh record cho nó.

Thiết kế wire v1 ở dưới đã thử trong40 và có mâu thuẫn assessment. [Bản sửa41](41_read_assessment_contract_v2.md) thay phần scope list: root mới là `aus`, `empty_reason`, `next_action`, không còn `assessed_scope_ids` từ model; host suy phạm vi/states conservative. Wire AU không đổi. Các mô tả `assessed_scope_ids` dưới đây giữ để giải thích v1, không dùng làm yêu cầu output của v2. `empty_reason` giữ các giá trị:

- `no_independent_legal_point`: không thấy điểm pháp lý độc lập trong phần được đánh giá, ví dụ facts/thủ tục thuần;
- `unadopted_argument_only`: chỉ có party submissions; đã kiểm treatment liên quan trong phạm vi được phép và không thấy legal point độc lập của tòa hoặc reported authority. Nếu chưa đủ treatment thì dùng `insufficient_context`;
- `citation_without_substance`: chỉ có citation/reference, không có proposition được nêu;
- `insufficient_context`: thiếu premise, attribution hoặc treatment;
- `uncertain`: chưa quyết định được.

Với AU không rỗng, `empty_reason=null`; không yêu cầu model giải thích vì sao mỗi AU đáng viện dẫn. Với AU rỗng **và có kết luận assessment**, reason bắt buộc; lượt chỉ navigation chưa kết luận được phép null và không sinh ReadAssessment. Ba reason đầu chỉ áp dụng cho tập `assessed_scope_ids` cùng kết quả mà model thực sự đã xem; host lưu `no_au_candidate`. Hai reason sau giữ `uncertain` cho scope chưa resolved; không cho reason đó chứng nhận đã hoàn tất semantic assessment. `assessed_scope_ids` rỗng được phép khi lượt đó chỉ navigation. Nếu response chứa AU nhưng vẫn còn scope chưa đánh giá, scope ấy giữ residual/not_assessed; không suy `has_au` thành complete.

Không áp một reason lên nhiều scope khác kết quả. Ví dụ A chỉ facts, B thiếu treatment: chỉ A nằm trong tập assessed với reason âm; B giữ residual hoặc unresolved theo hành động cần context, không kế thừa nhãn no-AU của A. Không thêm request riêng chỉ để phân loại B. Khi có AU và `empty_reason=null`, uncertainty/residual trước đó vẫn được giữ, không bị xóa vì response có kết quả dương.

`unadopted_argument_only` chỉ nói về lời bên không cung cấp authority độc lập; không áp dụng máy móc cho reported precedent, dissent, adverse authority hoặc một rule được trình bày để phân biệt/bác bỏ. Các nội dung đó vẫn có thể cung cấp legal point với attribution/treatment/limits đúng. Không xác định được treatment từ nguồn đã mở thì chọn uncertain thay vì kết luận âm.

Context có thể hỗ trợ AU ở scope khác mà không mang legal point độc lập; vì vậy host không dùng đơn thuần giao nhau evidence để tự xác nhận no-AU đúng hay sai. Host chỉ kiểm type, IDs, trạng thái và mâu thuẫn giao thức; kiểm ngữ nghĩa là phần đánh giá riêng.

## 6. Validate có điều kiện, không ép sửa

Trong pilot kế tiếp, trigger mặc định duy nhất là **CaseWork kết thúc với0AU**. Đây chỉ là cờ nghi ngờ, không khẳng định án bắt buộc có AU. Positive control fail là lỗi cả cấu hình: dừng trước case dispatch, không gọi validate hàng loạt để cứu nó.

Host được chạy **tối đa một lượt validate/case**, tính trong cap chung12POST/30000token của K0; tối đa3 lượt bổ sung cho3case. Không tự tăng cap hoặc tạo output root mới để retry. Nếu nguồn không vừa một request6000input/output800 hoặc budget còn lại không đủ, ghi `validation_not_run`/uncertain; không chọn một mẩu nhỏ rồi công bố đã kiểm cả case. K0 chỉ được đọc lại đúng union đã gửi; không thêm source qua KOS, review hoặc bản không che.

Giới hạn một lượt tính tích lũy qua resume, gắn case/source, phạm vi work, validation policy và parent draft revision. Receipt validate làm checkpoint độc lập. Source/draft phụ thuộc đổi làm review cũ hết hiệu lực, nhưng không tự cấp lại lượt hoặc chạy lại authoring; cần workload/budget mới được cho phép. Nguồn ngoài union K0 vẫn not_assessed dù cả authoring lẫn validate kết thúc.

Lượt validate nhận nguyên văn scope, draft nếu có và lý do ngắn đã trả; không được đưa lời giải reviewer/KOS. Câu hỏi cân bằng: xác nhận không có point độc lập, chỉ ra point bị bỏ có evidence, hoặc báo chưa đủ thông tin. Không dùng hướng dẫn “hãy tìm ít nhất một AU”. Agent được giữ kết quả rỗng. Nếu có bổ sung thì commit draft mới, không xóa AU khác; nếu vẫn rỗng hoặc bất định thì kết thúc nhánh, không lặp tới khi có AU.

Đây là kiểm tra lại của model, chưa là bằng chứng độc lập rằng không bỏ sót. Giữ model9B ban đầu để cô lập phương pháp; không âm thầm đổi model. Khi đã có baseline tốt, audit mẫu cả scope `no_au_candidate` lẫn `has_au` để phát hiện point thứ hai bị bỏ trong scope đã có AU. Mẫu đó khóa trước output, có ngân sách riêng; chưa bật thành pha runtime mặc định. Báo riêng unread, không gọi sample recall là recall toàncase. Không dùng thêm heuristic/NER để chọn lại tất cả scope trước khi có bằng chứng lợi ích.

## 7. Chi phí và quy mô

| Việc | Ai/thời điểm | Chi phí và xử lý lỗi |
|---|---|---|
| Source/catalog/ReadLedger | Host, corpus-time | 0tokenLLM, báo CPU/storage; source đổi invalidation đúng dependency |
| Ví dụ contract | Prompt cố định theo version | Tính token mỗi request thực gửi; prefix cache không đồng nghĩa miễn phí |
| Soạn AU và assessment | Cùng lượt authoring | Không gọi model riêng chỉ để gán nhãn; không bắt mọi block được đọc |
| Materialize/read-state | Host sau receipt | Record gọn, source chỉ tham chiếu; intent/receipt trước commit |
| Validate0AU | Model khi trigger và còn reserve | Một lượt/case, mọi output/retry/source lặp tính vào tổng; không auto-repair no-AU |
| Audit omission | Workload đánh giá riêng | Tính cả token reviewer/nhãn khi có; không lẫn vào cost authoring |

Cache key bao gồm example/prompt/grammar/schema/assessment/validation policy và source/catalog version. Semantic validate là job khác có parent receipt, không là retry transport. Resume không gọi lại job hợp lệ; usage/outcome unknown không cho POST mới. Không biến cap, hết budget hoặc output lỗi thành no-AU.

Không cam kết vừa không bỏ AU trong mọi trường hợp vừa không đọc hết corpus. Thiết kế giữ visible residual và đo tradeoff chất lượng/chi phí; không che phần chưa đọc bằng nhãn âm. Không có lời hứa giảm token từ ba ví dụ hoặc validate.

## 8. Trình tự thử và cổng chọn/bỏ

1. **Control contract trước:** giữ grammar/model/caps K0, chỉ bổ sung ví dụ JSON dương tổng hợp đầy đủ; so với control cũ bằng job/hash riêng. Chưa thêm `empty_reason`. CPU/endpoint đều phải tạo được AU hợp wire và giữ exception. Thất bại thì dừng; thí nghiệm grammar JSON tổng quát là arm chẩn đoán riêng, không fallback runtime âm thầm.
2. **Cân bằng dương/âm:** thêm ví dụ âm/bất định; kiểm rule không marker, exception, nhiều point độc lập, pure fact, party argument chưa được tiếp nhận, missing premise và citation-only. Khóa ba nhóm dương/âm/bất định, mỗi nhóm3 biến thể nội dung tổng hợp; tình huống multi-AU nằm trong nhóm dương. Không chấm đúng vì có AU hoặc vì JSON valid; uncertainty hợp lý không bị ép thành no-AU. Ví dụ trong prompt khác cả source, actor, exception và evidence IDs của control; giữ biến thể chưa dùng tuning. Không tính sao chép ví dụ thành authoring đạt.
   Sau khi thêm `empty_reason` hoặc đổi bất kỳ wire/grammar nào, phải chạy lại controls dương/âm/bất định/multi-AU trên **contract cuối** trước case dispatch. Native CPU chỉ xác minh grammar/mask chấp nhận witness, không tự tạo AU; endpoint control mới xác minh generation quan sát được. Test thêm A-facts/B-missing-treatment, navigation-only null, có một AU nhưng còn point/residual, tòa bác lời bên bằng một test và reported rule chưa được current court adopt.
3. **Authoring cùng nguồn:** chạy union K0 cũ, thêm record lý do gọn theo wire mới; giữ model/source/retrieval/caps. So grouping, actor, attribution, qualification, omission theo legal point; nhiều AU có thể cùng hỗ trợ một point, không chấm số lượng bằng KOS.
4. **Giá trị nhánh validate:** dùng receipt authoring đã khóa làm R0; R1 chỉ thêm một validate0AU theo cùng policy. So gain/loss và tổng cost bao gồm R0, không chỉ token lượt validate. Đầu ra bổ sung sai hoặc chỉ làm tăng AU count không là cải thiện. Nếu authoring không còn0AU, nhánh là no-op, chưa được chứng minh hữu ích; audit omission cục bộ thuộc workload đánh giá riêng.
5. **Held-out rồi K1:** chỉ sau control và calibration đạt, khóa case giữ riêng; không dùng các5ánKOS đã tuning làm xác nhận tổng quát. K1 phải có budget, review và coverage theo nguồn chưa đọc riêng; chưa triển khai trong thay đổi này.

Giữ riêng: tỷ lệ bỏ sót point, tỷ lệ AU được nguồn hỗ trợ, false positive trên negative controls, lỗi speaker/qualification, mức fragmentation/grouping, hợp lý của uncertainty và accuracy no-AU được audit. Đo input/output/reasoning, POST/tool/retry, text lặp, latency/GPU, startup và failed runs. Khi chất lượng chưa tương đương không tuyên bố token tiết kiệm. Agent review/KOS là tham khảo, không human gold; nếu đánh giá chỉ dựa model thì kết luận giữ ở mức pilot model-reviewed.

Audit sample bao gồm scope đã có AU, scope không AU và báo riêng vùng chưa đọc; không gọi omission của sample là recall toàncase. Test một scope có hai point nhưng chỉ soạn một phải để lộ residual khi đã biết còn việc; `has_au` không tự chứng nhận point còn lại đã xử lý. Agent tự báo hết vẫn cần source review độc lập trong đánh giá.

Control là workload chẩn đoán riêng, khóa cap tối đa12POST/30000token trước chạy;9 biến thể là bộ kiểm tra, không cho phép retry vượt cap để chạy đủ. Authoring+validate là workload tiếp theo với cap12POST/30000token riêng, chưa được cho thực thi trong đợt cập nhật tài liệu. Báo cả tổng xuyên hai workload khi so cost nghiên cứu; không giấu controls hoặc mở run mới chỉ để vượt giới hạn một workload. Đây không phải9request phụ cho mỗi case production.

## 9. Điều kiện triển khai

Giữ nguyên K0 v1 và diagnostic đã chạy làm baseline. Prompt/wire/grammar mới dùng version và workload mới, không resume checkpoint cũ bằng code mới, không sửa record cũ thành có lý do/no-AU đã kiểm. Baseline `assessed=true` không tự migrate thành negative đã xác minh.

Chốt thứ tự: control với ví dụ đầy đủ → kiểm âm/bất định → authoring mới → đánh giá validate0AU → held-out → quyết định K1. Chưa thêm mô hình, training, metadata workers, global graph hoặc tầng retrieval. Mọi lợi ích chất lượng và token trong bản thiết kế này vẫn là giả thuyết cần đo.

## 10. Checkpoint triển khai ngày2026-10-24

Đã triển khai controls và transport riêng,34test local và nativeCPU PASS; đã chạy10POST trong cap. Positive-only tạo được AU giữ ngoại lệ; contract cuối2/3positive có substance đúng,3/3negative rỗng đúng,3/3uncertain nhận ra thiếu context nhưng vi phạm kết hợp assessed_scope_ids. Vì control cuốiFAIL, đã dừng trước authoring mới trên bản án/ReadAssessment store/validate0AU/K1. Chi tiết và cost: [40_kos_controls_implementation.md](40_kos_controls_implementation.md). Các mục thiết kế trên chưa tự trở thành runtime production.
