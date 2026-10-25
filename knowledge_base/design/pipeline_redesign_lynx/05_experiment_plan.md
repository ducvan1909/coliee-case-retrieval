# Kế hoạch đánh giá hướng agent authoring gần KOS

Ngày cập nhật:2026-10-24. Kế hoạch mới thay thứ tự thí nghiệm chính P2; kết quả P2/Plan11 giữ nguyên ở history_before_kos_direction_20261021/05_experiment_plan.md và artifact gốc. K0 đã chạy nhưng0AU; bổ sung dưới đây là thiết kế thí nghiệm, chưa cho chạy thêm inference hoặc mở corpus. [Chi tiết cải tiến39](39_kos_authoring_improved.md).

## 1. Câu hỏi

Agent làm nhiệm vụ theo case và đóng gói theo legal point có tốt hơn extraction theo TARGET cố định không? Khi đã có authoring baseline, đọc chủ động có giữ chất lượng với tổng chi phí thấp hơn không? Không quy lợi ích cho NER/cue hoặc đổi model khi chưa có ablation.

## 2. Khóa tập và chống leakage

- K0: đúng16 source scopes thuộc3case của A,18 KOS references chỉ dùng để đối chiếu sau generation; nguồn đã calibration/tuning nên không phải held-out.
- K1: sau K0 mới xét toàn source5án013009/013948/011904/045155/099980. Universe là source thật, không tập TARGET chọn từ KOS.
- Sau calibration cần case-held-out trước khi suy rộng; có thể tái dùng thiết kế20development/40held-out đã đề xuất, phải khóa và loại near-duplicate trước tuning. Chưa chạy đợt đó.
- Không dùng KOS Claim/Issue/gold family, gold_noticed hoặc citation chưa che cho navigation/authoring/prompt examples.
- Agent review không human gold. Không cần người annotation trong đợt hiện tại, nhưng phải báo giới hạn này và không gọi agreement là correctness đã chứng minh.

## 3. K0 — Thử riêng authoring, chưa thử selective corpus reading

| Arm | Nguồn được phép đọc | Đơn vị công việc |
|---|---|---|
| A lịch sử, soft acceptance | Union nguồn16TARGET A stage1 đã thấy | Request theo TARGET; tối đa3AU/response cũ |
| K0 authoring | Chính union đó, giữ source order và gaps rõ | CaseWork; soạn legal point, nhiều block/response nếu cần |

Đây là đối chứng kiến trúc làm việc, không phải một biến cue; model và output wire substance giữ tương đương, cần báo renderer/authoring prompt khác nhau rõ. Không khẳng định nguyên nhân chỉ do grouping nếu thay nhiều điều kiện.

Qwen/Qwen3.5-9B hiện tại, thinking false, cùng giới hạn input6000/output800. Không đổi endpoint/model tự động. Không có NER/cue metadata hoặc planner request riêng. Mọi tool/continuation/retry/probe tính vào cap12request và tổng reservation/usage30000token. Preflight tính toàn serialized payload bằng tokenizer đúng khi có; estimate phải ghi rõ, không gọi local estimate là usage provider. Chưa preflight/khóa manifest thì chưa dispatch.

Union exact source exposure không đổi, nhưng thứ tự và số lần đọc có thể đổi, phải báo cả hai. Union phải trích từ source catalog/payload A đã thực sự gửi, không từ context_refs chỉ có sẵn trong workload: A chưa gửi context [15] của045155 và chưa có stage2. Case group vượt input cap chia thành ReadScope bounded, không cắt mất nguồn hoặc gom thành prompt quá cap. Evidence ngoài union không được mở trong K0; thiếu premise giữ unresolved. Continuation giữ draft đã commit, không lặp generation toàn collection. Workload K0 có thể hoàn tất trong khi các case vẫn partial vì phần ngoài union chưa assessed; báo hai trạng thái riêng.

18KOSrefs không phải đủ để chấm omission. Kiểm cả SOURCE có operative exception 045155[10] và finding noncompliance[21], dù KOS có thể không giữ chúng.

## 3b. Cải tiến KOS sau K0 rỗng — thứ tự bắt buộc

