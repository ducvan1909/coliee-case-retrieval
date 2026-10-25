Khuyến nghị của tôi: **host-selection là đối chứng tối thiểu; planner 9B một lượt/án là arm tùy chọn hợp lý; chưa chọn full interactive loop làm mặc định**. Batch planning có thể giảm overhead, nhưng chưa có evidence rằng 9B chọn vùng đủ tốt hoặc phần source tiết kiệm bù được planner.

Đã đọc AGENTS.md và các đầu vào bắt buộc; chỉ đọc, không sửa file, chạy inference hay deploy. Contract repair thực tế nằm tại `pipeline_v1/contracts/repair_selection_wire.v1.json`, không nằm trong thư mục `repair_agent/contracts`.

**Baseline và phép tính chi phí**

Workload hiện tại là **30 target, sáu target mỗi án trong năm án**, không phải exhaustive baseline của 30 án. Bulk dùng 64.347 input + 5.914 output = **70.261 token**; workload wall 186,625 giây, setup 189,562 giây. Corpus dùng **70.496 token**, workload wall 189,5 giây; báo cáo không xác nhận speedup hoặc chất lượng ngữ nghĩa. [Manifest](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/manifest.json:14), [BULK_REVIEW](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/BULK_REVIEW.json:8), [CORPUS_REVIEW](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/CORPUS_REVIEW.json:145).

Với một workload so sánh **thực sự tương ứng**, đặt:

\[
T_{\text{selective}}
= T_{\text{navigation}}+T_{\text{extraction}}+T_{\text{context}}
+T_{\text{repair}}+T_{\text{resume}}+T_{\text{failed attempts}}
\]

Mọi thành phần gồm input/output và prompt/catalog lặp. Arm chỉ đạt mức ngân sách \(b\) nếu \(T_{\text{selective}}\le bT_{\text{baseline}}\). Áp dụng số học vào 70.261 token cho các trần 25/50/75% cho ra **17.565 / 35.131 / 52.696 token**, nhưng đây chỉ là trần của workload 30 target; không phải dự toán selective extraction toàn án.

**Tám phản biện trọng yếu**

1. **P1 — Thiếu bằng chứng: giảm source đọc chưa chứng minh giảm TOTAL token.**  
   **Claim → evidence:** Loop tạo thêm lượt overview/planning/paging/next-action. Ngay repair giới hạn hai lượt đã có trường hợp từng request vừa cap nhưng tổng arm vượt cap; [README repair:299–302](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:299).  
   **Impact:** Có thể đọc ít hơn nhưng tốn token hơn; budget hết trước discovery/context cần thiết.  
   **Change:** Khóa riêng trần navigation, extraction, discovery, context và phục hồi; admission tính payload đầy đủ trước dispatch. Gộp assessment và next-action giúp giảm lượt, nhưng không xóa input của lượt tiếp theo.  
   **Test decision:** So host-selection, planner một lượt/án và interactive trên cùng nguồn/caps. Giữ planner chỉ khi lợi ích selection bù **toàn bộ** overhead, thay vì chỉ báo số source token bỏ qua.

2. **P1 — Defect hợp đồng còn thiếu: pagination và search chưa có giới hạn tổng chi phí.**  
   **Counterexample:** Án dài thiếu heading; AU nằm giữa block, ngoài first/last/salient previews. Planner có thể duyệt hết các trang hoặc lặp `find_source` bằng biến thể câu hỏi. Không có upfront all-block previews vẫn có thể trở thành all-block previews trả dần. Spec hiện chỉ quy định tool trả identity/span/version, chưa có hợp đồng pagination mới. [Spec04:246–265](/G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:246).  
   **Impact:** Navigation tăng theo độ dài án; preview bias làm bỏ vùng quan trọng.  
   **Change:** Cursor gắn snapshot/hash/order/filter; cap bytes/token mỗi trang, tổng trang và search calls; báo truncation rõ. Host dành discovery cho vùng ngoài trang đã xem, không phụ thuộc planner yêu cầu.  
   **Test decision:** Fixture AU giữa block, không citation, không heading; search nhiều kết quả và trang sát cap. Kiểm tra thứ tự/cursor ổn định, không đánh dấu preview là read, và discovery còn ngân sách sau navigation.

3. **P1 — Defect thiết kế nếu tái dùng nguyên repair wire/catalog cho extraction và planning.**  
   **Evidence:** Wire repair yêu cầu quyết định cho **proposal đã tồn tại**, mỗi lượt đúng một tool call; không phải contract phát hiện AU mới. Catalog có cap 128, bỏ intersection mơ hồ; expansion đổi read-view và invalidates IDs cũ. [Wire](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/contracts/repair_selection_wire.v1.json:14), [README:11–34](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:11), [README:258–274](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:258).  
   **Impact:** Expansion trước submit có thể làm evidence ID trước đó hết hiệu lực; catalog thiếu evidence có thể bị hiểu sai thành không có AU.  
   **Change:** Reuse cơ chế finite selection/validate-first, không reuse nguyên ngữ nghĩa repair. Tách navigation ID, immutable span identity và request-scoped evidence ID. Assessment bind đúng catalog snapshot; planner chỉ chọn region, host dựng TARGET rồi dùng AU extraction wire hiện có.  
   **Test decision:** Read → expand → submit bằng ID cũ; câu lặp; catalog overflow; CONTEXT được chọn thành TARGET mới. Phải reject stale ID hoặc resolve qua snapshot đã khóa, không tự remap hay no-AU.

