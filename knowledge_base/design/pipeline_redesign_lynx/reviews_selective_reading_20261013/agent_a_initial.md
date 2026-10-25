**Thiết kế chọn đọc theo vùng đáng thử, nhưng chưa đủ căn cứ để coi là cách xây KB AU có coverage tương đương exhaustive.** Không cần LLM đọc toàn án chỉ để lựa chọn; đổi lại, phải chấp nhận và đo rủi ro bỏ sót. Discovery budget giảm điểm mù, không loại bỏ nó.

Đã đọc AGENTS.md và các đầu vào bắt buộc. Contract repair nằm thực tế tại `pipeline_v1/contracts/repair_selection_wire.v1.json`. Chỉ đọc source, tài liệu, báo cáo và test; không sửa file, chạy test, inference hay deploy.

Dưới đây là tám điểm trọng yếu. “Thiếu hợp đồng” là vấn đề thiết kế; các phản ví dụ tổng hợp chưa chứng minh lỗi runtime mới.

1. **P1 — Điều hướng bằng preview có điểm mù không thể giải quyết bằng “salient” đơn thuần.**

   **Claim:** first/last/salient previews giúp lựa chọn, nhưng không chứng minh agent sẽ thấy AU quan trọng trong vùng tín hiệu thấp. Việc tránh hard filter là cần thiết, chưa đủ.

   **Evidence/phản ví dụ:** trong source `000031`, đoạn [59] có một proposition kèm điều kiện về public-interest costs, không có citation/marker trong chính đoạn: [000031.txt:274](G:/Git/coliee-case-retrieval/data/task1_train_files_2026/cases/000031.txt:274). Nó xuất hiện khá muộn. Đây là ví dụ citation-free thật, không phải gold AU đã phân xử.

   Phản ví dụ **tổng hợp thiếu heading**: hai án có cùng metadata, độ dài, cues và ba preview của một block; câu giữa không được preview là “An extension is available only where the delay was beyond the applicant’s control.” Một án chứa câu đó, án kia chứa background. Agent nhận cùng thông tin điều hướng nên không thể chắc chắn chọn khác nhau. Không được khắc phục bằng heading giả hoặc summary toàn án.

   **Impact:** dễ ưu tiên vùng “trông giống doctrine”, bỏ qua proposition nằm giữa block dài hoặc section không có heading.

   **Change:** phân trang theo ordinal; cho nhảy đến vị trí đầu/giữa/cuối; discovery lấy mẫu cả **trong block dài**, không chỉ chọn block. Mỗi preview có source ref và thuật toán/version chọn câu; `real_heading_ref` được phép null.

   **Test quyết định:** dùng cặp tổng hợp trên, hoán đổi vị trí câu quan trọng giữa các ordinal và vị trí trong block. Đo tỷ lệ vùng đó được đọc dưới cùng budget; nếu giảm mạnh khi bỏ heading/cue, navigation chưa đạt yêu cầu chống điểm mù.

2. **P1 — Expansion theo lân cận chưa đủ cho speaker, treatment và qualification phân tán.**

   **Claim:** bounded neighbors và structural relations không bảo đảm đủ ngữ cảnh pháp lý; host chỉ kiểm tra được nghĩa vụ **đã được phát hiện**.

   **Evidence:** source [000031.txt:138](G:/Git/coliee-case-retrieval/data/task1_train_files_2026/cases/000031.txt:138) đặt attribution trước quoted proposition; đoạn sau chứa exception/qualification tại dòng 144. Spec cũng thừa nhận hint không chứng minh speaker/condition và obligation chưa giải quyết không được accepted/no-AU ([spec04:117](G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:117), [155](G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:155)).

   Phản ví dụ tổng hợp: B12 “Counsel submits…”; B13–B15 trình bày quy tắc; B41 “That submission cannot be accepted”; B44 giới hạn áp dụng. Đọc B14 ±1 có thể tạo AU gán sai current court và thiếu treatment.

   **Impact:** AU có exact evidence nhưng claim rộng hơn nguồn hoặc biến lập luận đương sự thành quy tắc của tòa.

   **Change:** mỗi AU assessment phải trả trạng thái riêng cho attribution, current-court response, condition, exception và limit: `supported / uncertain / not_applicable`, với witness hoặc lý do. Cho phép `find_source` tìm antecedent/response xa rồi `read_region`; không chỉ before/after. Chưa giải quyết được thì unresolved.

   **Test quyết định:** di chuyển lead-in, phản bác và exception ra ngoài cửa sổ ban đầu. Kết quả đạt là agent mở đúng vùng hoặc giữ unresolved; accepted claim sai attribution/qualification là thất bại, dù quote/hash PASS.

