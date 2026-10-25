# Bổ sung tăng dần cho chất lượng AU với chi phí thấp

## Mục tiêu và nguyên tắc

Giữ luồng TARGET-only → context khi cần của kế hoạch24. Ưu tiên sửa cách đọc trong request hiện có, chưa thêm model, schema, worker hoặc vòng LLM. Mục tiêu là giảm attribution sai và AU factual/trùng mà không bỏ holding, điều kiện, ngoại lệ hoặc legal point độc lập. Không có bước nào mặc nhiên được giữ vì đã triển khai.

Đầu vào bắt buộc:

- `24_target_context_staged_pilot.md` và README `knowledge_base/pipeline_v1/au_target_context/`.
- `outputs/staged_v2_20261014_192159/smoke/run.json` và `smoke/INSPECTION.md`: giao thức đạt nhưng quote origin, generalization, factual rationale và duplicate còn lỗi; chưa chạy stage2.
- Bộ nguồn và32 TARGET trong frozen presentation manifest của kế hoạch23; nguồn KOS chỉ tham khảo, không gold.
- Snapshot baseline: `outputs/au_incremental_20261014/baseline_prompt_snapshot.json`.

Mỗi bước đều có local gate trước remote. Local PASS chỉ chứng minh invariants và khả năng chạy, không chứng minh chất lượng. Đợt triển khai hiện tại không inference/deploy; command remote là thao tác được người vận hành chủ động chạy sau khi kiểm artifact. Chưa mở toàn corpus, đổi model hoặc reranker.

## Bước0 — Khóa đối chứng

Giữ profile `baseline_v2` với chính xác hướng dẫn v2 trước sửa. Snapshot nguyên văn, fingerprint, source và run lỗi/thành công cũ. Baseline vẫn là mặc định; các profile mới phải chọn rõ lúc prepare. Không sửa raw response v2 đã chạy.

Đối chứng cùng TARGET, source/context, kind/contract v2, grammar, cap800, model9B, temperature0, thinking=false và concurrency. Chỉ prompt stage1 thay đổi; stage2 instructions giữ nguyên. Profile và prompt hash vào identity để không reuse nhầm request/cache.

Local gate: baseline nguyên văn không đổi; source/offset/hash, contract, caps và context policy giống nhau; không gọi mạng.

## Bước1 — Attribution trong claim, không thêm field

Profile `attribution_v1`: thêm hướng dẫn ngắn và ví dụ tổng hợp để claim phân biệt lời tòa hiện tại với proposition được trích/thuật lại. Không biến fact của án được trích thành finding vụ hiện tại. Không yêu cầu tên người nói đầy đủ hoặc treatment taxonomy.

Nếu chưa rõ nguồn, dùng `needs_context=["speaker"]` cùng `unclear_attribution` đã có. Nếu proposition vẫn rõ, giữ neo rồi bổ sung context; nếu chưa có neo, unresolved/revisit như v2. Không tự tạo verifier hoặc gọi context cho mọi AU.

Local: prompt delta chỉ về attribution, clipping/IDs/grammar/schema không đổi; không dùng đoạn calibration/gold làm ví dụ mới; tối đa khoảng700 byte hướng dẫn thêm mỗi request.

Remote đầu tiên: cùng hai TARGET013009/099980 đã smoke, kiểm từng claim và evidence từ source. Chỉ xem là tín hiệu calibration; nếu giảm lỗi quote origin mà không loại holding notice thì thử32 TARGET. Nếu chưa rõ tác dụng, không promote và không ghép thêm bước2 vào kết luận bước1.

Giữ khi attribution nghiêm trọng giảm, holding/điều kiện không bị mất thêm và tổng chi phí được báo; không dùng model đồng thuận làm bằng chứng thay source. Nếu không cải thiện, bỏ/rewrite bước1 trước khi thêm thành phần.

## Bước2 — Legal point cùng rationale trong một AU

Profile `legal_point_v1`: giữ nguyên bước1, chỉ thêm hướng dẫn và ví dụ ngắn về đơn vị AU. Một holding/rule/application đi cùng factual rationale, qualification và nhiều evidence refs; không biến mỗi factual premise thành holding. Tách khi có proposition pháp lý thực sự độc lập. Ba AU là cap, không phải chỉ tiêu; không ép mọi TARGET chỉ có một AU.

