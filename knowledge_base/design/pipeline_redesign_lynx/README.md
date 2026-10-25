# Thiết kế preprocessing và KB cho COLIEE Task 1

## Hướng hiện hành: agent authoring gần KOS

Quyết định2026-10-21: chuyển thiết kế từ extraction theo TARGET cố định sang agent chọn nguồn và soạn AU theo legal point. Chưa triển khai runtime mới hoặc chứng minh lợi ích chất lượng/token.

```text
Source bất biến + SourceBlock/SentenceAtom local
  → CaseWork và tool đọc nguồn bounded
  → agent đọc/chọn + soạn AU theo legal point
  → host kiểm nguồn/contract và lưu grounded drafts
  → snapshot có reading coverage và quality status
```

1. Agent soạn proposition tự đủ nghĩa; gom rationale/exception cùng rule khi cần, tách quyền/nghĩa vụ độc lập.
2. AU owner là case/source, evidence có thể qua nhiều block/context cũ; không buộc primary proposition trong TARGET cố định.
3. Không bắt mỗi block gọi LLM; nguồn chưa đọc giữ not_assessed, case có thể partial.
4. Không planner toàn cục, NER/cue/rhetorical-role enrichment hoặc verifier toàn corpus mặc định.
5. Host giữ source/provenance, tool/caps, receipt/cache/resume; không suy legal truth từ annotation/offset.
6. Độ dài field chỉ cảnh báo, không shortening; trần tài nguyên và truncation vẫn được kiểm.
7. Issue mở, CiteSite/NN giữ trong preprocessing; chưa chọn NN–AUmatching, candidate generation hoặc reranker.
8. K0 thử cùng union16scopes/3case của A trước; K1 mới xét đọc chủ động toàn5án; K2 cải tiến từng biến.

KOS schema/strategy local là bằng chứng thiết kế có giới hạn, không đầy đủ prompt/runtime/model/throughput. Không dùng gold-family selection của sample. P2 và các pilot trước là đối chứng/lịch sử, không tự relabel thành output của kiến trúc mới.

## Tài liệu hiện hành

- [Chuyển môi trường và commit bàn giao](44_portable_research_handoff.md): lane K0 portable dùng đường dẫn tương đối; nguồn và receipt gốc giữ nguyên byte, không phụ thuộc thư mục/runtime máy cũ để đọc lịch sử.

- [K0 v2 trên cùng nguồn cũ](43_k0_v2_same_source_authoring.md): runner riêng dùng contract v2 trên 16 scope/58 phần evidence/3 án; kiểm local trước live, chưa mở K1 hoặc xác nhận chất lượng AU.

- [Khôi phục báo cáo v2](42_v2_report_binding_recovery.md): 9controls đã hoàn tất, evaluator lỗi hash do chuẩn hóa lại kiểu số; báo cáo đọc offline từ receipt, không inference mới.

- [Contract đọc/assessment v2](41_read_assessment_contract_v2.md): bỏ scope list do model tự báo; host giữ uncertainty theo reason/action. Module controls và lệnh chạy riêng, chưa chứng minh hết omission.

- [Triển khai controls của39](40_kos_controls_implementation.md): 34test local và nativeCPU PASS; positive-only cóAU, contract cuối còn omission/trạng thái sai. Đã dừng trước authoring mới và validate0AU; chưa mởK1.

- [Cải tiến authoring theo KOS](39_kos_authoring_improved.md): Claim–Evidence–Limits, ví dụ JSON đầy đủ, no-AU/bất định có lý do, validate0AU có cap; mới là thiết kế, chưa sửa runtime hoặc chạy thêm model.

- [Triển khai và chạy K0](38_k0_implementation.md): CaseWork/ReadLedger, source-union authoring, local token counter và lệnh mock/smoke/live; chưa có semantic/live-provider acceptance.