4. **P1 — Defect hợp đồng còn thiếu: checkpoint assessment chưa đủ cho commit và next-action.**  
   **Counterexample:** Assessment đã lưu nhưng crash trước cập nhật coverage/obligation; hoặc next-action đã dispatch nhưng mất ACK trước checkpoint. Resume có thể đếm chi phí hai lần, tạo AU trùng hoặc dispatch lại. Code hiện có lưu receipt trước cursor; unknown outcome chặn admission. [Bulk core:188–204](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/bulk_execution/core.py:188).  
   **Impact:** Mất durability hoặc phát sinh inference lặp khi xử lý hàng nghìn án.  
   **Change:** Commit assessment, AU proposal, interval assessment, obligations và budget delta trong một transaction/log sequence; next-action là intent riêng chỉ chạy sau commit. Request identity gồm source/map/render/tool/schema/model/settings, TARGET/CONTEXT, catalog và state snapshot thực sự dùng.  
   **Test decision:** Fault injection ở reservation→dispatch→receipt→assessment commit→next intent. Replay phải cho cùng trạng thái, không tạo AU trùng; unknown không tự redispatch. Test hiện kiểm tra write-order và scripted recovery, chưa chứng minh transaction của loop mới. [Tests:227–237](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/tests/test_bulk_execution.py:227), [Tests:421–456](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/tests/test_bulk_execution.py:421).

5. **P1 — Thiếu bằng chứng và thiếu gate: 9B extraction không chứng minh planner tốt; host-valid không đủ publish AU.**  
   **Evidence:** Cùng workload bulk/corpus vẫn đổi một decision và ba AU counts; cả báo cáo giữ `semantic_quality_claim:false`. Repair host-valid cũng giữ `semantic_review_pending`, không tự ghi accepted store. [CORPUS_REVIEW:2–8](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/CORPUS_REVIEW.json:2), [README repair:3–7](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:3).  
   **Impact:** Planner có thể bỏ nguồn; reader có thể hiểu sai attribution/exception dù ID, hash, offset đúng. “Validated AU” dễ bị diễn giải thành structural PASS rồi đưa vào citation candidates.  
   **Change:** Không thêm verifier mặc định là hợp lý, nhưng phải định nghĩa publish gate rõ: structural validity, model semantic assessment và accepted status là các trường khác nhau. Raw block/candidate/unresolved không vào citation view.  
   **Test decision:** Challenge tool hợp lệ nhưng lựa chọn sai, condition ngoài TARGET, party submission giống holding, repeated invalid action. Đo invalid-action rate, request sửa lỗi và semantic disagreements riêng. Các probe grammar/mock hiện không chứng minh planner hay entailment. [README:291–297](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:291).

6. **P1 — Defect biểu diễn: bốn semantic states ở cấp block chưa biểu diễn đầy đủ assessment một phần.**  
   **Counterexample:** Block được đọc 20% dưới CONTEXT; chỉ 10% được đánh giá làm TARGET và không có AU. Gán cả block `assessed_without_AU` là sai; gán `not_assessed` lại mất thông tin tiến độ. Spec hiện phân biệt primary coverage với context overlap. [Spec04:111–127](/G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:111).  
   **Impact:** Stop/discovery/resume có thể bỏ phần chưa xét hoặc đọc lại phần đã xét.  
   **Change:** Canonical ledger lưu interval TARGET đã assessment, interval supplied/read dưới CONTEXT, preview exposure và obligations; block status chỉ là projection có thêm partial/mixed. Context promotion tạo TARGET assignment mới, không tự tạo no-AU hay sửa owner cũ.  
   **Test decision:** Partial overlap, đảo thứ tự assessment, promote CONTEXT, retry slice. Union coverage phải đúng, không đếm overlap hai lần; partial negative không trở thành full-block negative.

7. **P2 — Giả thuyết chưa đo: interactive scheduling có thể giảm utilization và tăng cold-start cost.**  
   **Evidence:** Corpus có mean active claims 3,34 so bulk 2,68 nhưng wall vẫn cao hơn; active claims không phải GPU utilization. Setup gần bằng workload wall; GPU/billing và component timing chưa đo. Client ngắt lâu có thể scale down, job đang chạy thành unknown. [Diagnosis](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/PERFORMANCE_DIAGNOSIS.json:26), [Bulk README:41](/G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/bulk_execution/README.md:41).  
   **Impact:** Chuỗi phụ thuộc trong từng án để GPU chờ planner; án dài hoặc obligation chain chiếm hàng đợi.  
   **Change:** Host dispatch vùng độc lập qua bounded queue, fair scheduling giữa án, giới hạn in-flight/án; duy trì case state bền vững độc lập container. Wide/full-read là workload có cap và approval scope rõ.  
   **Test decision:** Workload trộn án ngắn/dài, planner chậm, client ngắt, container restart. Đo queue wait và end-to-end setup+workload; không suy billing hoặc speedup từ token/cache hit.