3. **P1 — TARGET ownership đúng kỹ thuật vẫn có thể sai về nội dung.**

   **Claim:** chọn một evidence ID thuộc TARGET không tự chứng minh primary proposition nằm ở TARGET. Chuyển context thành target cũng không được tự chuyển trạng thái thành assessed.

   **Evidence:** test hiện có chặn primary quote nằm trong context dù evidence chứa cả target ([test_au_candidate_reviews.py:166](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/tests/test_au_candidate_reviews.py:166)). Nhưng test selection chấp nhận exact intersection `"le X"` làm địa chỉ primary hợp lệ ([test_repair_selection.py:50](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/tests/test_repair_selection.py:50)); nó chứng minh địa chỉ, không chứng minh proposition hoàn chỉnh.

   **Impact:** model có thể chọn câu dẫn TARGET để hợp thức hóa claim thực chất chỉ được phát biểu trong CONTEXT; hoặc tính context-only read thành đã đánh giá AU.

   **Change:** tách `primary_proposition_ref` khỏi supporting/context refs. Context phát hiện AU tạo một target assessment mới, có ownership và catalog mới; không sửa ownership của proposal cũ. Với proposition thực sự xuyên block, cho target region chứa các span cần thiết, giữ một owner neo và nhiều evidence refs; không ép split theo block.

   **Test quyết định:** TARGET “The applicable test is discussed below”, CONTEXT chứa toàn bộ quy tắc. Host phải chặn xuất bản AU dưới TARGET này; promote CONTEXT chỉ thành công sau assessment riêng. Thêm trường hợp proposition xuyên block để kiểm tra hệ thống không đánh mất phần điều kiện.

4. **P1 — Ledger và stop cần tách ba trục; discovery quota không phải chứng nhận coverage.**

   **Claim:** `not_assessed/assessed_with_AU/assessed_without_AU/unresolved` vẫn thiếu nếu dùng như một state duy nhất cho cả block.

   **Evidence:** spec hiện yêu cầu mọi content target có trạng thái cuối và không ghi complete khi dừng do budget/provider failure ([spec04:181](G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:181), [282](G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:282)). Selective mode chủ động để lại source chưa assessed; đây là thay đổi hợp đồng đã xác nhận, không phải lỗi triển khai mới.

   **Impact:** đọc vài câu có thể làm cả block thành negative; quota discovery đã đạt có thể che unresolved hoặc hết ngân sách.

   **Change:** giữ riêng:
   - delivery: preview / source delivered, kèm exact spans;
   - assessment: trạng thái ngữ nghĩa trên exact spans;
   - run termination: policy satisfied / budget exhausted / provider failure.

   Preview và find hit không vào evidence catalog. Source delivered không đồng nghĩa model hiểu đúng. `selective_pass_complete` chỉ khi policy đã khóa được thỏa; budget hết trước đó là partial. Dù complete selective, source còn lại vẫn `not_assessed`.

   **Test quyết định:** block mười câu, chỉ hai câu được đọc và assessed negative; tám câu còn lại phải chưa assessed. Đạt discovery quota nhưng còn mandatory obligation phải không complete. Host không được tuyên bố “không còn nghĩa vụ” theo nghĩa không còn qualification chưa phát hiện.