- [Hướng agent authoring gần KOS](37_kos_style_authoring_direction.md): quyết định chuyển hướng, tool/ownership; K0 đã live đúng wire nhưng0AU, chưa đạt positive control. K1 đọc chủ động chưa triển khai.
- [Độ dài là mục tiêu mềm](36_soft_length_policy.md): chỉ warning, không loại/sửa vì dài.

Các kế hoạch 10–35 dưới đây là các đợt nghiên cứu/pilot và lịch sử P2/A. Không dùng mô tả default của chúng để ghi đè kiến trúc37 và canonical03/04/05/09.

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

Khi xung đột, 03, 04, 05, 09 và 37 là nguồn hiện hành; 39 bổ sung cách authoring/assessment và thứ tự sửa sau K0rỗng, 36 giữ chính sách độ dài mềm. File10 và các checkpoint P2/A là lịch sử. Snapshot nguyên bản trước chuyển hướng ở history_before_kos_direction_20261021/.

## Tài liệu lịch sử

agents/ và agents_round2/ giữ thiết kế/phản biện cũ làm bằng chứng, không phải đặc tả hiện hành.

## Trạng thái triển khai

Runtime hiện có gồm các module/pilot Plan01–12, tối ưu vận hành, AU claim-first và K0 authoring. K0 cũ live5request hợp wire nhưng0AU. Controls v2 đã hoàn tất9request: ba mẫu dương có4AU, ba mẫu âm trả rỗng, ba mẫu thiếu context giữ unresolved; còn cảnh báo kind holding của refund. K0 v2 là bước triển khai riêng để thử trên cùng nguồn án thật, xem43; chưa có kết quả live chứng minh chất lượng authoring, chưa mởK1. Review A có34AU trên16TARGET/3case, chưa chứng minh chất lượng hoặc chi phí toàn corpus. Các ghi chú lịch sử không thay thế trạng thái hiện tại này.

## Ranh giới bàn giao

Giai đoạn preprocessing hoàn tất khi source/context/AU/Issue/CiteSite/NN contract và phép thử đạt gate. Nghiên cứu sau mới quyết định cách nối NN–AU, retrieval view, vai trò của Issue/alias, candidate ranking và final COLIEE evaluation.
# Tài liệu bổ sung

- [Độ dài là mục tiêu mềm](36_soft_length_policy.md): thay thế shortening theo ngưỡng; chỉ cảnh báo, kiểm lại response lưu sẵn và không gọi model sửa vì dài.

- [Lịch sử phục hồi output quá dài và phép thử escape](35_length_recovery_and_escape_repro.md): shortening đã ngừng theo36; giữ checkpoint và chẩn đoán decoder, không chạy sửa chỉ vì dài.

- [Primary và supporting evidence cho AU](28_primary_support_au_pilot.md): profile opt-in chọn neo proposition và evidence hỗ trợ riêng; giữ nguồn nguyên văn, đối chứng evidence-first và local gate trước live.

- [Sửa thứ tự anchor trong grammar và probe endpoint](27_anchor_slot_grammar_fix_plan.md): đồng bộ vị trí ID với validator, giữ contract và kết quả lỗi lịch sử; tách local gate, endpoint probe và đánh giá ngữ nghĩa.

- [Evidence-first và lộ trình tự động hóa AU](26_evidence_first_automation_plan.md): thử nghiệm opt-in chọn evidence bằng model, host dựng nguyên văn; triển khai local trước, chưa promote kiến trúc hoặc xác nhận ngữ nghĩa. Kết quả calibration trước đó tại kế hoạch25 và các artifact liên quan.

- [Kế hoạch paired AU extraction: packet gọn và selective](22_au_extraction_compact_selective_paired_plan.md): cùng TARGET/prompt/contract, tách effective context pairs và no-op controls; chưa implement/chạy model.

- [Thử context có chọn lọc offline](21_selective_context_offline_plan.md): tiếp nối hai biến thể thứ tự/context, chưa thay đổi kiến trúc mặc định.

- `12_plan09_semantic_remediation.md`: kế hoạch model-only để cách ly và sửa lỗi semantic của model-silver, hoàn tất target còn thiếu và audit độc lập.