Giữ K0 v1 làm baseline, không sửa source/checkpoint cũ. Hướng39 có ba thay đổi nối tiếp, không đưa tất cả vào một run rồi quy nguyên nhân:

| Bước | Biến thay đổi | Đối chứng và cổng |
|---|---|---|
| Contract control | Một ví dụ JSON dương đầy đủ, khác source kiểm tra | Cùng model/grammar/caps; có AU hợp wire và đúng rule/exception mới đi tiếp |
| Control cân bằng | Ví dụ âm/bất định so với chỉ ví dụ dương | Ba nhóm dương/âm/bất định, mỗi nhóm3 biến thể; bao phủ multi-point, no-marker, exception, fact-only, party-only, citation-only và missing context; giữ biến thể ngoài prompt |
| Authoring mới | Cách soạn KOS và lý do rỗng gọn theo39 | Cùng union K0, ghi rõ prompt/wire thay đổi; không attribution causal cho riêng few-shot |
| Validate0AU | R0 receipt authoring khóa → R1 thêm tối đa1validate/case | Được giữ rỗng; tổng cap12POST/30000token, không tạo lượt mới qua resume; gain phải là point được nguồn hỗ trợ |

Positive control chỉ đạt khi đúng substance/evidence/exception, không chỉ AU_count>0. Negative control phải cho phép rỗng; uncertain không bị ép no-AU. Nếu control fail thì dừng, không chạy cảcase rồi dùng review để cứu. Grammar JSON tổng quát là phép thử riêng nếu cần, không tự đổi production.

Sau thêm `empty_reason` hoặc đổi wire/grammar phải replay native và chạy lại controls dương/âm/bất định/multi-AU trên contract cuối. Không coi PASS ở contract cũ là giấy phép cho bản mới. Test mixed scopes facts/thiếu treatment, navigation-only, có AU nhưng còn point chưa soạn, court rejection có test riêng và reported authority chưa adopt; không gán no-AU đồng loạt cho các scope khác kết quả.

Workload control và authoring+validate khóa riêng cap12POST/30000token trước thực thi; tính cả retry/probe trong từng cap và báo tổng xuyên workload khi so chi phí nghiên cứu. Chưa cho chạy hai workload này trong lần cập nhật tài liệu. Không tự tạo run mới để vượt cap hoặc biến controls thành chi phí lặp cho mỗi case production.

Audit omission phải lấy mẫu cả scope có AU và không AU, đồng thời báo unread; chỉ xem no-AU không đủ đo recall. CaseWork0AU chỉ trigger kiểm tra đúng union đã đọc, không mở toàncase. Không quota theo block/case, không yêu cầu số AU bằng KOS. Khi validate không được gọi vì không có trigger, lợi ích nhánh này là chưa đo, không coi no-op là thắng.

Báo riêng AU support rate, false positive trên mẫu âm, bỏ legal point, fragmentation, actor/attribution/qualification và residual. Tính toàn bộ ví dụ prompt, authoring, validate, nguồn lặp, warmup/probe/retry, run lỗi và model-review. Chất lượng không tương đương thì không so token để tuyên bố tiết kiệm. Sample agent-review không human gold và không suy recall toàncase từ sample.

## 4. K1 — Thử đọc chủ động trên toàn nguồn calibration

**Chặn hiện tại:** chưa mở K1 vì K0 và positive control chưa đạt. Trước K1 thực hiện thứ tự ở mục3b dưới đây và39.

Chỉ lập manifest sau K0 quality gate. Agent được open/search raw source cùng case, không planner toàn cục hoặc host semantic shortlist. Initial scope/navigation/cap và stop policy phải khóa trước khi xem output/KOS; ngân sách dựa preflight độ dài và chi phí K0, không đổi sau kết quả để gọi thắng.

So K1 với no-planner exhaustive reading baseline có cùng source universe/model/AU acceptance. Budget curves tính theo cùng mức token tuyệt đối. Phần chưa đọc báo not_assessed, run partial; không chứng minh no-AU. Audit vùng không citation, application/exception, giữa section, án dài ít AU; không chỉ mở lại các vùng đã biết từ KOS.

K1 mở thêm nguồn so K0 thì tách gain nhờ evidence mới với gain authoring. Không dùng K0 để kết luận selection toàn case hiệu quả.

