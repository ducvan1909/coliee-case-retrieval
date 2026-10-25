# Thiết kế preprocessing và KB cho COLIEE Task 1

Bộ tài liệu hiện tại thiết kế phần trước retrieval:

    Corpus source
      → SourceBlock/SentenceAtom và sidecars
      → AnalysisRegion tạm
      → AU extraction và repair chọn lọc
      → AU store

    Query source
      → marker/citation cue
      → CiteSite
      → NN

    AU/NN
      → Issue metadata mở nếu có

Issue được giữ như nhãn mở có status và provenance. Tài liệu chưa quyết định cách dùng Issue hoặc phương pháp khác để nối NN với AU.

## Kiến trúc hiện hành P2

1. Source bất biến, hash, exact offsets và provenance.
2. Structural pre-pass tạo SourceBlock leaf có thứ tự, không chồng lấn; heading chỉ là tín hiệu hình thức.
3. SentenceAtom và worker local tạo địa chỉ cùng annotation sidecar.
4. Không tạo global LegalUnit partition. LegalUnit cũ chỉ còn là arm P1 để đối chứng.
5. Scheduler dựng AnalysisRegion tạm từ target blocks, bounded context, structural relation và ContextHint.
6. Mọi content block là target và có trạng thái trong CoverageLedger; không auto-skip theo citation hoặc AU cue.
7. AU extraction model zero-shot/few-shot ưu tiên recall. ContextObligation yêu cầu mở thêm vùng khi thiếu evidence; model/agent sửa chỉ xử lý ca khó.
8. AU accepted có exact evidence, attribution và condition theo acceptance profile.
9. Marker FRAG/REFERENCE/CITATION tạo CiteSite; fallback không marker có origin riêng.
10. NN được tạo từ bounded query context.
11. Issue đi qua IssueProposal → phân xử → IssueLink; alias có status/provenance riêng.
12. Không có Issue gate, CandidatePair, candidate retrieval hoặc reranker trong phạm vi hiện tại.

Lynx được dùng cho document/part/annotation/provenance, worker tách rời, NER/reference/terminology và persisted workflow. NLP output là feature/proposal, không tự trở thành kết luận pháp lý.

## Tài liệu hiện hành

- [Thử giới hạn độ dài tại decoder](34_length_constraints_decoder_probe.md): kiểm tra phiên bản, cap từng chuỗi, Unicode/escape và overhead; benchmark riêng trước khi sửa endpoint hoặc checkpoint A.
- [Phép thử A: AU sát nguồn và gom legal point](33_source_close_grouped_au_experiment_a.md): giữ model/schema/cap; chưa thử tăng cap hoặc đổi model, chưa khẳng định chất lượng sau kiểm tra local.
- [Claim-first v2: giữ nghĩa và đủ legal point](32_claim_first_v2_fidelity_coverage.md): sửa prompt/few-shot, giữ schema và model; so chủ thể, ngoại lệ, omission và tổng chi phí trước khi mở rộng.
- [Pilot AU theo legal point, một lượt chính](31_claim_first_au_pilot.md): claim/kind/evidence/limits, context chọn lọc và cho sửa toàn AU; giữ cùng 16 TARGET/model để kiểm phương pháp trước khi mở rộng.
- [Sửa readiness, grammar và recovery KOS](30_kos_readiness_grammar_recovery_fix.md): warmup chung, ràng buộc global/anchor và nhập receipt hợp lệ sang checkpoint mới có provenance, giữ nguyên run lỗi.
- [So AU KOS và pipeline trên cùng vùng nguồn](29_kos_same_source_au_comparison.md): khóa các vùng chứa evidence của 18 AU reference; tách annotation KOS khỏi model input, không coi overlap là chất lượng ngữ nghĩa hoặc coverage toàn án.
- [Triển khai nhanh hai mốc để so sánh KOS](13_fast_kos_comparison_plan.md): AU baseline đầy đủ trước; NN/Issue/snapshot tối thiểu sau, không thay semantic gate thành protocol gate.
- [Thử tối ưu tốc độ theo từng bước](14_speed_optimization_plan.md): concurrency 1/2/4 trên một GPU, sau đó prefix caching và batching; tách khỏi checkpoint Mốc1.
- [Tham khảo thiết kế tối ưu bên ngoài](15_external_design_optimization_review.md): phân biệt batch vận chuyển với gộp target trong prompt.
- [Bulk, pending queue và corpus runner](16_bulk_corpus_implementation.md): app thử C4 riêng, manifest30 và cổng kiểm tra trước khi chạy remote.
- [Phản biện đọc chọn lọc](reviews_selective_reading_20261013/README.md): hai review độc lập, một vòng kiểm tra chéo.
- [Pilot đọc chọn lọc H/P](18_selective_reading_pilot.md): đã chạy so cùng 30 target; chưa thay exhaustive default vì omission và overhead planning.
- [Xếp hạng vùng nguồn và kiểm tra offline KOS-5](19_host_region_priority_offline_plan.md): prototype nhiều hàng đợi trên toàn nguồn năm án; KOS chỉ đối chiếu sau chọn, chưa gọi model và chưa thay default.
- [Hai phép thử local: ưu tiên chung rồi dependency context](20_single_priority_dependency_offline_plan.md): đổi scheduler trước, khóa thứ tự rồi đổi context; so cùng ngân sách tuyệt đối, chưa inference.