Không tạo rationale graph/record mới, không thêm field hoặc tự động gộp claim bằng similarity. Không bỏ exception, adverse proposition hoặc rule độc lập vì muốn giảm số AU.

Local: xác nhận profile là bước1 + delta grouping; mỗi AU vẫn có primary evidence và claim không bị host rewrite. Delta grouping tối đa khoảng700 byte. Source và mọi giới hạn giống bước1.

Remote: so bước1 với bước2 trên cùng inputs/model. Kiểm099980 có holding với rationale đầy đủ thay vì các fact-only AU, và013009 không mất rule độc lập/qualifier. Sau smoke, mở32 TARGET khi có bằng chứng đủ; không suy chất lượng từ số AU giảm.

Giữ khi duplicate/fact-only AU giảm mà omission, qualification và attribution không xấu thêm; chi phí tuyệt đối gồm request context/retry phải được báo. Nếu giảm token do mất legal point thì bỏ.

## Bước3 — Chỉ bổ sung cue host khi hai bước trên chưa đủ

Chưa triển khai hoặc promote trong đợt này. Trigger: model vẫn bỏ qua reporting cue/quotation hoặc không báo speaker uncertainty sau bước1/2 trên source đủ thông tin.

Khi trigger xảy ra, thử duy nhất cue literal local trong packet hiện có: reporting phrase/quotation delimiter có offset, confidence unknown, không suy speaker/endorsement/treatment. Giữ thứ tự nguồn; không đồng thời đổi TARGET hoặc grouping. Đây là đối chứng riêng vì P1 của kế hoạch23 từng giảm ownership nhưng làm attribution/omission xấu hơn.

Không gọi NER, semantic graph hoặc verifier toàn corpus mặc định. Host cue không tự chứng minh AU sai và không hard-filter candidate. Giữ raw source truy cập được. Chỉ làm bước3 nếu tăng metadata có lợi đo được trên cùng workload; otherwise giữ kiến trúc đơn giản hơn.

## Khi các bước nhẹ vẫn không đạt

Không tiếp tục chồng thành phần để bảo vệ thiết kế. Phân loại nguyên nhân input/TARGET, contract eligibility hoặc khả năng model; phép thử đổi model trên cùng packet/contract là đợt riêng. Không tự mở repair LLM cho toàn bộ AU. Revisit queue giữ rõ pending, chưa accepted, không tự dispatch.

## Kiểm thử, metric và bàn giao mỗi bước

- Local: provenance, exact source/context, finite reason theo decision, schema/caps, code/config/profile invalidation, cache/resume không POST lại, C4/accounting và lỗi cục bộ. Profile không được thay semantics của validator để chiều model.
- Ngữ nghĩa: per-AU primary support, current versus reported origin, qualification, fact-only AU, duplicate và omission. Đánh giá toàn TARGET kể cả negative/unresolved, không chỉ AU sinh ra. Reference calibration là source review/model-assisted, không human gold; giữ disputed.
- Coverage: không loại marker, đoạn không citation hoặc AU không có abstract rule; không gộp hai legal point/ngoại lệ độc lập. Mở context khi cần là chi phí thật, không failure tự thân.
- Hiệu quả: input/output/provider tokens, source/context gửi lặp, request kể cả retry/run lỗi, latency/inference và unknown usage. Chuẩn bị host 0 LLM token; mock không dự báo token/chất lượng model.
- Hai TARGET chỉ smoke.32 TARGET dùng đánh giá calibration; muốn kết luận tổng quát phải có tập mới khóa trước. Không có hiệu quả30% hoặc đủ rẻ cho toàn corpus trước khi đo.
- Bàn giao: prompt profile/fingerprint, workload và CLI, local test/report, raw receipts+ledger, review từ source và quyết định giữ/bỏ. Nếu thiếu remote evidence, ghi live/semantic pending; không coi local PASS là mở khóa bước sau.

## Phạm vi triển khai hiện tại

Triển khai profile baseline/bước1/bước2 để có thể so sánh từng thay đổi; không đổi default và không promote profile mới. Kiểm thử local từng profile trên cùng32 TARGET. Bước3 và đánh giá model khác còn phụ thuộc trigger từ ngữ nghĩa remote, chưa triển khai.