## 5. Tình huống kiểm thử

- Hash/offset/quote, parser không mất ký tự; thiếu heading/marker vẫn mở được nguồn.
- Một AU rule–rationale–exception chạy qua nhiều block; đọc nó từ context cũ vẫn có owner/evidence đúng.
- Hai legal points độc lập không bị gộp chỉ vì cùng topic; claim không bị buộc giống nguyên văn.
- 045155[21]: applicant không đổi thành decision-maker; giữ scope27(3) và finding noncompliance.
- 045155[9]: giữ MacKay/reporting voice và particular-facts qualification; party assertion không thành holding.
- 045155[10]: không dùng hết slot cho policy slogan rồi bỏ operative exception.
- 011904[16]: no-danger rule, ví dụ prior police case và exception không đổi người gây nguy hiểm.
- Long output fields chỉ warning; output truncation/incomplete vẫn partial, không tự cắt hoặc gọi shortening.
- Source chưa mở không làm evidence; preview không được cite; reference của cited case không resolve thành paragraph local.
- Dừng sau lượt đầu, hết cap, invalid tool ID, đọc lặp, provider unknown, crash sau receipt và resume; không fallback exhaustive hoặc retry vô hạn.
- Source/map/policy đổi invalidation đúng; Issue đổi không làm mất AU độc lập.

## 6. Metrics

### Chất lượng AU

Đúng actor, attribution, polarity/modal, qualification/exception và scope; legal point self-contained; omission của operative holding; fragmentation/duplicate; kind confusion. Đánh giá rule/application/rationale riêng, không buộc count bằng KOS. Báo per-target/per-case cùng nguồn và AU chỉ xuất hiện nhờ thêm context.

Grounded draft khác reviewed_supported. Một full-source pass của model không bảo đảm semantic recall. Không báo precision/recall gold nếu chỉ có review agent hoặc KOS overlaps.

### Phạm vi đọc

Source inventory, delivered spans, assessed spans và residual/unknown; unique/rendered/repeated chars; source mở bằng search vs adjacency; expansion và navigation turns. Agent self-report assessed chỉ là log, phải kiểm omission độc lập trên sample.

### Chi phí và vận hành

Input/output/reasoning usage provider; request model kể cả navigation/continuation, tool HTTP riêng, retry/error; full serialized payload và local CPU/storage. Cold-start, warmup/probe và cache/resume tách riêng. Số token ước lượng không đổi thành usage thực; không bỏ phần thất bại hoặc outcome unknown.

A stage1:19672token; v2 stage1:19366; v2context1497. Shortening A thất bại3291 được báo riêng trong historical branch22963. Không gọi A rẻ hơn v2 bằng cách bỏ context pending, không coi chi phí sunk của sửa lỗi là baseline bắt buộc của mọi run tương lai.

## 7. Cổng quyết định

1. Local/source/tool/state PASS mới đủ điều kiện chuẩn bị live; không chứng minh AU quality.
2. K0 phải không còn lỗi actor/attribution nghiêm trọng trong ca đã phân xử và không mất thêm operative points so baseline. Nếu chưa đạt, giữ failure set; không thêm enrichment hoặc planner để che.
3. Chất lượng tương đương mới tuyên bố tiết kiệm. K0 tốt nhưng tốn hơn thì báo tradeoff, chưa gọi tối ưu toàn corpus.
4. K1 cần báo phần chưa đọc và omission dưới ngân sách; nhiều positive hoặc marker coverage không đủ chứng minh recall.
5. Review độc lập, disagreement và limits lưu riêng; trước corpus expansion cần held-out có đủ power. Không dùng agent consensus thay gold.
6. K2 cải tiến cache/transport/model/worker từng biến; không mặc định30% savings, không chạy toàn corpus trước gate.

## 8. Trình tự triển khai

(1) CaseWork/ReadLedger và tool adapter local; (2) authoring renderer/contract và mock; (3) manifest/preflight K0; (4) live khi được cho chạy; (5) review equal-exposure và cost; (6) thiết kế/khóa K1full5case; (7) held-out và dự toán toàn corpus. Không quay lại sửa source/atom hay thêm NER trước bước1.