- [Audit V13–V15](01_current_pipeline_audit.md)
- [Ma trận và phiếu đọc Lynx](02_lynx_research_review.md)
- [Bảng quyết định preprocessing](03_decision_log.md)
- [Đặc tả pipeline và KB](04_pipeline_spec.md)
- [Kế hoạch thực nghiệm preprocessing](05_experiment_plan.md)
- [Kiểm kê corpus và tài nguyên](06_corpus_scale_inventory.md)
- [Nghiên cứu bổ sung](07_supplemental_research.md)
- [Audit thành phần vòng 2](08_component_audit_round2.md)
- [Kế hoạch xây KB và thông tin cần có](09_kb_build_plan.md)
- [Lý do và phương án P2 SourceBlock/AnalysisRegion](10_sourceblock_analysis_region_proposal.md)
- [Các kế hoạch triển khai tăng dần và cổng đánh giá](11_incremental_implementation_plans.md)

Khi xung đột, 03, 04, 05 và 09 là nguồn hiện hành. File 10 giữ lập luận, rủi ro và lịch sử quyết định P2.

## Tài liệu lịch sử

agents/ và agents_round2/ giữ thiết kế/phản biện cũ làm bằng chứng, không phải đặc tả hiện hành.

## Trạng thái triển khai

P2 hiện đã được chốt ở mức tài liệu, chưa được implement hoặc xác nhận thực nghiệm. Module pilot fixed-window/BM25/Qwen cũ không phải runtime của P2. Chưa có kết quả chứng minh block/region/AU/NN quality hay chi phí toàn corpus.

## Ranh giới bàn giao

Giai đoạn preprocessing hoàn tất khi source/context/AU/Issue/CiteSite/NN contract và phép thử đạt gate. Nghiên cứu sau mới quyết định cách nối NN–AU, retrieval view, vai trò của Issue/alias, candidate ranking và final COLIEE evaluation.
# Tài liệu bổ sung

- [Độ dài là mục tiêu mềm](36_soft_length_policy.md): thay thế shortening theo ngưỡng; chỉ cảnh báo, kiểm lại response lưu sẵn và không gọi model sửa vì dài.

- [Phục hồi output quá dài và thu nhỏ phép thử escape](35_length_recovery_and_escape_repro.md): chỉ sửa hai output lỗi của thử nghiệm A; giữ checkpoint cũ và chưa đổi decoder.

- [Primary và supporting evidence cho AU](28_primary_support_au_pilot.md): profile opt-in chọn neo proposition và evidence hỗ trợ riêng; giữ nguồn nguyên văn, đối chứng evidence-first và local gate trước live.

- [Sửa thứ tự anchor trong grammar và probe endpoint](27_anchor_slot_grammar_fix_plan.md): đồng bộ vị trí ID với validator, giữ contract và kết quả lỗi lịch sử; tách local gate, endpoint probe và đánh giá ngữ nghĩa.

- [Evidence-first và lộ trình tự động hóa AU](26_evidence_first_automation_plan.md): thử nghiệm opt-in chọn evidence bằng model, host dựng nguyên văn; triển khai local trước, chưa promote kiến trúc hoặc xác nhận ngữ nghĩa. Kết quả calibration trước đó tại kế hoạch25 và các artifact liên quan.

- [Kế hoạch paired AU extraction: packet gọn và selective](22_au_extraction_compact_selective_paired_plan.md): cùng TARGET/prompt/contract, tách effective context pairs và no-op controls; chưa implement/chạy model.

- [Thử context có chọn lọc offline](21_selective_context_offline_plan.md): tiếp nối hai biến thể thứ tự/context, chưa thay đổi kiến trúc mặc định.

- `12_plan09_semantic_remediation.md`: kế hoạch model-only để cách ly và sửa lỗi semantic của model-silver, hoàn tất target còn thiếu và audit độc lập.