8. **P1 — Thiếu bằng chứng: baseline/model_silver không đủ nghiệm thu selective completeness.**  
   **Evidence:** Spec04 hiện yêu cầu mọi content nằm trong primary target; selective proposal đổi invariant đó. KOS v1 đã superseded và gold-family biased; log ghi curated/agent-crafted, không cung cấp raw usage/reading trace để tính token hoặc source coverage. [Spec04:22](/G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:22), [KOS strategy:71–81](/G:/Legal-AI/kos_sample/_meta/extract_strategy.md:71), [Log 000002:24–28](/G:/Legal-AI/kos_sample/_meta/extract_log_000002_family_20260826.md:24), [Log 000031:40–46](/G:/Legal-AI/kos_sample/_meta/extract_log_000031_family_20260827.md:40), [SCHEMA:13–14](/G:/Legal-AI/kos_sample/SCHEMA.md:13).  
   **Impact:** Giảm token bằng bỏ AU có thể được báo nhầm là tối ưu thành công.  
   **Change:** Giữ `selective_pass_complete` riêng với complete source assessment và AU completeness; quota discovery chỉ chứng minh đã thực hiện policy. Exhaustive output là reference không phải gold.  
   **Test decision:** Đối chiếu theo evidence/proposition/attribution, không chỉ AU count; kiểm tra vùng unread được discovery bổ sung. Khi tiếp tục bỏ human annotation, chỉ kết luận operational feasibility và agreement/missed-reference signals; chưa kết luận AU recall hay quality equivalence.

**Thiết kế tối thiểu sửa lại, gồm câu hỏi tích hợp của Main**

| Arm | Điều phối | Giá trị đối chứng |
|---|---|---|
| H | Host xếp vùng từ cues, obligations và discovery | Ít overhead model nhất |
| P | Planner 9B một lượt/án chọn bounded region IDs; host dispatch bằng AU wire hiện có | Đo giá trị selection của planner |
| I | Full interactive navigation/read/submit loop | Chỉ giữ nếu lợi ích vượt overhead và lỗi bổ sung |

Tôi khuyến nghị **H trước, P là tùy chọn, I là arm nghiên cứu**. Với P, planner nhận overview cấu trúc và một shortlist bounded do host chuẩn bị; trả region IDs, reason enum và câu hỏi ngắn. Phải ghi rõ planner chỉ chọn trong shortlist đã thấy, không tuyên bố đã cân nhắc toàn án. Không yêu cầu kind/Issue cho tất cả block.

Host thêm discovery reserve độc lập, dựng TARGET/CONTEXT từ spans thật, rồi dispatch các vùng được chọn qua extraction hiện có. Không cần planner gọi tool cho mỗi vùng. Chỉ replan sau checkpoint có trigger rõ: unresolved obligation, discovery phát hiện vùng mới đáng xét, hoặc kế hoạch đã cạn trong khi policy còn yêu cầu exploration. Mỗi replan có cap riêng; lỗi planner không retry vô hạn hoặc chuyển thành no-AU.

Assessment commit lưu proposal, evidence, ownership, interval ledger và cost receipt. Source reads không tự satisfy obligations. Stop certificate ghi budget, discovery thực hiện, vùng chưa assessment và obligations unresolved. Chỉ AU qua publish gate được đưa vào citation view; query-time extraction về sau dùng cùng gate, chưa thiết kế NN–AU join hay Issue gate.

Cache tách ba lớp: artifact local, response reuse và prefix/KV cache. Source/map/render thay phải invalidates đúng dependency; đổi queue priority không mặc nhiên làm mất AU đã đánh giá hợp lệ. Prefix cache có thể giảm compute nhưng vẫn phải tính input token đã gửi; hiện có cache counters nhưng chưa có GPU/billing evidence. [Plan14:45–53](/G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/14_speed_optimization_plan.md:45), [Spec04:267–282](/G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:267).

Điểm yếu của phương án tôi là host shortlist vẫn mang bias của cues, còn planner một lượt có thể bỏ quan hệ chỉ lộ ra sau khi đọc sâu. Discovery và replan giảm rủi ro đó nhưng chưa chứng minh đủ.

Trước implement cần chốt **interval/state contract, ID invalidation, transaction/unknown-outcome handling, publish gate và budget accounting**. Trước chọn kiến trúc để mở rộng cần đo **prompt/source/catalog decomposition, planner overhead và selection errors, replan frequency, context/repair cost, cold/warm end-to-end cost** trên workload tương ứng. Baseline 30 target hiện chỉ cung cấp tham chiếu vận hành; thiếu exhaustive whole-case comparator và semantic labels là blocker cho claim completeness, không phải lý do để tự mở inference hoặc human annotation.