5. **P1 — “Validated AU” chưa có nghĩa xuất bản đủ rõ khi bỏ verifier mặc định.**

   **Claim:** dùng một reader/planner là lựa chọn hợp lý về chi phí; không được suy validate-first cùng request là xác minh ngữ nghĩa độc lập.

   **Evidence:** repair README giữ mọi revision ở `semantic_review_pending`, exact witnesses không chứng minh entailment ([README:3](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:3)). KOS cũng có artifact `kind: holding` nhưng evidence là câu hỏi framing hoặc lập luận counsel ([issues-framed:5](G:/Legal-AI/kos_sample/cases/066809/authority_units/au-066809-issues-framed.md:5), [loga-argument:23](G:/Legal-AI/kos_sample/cases/040679/authority_units/au-040679-loga-argument.md:23)). Đây là bất tương thích nhãn/evidence quan sát được, chưa phải phân xử pháp lý toàn record.

   **Impact:** AU-only gate vẫn có thể cho proposition sai vào candidate nếu “validated” chỉ là schema/source PASS.

   **Change:** tách `host_valid`, `model_assessment`, `publication_status`, `assessment_provenance`. Main phải chốt điều kiện AU được vào citation-candidate view. Nếu cho phép model-only acceptance, ghi rõ mức bằng chứng đó; không gọi human gold hay independently verified. Không cần thêm agent mặc định.

   **Test quyết định:** quote đúng tuyệt đối nhưng claim đổi “may” thành “must”, bỏ “unless”, hoặc đổi speaker party thành court. Host-valid có thể PASS; publication phải bị chặn khi assessment nhận uncertain/defect. Mock tự gán supported không chứng minh khả năng phát hiện lỗi này.

6. **P2 — Có thể reuse finite selection, nhưng không bê nguyên repair runtime sang reader loop.**

   **Claim:** reader cần chọn nguồn chưa đọc, trong khi repair catalog hiện chỉ chứa read selections. Hai domain ID phải khác nhau.

   **Evidence:** catalog hiện giới hạn 128 entries, loại ambiguous intersections; expansion thay view và invalidates IDs ([README:258](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:258)). Contract chỉ có một tool call ([wire:14](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/contracts/repair_selection_wire.v1.json:14)); runtime repair có cap sáu original proposals và relation grammar tăng theo `O(n·2^n)` ([README:203](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/repair_agent/README.md:203)).

   **Impact:** nguồn chưa đọc không chọn được nếu dùng evidence catalog làm navigation catalog; kết hợp assessment+next action có thể dùng IDs của view chưa tồn tại hoặc chạy tiếp sau submit lỗi.

   **Change:** navigation IDs cho đọc; evidence IDs chỉ từ actual read region. Response có `assessment + next_action`, nhưng host validate và commit assessment trước khi thực hiện action. Resume giữ exact resolved witnesses; re-render nguồn cần đánh giá trong request mới. Fingerprint thêm preview/navigation policy, discovery seed, assessment schema, ledger revision và acceptance policy.

   **Test quyết định:** stale evidence ID sau expansion; find-hit ID dùng làm witness; crash sau commit trước next action; replay cùng assessment. Phải reject IDs sai, không double-count assessment và không dispatch lại action đã hoàn tất. Test `"le X"` hiện tại chỉ kiểm tra reconstruction, không kiểm tra semantic adequacy.

7. **P1 — Query-trigger extraction không thể là lời hứa cứu mọi AU bỏ sót.**

   **Claim:** giữ giao diện tương lai là phù hợp; khả năng tìm lại unread source vẫn chưa có bằng chứng.

   **Evidence/phản ví dụ:** nếu một án chưa có AU về quy tắc bị bỏ sót, đường chỉ tìm trong AU không có tín hiệu để chọn án ấy cho extraction. Spec cố ý chưa quyết định retrieval view, cutoff và NN–AU matching ([spec04:294](G:/Git/coliee-case-retrieval/knowledge_base/design/pipeline_redesign_lynx/04_pipeline_spec.md:294)).

   **Impact:** KB selective có điểm mù tự duy trì; đề xuất dễ dùng tương lai chưa triển khai để biện minh cho coverage hiện tại.

   **Change:** chỉ khai báo future interface nhận source-region refs, tạo extraction assessment và trả AU qua cùng publication gate. Phân biệt rõ source navigation/extraction discovery với citation candidates; raw block không được vào candidate view. Chưa chọn NN join/Issue gate.

   **Test quyết định:** một case không có accepted AU, nhưng unread span có proposition liên quan. Khi nghiên cứu retrieval sau này, phải đo riêng source-selection recall, extraction success và candidate eligibility. Hiện tại đo preprocessing selection độc lập, không cộng “sẽ được query cứu” vào coverage.