## Nghiệm thu local — 2026-10-14

- Đã có `prompts.py` và CLI `prepare --prompt-profile baseline_v2|attribution_v1|legal_point_v1`. Profile/hash khóa lúc prepare; không runtime override. Stage2 instructions giống nhau; wire contract vẫn v2.
- Baseline ba instruction strings khớp snapshot nguyên văn. Byte thêm mỗi TARGET, tính cả newline: attribution529; grouping thêm499. Đây là byte, không provider token.
- Tester độc lập:35 test hồi quy +9 test profile = **44 PASS**. Report `knowledge_base/pipeline_v1/outputs/au_incremental_profiles_test_report.md`.
- Main đã chạy prepare/preflight/mock riêng từng profile trên32 TARGET:39/39 job verified/profile, C4, provider POST0. `local_final_v1/local_steps.json` lưu summary; đây là fixture tổng hợp, không chứng minh benefit về chất lượng hoặc chi phí.
- `local_final_v1/resume_and_source_checks.json`: source catalogs giữa profile giống nhau, mỗi profile resume0 GET/POST và ledger không đổi.
- Script local: `outputs/au_incremental_20261014/run_local_steps.ps1` (không có execute/deploy).
- Live/semantic gate của bước1/2 còn pending. Bước tiếp theo chỉ smoke baseline versus attribution trên hai TARGET; review từ source trước khi promote hoặc chạy grouping/full32. Không dùng local PASS để chốt phương án cuối.

## Gate context phát hiện khi chạy thật — 2026-10-14

Run `incremental_step1_20261014_213712/baseline_v2/smoke` có hai stage1 verified và một stage2 invalid. JSON đầy đủ, finish_reason=stop, reason codes hợp lệ; stage2 trả bốn supplement cùng slot scope nên host từ chối. Đây là lần context thật đầu tiên chạm duplicate-slot gate; không phải timeout hoặc output bị cắt. Chi phí run lỗi vẫn giữ5855 provider token/3 POST.

Sửa gate chung trước khi tiếp tục so profile:

- Grammar dùng16 tập con có thứ tự của condition/exception/speaker/scope; mỗi slot tối đa một lần, có thể rỗng. Nhiều context refs dùng cùng một supplement; không bắt điền đủ bốn slot. Validator không nới và không tự dedup output cũ.
- Hướng dẫn stage2 chung cho mọi profile phân biệt scope (phạm vi áp dụng) với fact, ngày sự kiện, rationale hoặc ghi chú chung. Text mới phải có support từ context refs; lời đương sự không tự chứng minh kết luận tòa hoặc một yêu cầu pháp lý bắt buộc.
- Nếu thông tin cần thiết không được hỗ trợ, giữ unresolved; không tự invent supplement. Nếu không cần bổ sung thì giữ [] và claim chính bất biến.
- Stage1 baseline và các delta attribution/grouping không đổi. Snapshot stage2 cũ giữ nguyên như lịch sử; phần hướng dẫn sửa stage2 được thêm chung, không quy tác dụng của gate này cho attribution profile.
- Wire contract vẫn v2 vì unique slots đã là yêu cầu validator. Grammar/prompt/code hash mới cần prepare/root mới; không dùng receipt invalid cũ làm kết quả mới, không migrate hoặc chạy lại paid inference trong đợt sửa code.
- Local kiểm tất cả16 subset, negative duplicate slots, nhiều refs trong một slot, empty context, giữ primary và hồi quy profile/cache; grammar trên endpoint và chất lượng scope vẫn cần smoke mới.
- Nghiệm thu gate: **52 test PASS**; Main mock32 TARGET riêng từng profile39/39 verified, C4, provider POST0. Main replay response stage2 lỗi thực bằng validator hiện tại vẫn từ chối `foreign/duplicate slot`; không sửa raw receipt. Artifact tại `outputs/au_scope_gate_20261014/`.
- Hướng dẫn stage2 thêm1761 UTF-8 byte tính cả newline chỉ khi chạy lượt context; stage1 instructions không tăng. Byte không phải token thực và không chứng minh tiết kiệm. Chưa inference mới, chưa compile XGrammar local.
