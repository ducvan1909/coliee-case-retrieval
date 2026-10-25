# Triển khai nhanh để so sánh với KOS

## Mục tiêu

Có bản AU baseline xử lý đủ năm án KOS-5 và báo cáo đối chiếu đọc được, sau đó tinh chỉnh theo lỗi quan sát. Không chờ hoàn tất mọi plan hoặc chứng minh mọi AU đúng. Không coi KOS/model_silver là gold.

## Mốc 1 — AU baseline và bộ đối chiếu

1. Khóa model Qwen/Qwen3.5-9B, prompt/decoder compact hiện tại, không thinking. Không đổi schema hoặc chạy R1/R2 cho mọi target.
2. Tạo manifest từ source bất biến và map SourceBlock/SentenceAtom đã kiểm tra. Mọi block có nội dung được xử lý, kể cả heading/editorial; whitespace-only được ghi rõ là host skip. Block dài dùng DerivedSlicePlan hiện có, không chia bằng cửa sổ ký tự mới.
3. Baseline không có ContextHint. Mỗi target dùng context lân cận có giới hạn theo whole atom; không lặp toàn bộ batch cũ cho từng target. Đây là baseline `m1-sourceblock-all-v1`, thích nghi từ hướng P2a, không phải workload P2a/P2b lịch sử giống hệt.
4. Preflight xác minh lại source, map, span, coverage và manifest; dự toán từ full prompt, bao gồm instructions/examples. Ước lượng UTF-8 bytes là dự phòng bảo thủ, không phải provider usage. Kiểm tra tổng request/input/output và giới hạn input từng request. Không dùng USD/request.
5. Chạy extraction có checkpoint/resume bằng runner jobs hiện có. Source sai hoặc manifest stale phải dừng trước dispatch. `needs_split`, unresolved, budget stop và target chưa chạy không được tính là coverage đã hoàn tất.
6. Đối chiếu output với KOS sau extraction: source span/claim/kind/attribution, thêm/thiếu/trùng/split-merge; output JSON và HTML có nguồn mở được. Không đưa KOS quote/position/claim vào builder hoặc prompt để chọn target.

Ownership: ghi lại AU có evidence/context nghi không cùng owner; primary selection hợp schema không chứng minh entailment. AU đề xuất được so sánh khi còn pending; không tự promote accepted. Không auto đổi speaker, claim hoặc offset để làm kết quả đẹp hơn.

## Mốc 2 — KB tối thiểu

- Plan 14: CiteSite/NN có exact source; marker và fallback không marker, không khôi phục citation từ bản không che/gold.
- Plan 15 tối thiểu: Issue label mở, mô tả/evidence/status/provenance. Chưa làm equivalence/hierarchy/auto-merge.
- Plan 16 tối thiểu: snapshot và tool đọc source, span, AU, NN, Issue, coverage. Sau đó mở rộng đối chiếu KOS từ AU sang NN/Issue/context.

Hoãn worker ablation Plan 13, repair toàn bộ, so nhiều model và P2a/P2b, held-out/toàn corpus, NN–AU matching và reranker. Chỉ thêm thành phần khi báo cáo chỉ ra nhóm lỗi cụ thể.

## Phân công và cổng

Main xây full manifest/preflight/orchestration và nghiệm thu. Implementer xây bộ đối chiếu KOS. Tester viết kiểm thử độc lập về source/hash, coverage, budgets, run thiếu kết quả, quote ambiguity, escaping, accounting và resume.

Mốc 1 sẵn sàng về code khi: manifest phủ đủ source KOS-5; preflight đầy đủ; lệnh chạy dùng cấu hình/model đã khóa; bộ đối chiếu hoạt động trên fixture và output thật có sẵn. Việc gọi inference full KOS-5 là lượt chạy riêng sau khi người dùng xem workload/preflight. Chưa chạy paid inference trong đợt triển khai local này.

Mốc 1 có kết quả thực nghiệm khi: mọi target có outcome hoặc trạng thái unresolved/unrun rõ ràng; có AU/KOS comparison và cost report. `processing complete`, `protocol verified` và `semantic accepted` là các trạng thái riêng. Missing KOS trong vùng chưa xử lý không được gọi là extraction false negative.

## Tài liệu đầu vào

- `04_pipeline_spec.md`, `05_experiment_plan.md`, `11_incremental_implementation_plans.md`.
- `manifests/calibration_manifest.v1.json`, map SourceBlock/SentenceAtom và source store của Plan 02–04.
- `au_compact/` và `repair_agent/`: decoder, source binding, cache/jobs, giới hạn của smoke Plan 12.
- `manifests/selected_kos_manifest.v1.json`; KOS chỉ là input cho bộ đối chiếu.

Không sửa báo cáo agent cũ, artifact V13–V15, KOS hoặc manifest pilot mười target.