8. **P2 — Pilot 25/50/75% cần budget cố định và thước đo chất lượng không vòng tròn.**

   **Claim:** tổng token là denominator đúng, nhưng exhaustive output không phải semantic oracle; chưa biết 9B planner có tiết kiệm sau navigation/replay hay không.

   **Evidence:** bulk/corpus đều formal verified 30 nhưng có decision và AU-count changes ([CORPUS_REVIEW:3](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/CORPUS_REVIEW.json:3)); báo cáo phủ nhận semantic quality claim tại dòng 187. Tổng token khoảng 70 nghìn mỗi arm ([BULK_REVIEW:13](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/BULK_REVIEW.json:13)). Cache observations không thay total-token accounting, và GPU/compile timing chưa đo ([PERFORMANCE_DIAGNOSIS:3](G:/Git/coliee-case-retrieval/knowledge_base/pipeline_v1/outputs/bulk_trial30_20261013/PERFORMANCE_DIAGNOSIS.json:3)).

   KOS v1 đã superseded/gold-family ([extract_strategy:71](G:/Legal-AI/kos_sample/_meta/extract_strategy.md:71)). Log chỉ kể đọc RFC/SIL hoặc chọn proxies, không có token/read trace đầy đủ ([000002 log:24](G:/Legal-AI/kos_sample/_meta/extract_log_000002_family_20260826.md:24), [000031 log:19](G:/Legal-AI/kos_sample/_meta/extract_log_000031_family_20260827.md:19)). Không suy KOS tiết kiệm hoặc phủ đủ từ AU counts.

   **Change:** khóa denominator per-case và corpus trước selective run; không tăng budget khi selective gặp lỗi. Tính mọi planning, navigation, tool text, output, repair, replay/resume và failed calls; tách fresh/reuse. Plan một batch vùng mỗi án, replan khi có obligation hoặc discovery mới.

   **Test quyết định:** so host-selected bounded batches với agent batch-plan dưới cùng nguồn/model/budget. Báo token, latency, span đọc và proposition retention/qualification trên tập kiểm tra có reference rõ. Model-silver chỉ cho agreement/retention tương đối; không cho true AU recall hay kết luận tương đương exhaustive.

**Thiết kế tối thiểu tôi đề xuất**

Host giữ source bất biến, hashes, exact offsets, SourceBlock/SentenceAtom và relations quan sát được. Không có semantic partition bắt buộc. Overview chứa metadata, kích thước, cấu trúc thật và trạng thái đọc; `list_blocks` phân trang, heading nullable, previews nguyên văn có refs. Agent không cần duyệt hết mọi trang để lập plan.

Host cấp một tập lựa chọn hữu hạn từ priority queue và discovery queue, với ngân sách discovery được bảo vệ. Agent chọn **batch vùng trong một án**, nêu reason code và câu hỏi cần giải quyết. Không gán kind/Issue cho mọi block; không quota AU tối thiểu.

`read_region` trả nguyên văn TARGET/CONTEXT, receipt về span delivered và finite evidence catalog. Preview/find hit chỉ giúp điều hướng. Mỗi assessment ghi exact assessed spans, AU proposals, từng thành phần support/qualification, obligations và phần chưa assessed. Context AU được promote thành target assessment riêng.

Một response có thể submit assessment và đề xuất hành động kế tiếp. Host commit assessment hợp lệ trước; sau đó đọc batch tiếp, expansion hoặc replan. Checkpoint lưu nguồn/version, witnesses, ledger, queue/discovery progress, usage và next-action identity. Request sau tự chứa evidence cần đánh giá; không dựa vào model memory.

Stop có hai lớp: trạng thái thực thi và policy selective đã hoàn tất hay chưa. Báo rõ source chưa assessed và obligations unresolved. Wide/full read là escalation có chi phí, không mặc định. Chỉ AU đạt publication policy đã chốt mới vào citation-candidate view; query-trigger extraction là giao diện tương lai.

**Điểm yếu của phương án này:** discovery vẫn có thể bỏ sót doctrine hiếm; nghĩa vụ chưa được model phát hiện không hiện trên ledger; dùng cùng reader để tự assessment có lỗi tương quan; replay evidence và nhiều lượt điều hướng có thể tiêu hết phần tiết kiệm. Nó là selective extraction có rủi ro được ghi nhận, không phải bảo đảm coverage.

**Trước implement cần chốt:** hợp đồng publication của “validated AU”; state/stop selective thay thế invariant exhaustive; navigation-ID/evidence-ID và semantics của combined submit/action; budget denominator cùng tiêu chí giữ/bỏ pilot. Có thể triển khai prototype hình thức sau các quyết định này. Chưa thể nghiệm thu semantic coverage tương đương nếu bỏ human annotation và chỉ có model-silver.

Review này độc lập; chưa dùng đồng thuận của agent khác làm validation.


