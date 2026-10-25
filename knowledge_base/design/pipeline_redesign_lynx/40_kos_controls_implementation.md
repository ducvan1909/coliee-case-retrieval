# Triển khai kế hoạch39: controls trước authoring

Ngày2026-10-24. Đã triển khai module riêng `knowledge_base/pipeline_v1/kos_authoring_controls/`. Không sửa K0 v1, không deploy, không đổi `.env`, model hoặc nguồn; chưa mởK1.

## Phần đã có code và kiểm thử

- Ví dụ JSON đầy đủ, nguồn tổng hợp khác nguồn control; positive-only giữ grammar/source/model/caps của diagnostic cũ.
- Bộ9controls khóa trước output: dương, âm, bất định; có nhiều point độc lập và ngoại lệ.
- Grammar cuối thêm `empty_reason` và host validator kiểm kết hợp trạng thái; wire AU vẫn claim/kind/evidence_ids/limits.
- Transport durable: intent trước POST, receipt có digest trước ledger; orphan/retrieval/resume, unknown usage và trần chung qua nhiều stage.
- CPU report khóa đúng bundle/tokenizer/XGrammar/EOS; stage balanced cần positive source review, không tự pass vì sốAU.

Main chạy34test local PASS, gồm9test mới của tester độc lập. NativeCPU cả grammar cũ và mới PASS. Đây chỉ là kiểm tra cơ chế và witness, không là chất lượng authoring corpus.

## Kết quả thực thi

| Bước | Kết quả |
|---|---|
| Positive-only | 1AU đúng rule/exception, không sao chép ví dụ; Main source review hỗ trợ |
| Dương trên contract cuối | 2/3 đúng substance; notice rule vẫn bị bỏ |
| Âm trên contract cuối | 3/3 trả rỗng phù hợp |
| Bất định | 3/3 nhận ra thiếu context nhưng đánh dấu assessed_scope_ids không nhất quán; bị reject |

Tổng10POST,8173input+484output=8657token provider, không retry/truncation. Usage startup warmup chưa lấy được vì runtime-info GET503; không coi subtotal là chi phí GPU đầy đủ. Resume từ10receipt:0lời gọi mạng/0POST mới. K0 source/code/checkpoint bindings giữ nguyên.

**Cổng cuối FAIL**. Đã dừng đúng trước authoring trên bản án và validate0AU. Module hiện chỉ triển khai controls/transport, chưa là pipeline39 hoàn chỉnh. Không sửa output sai thành đúng, không ép AU không rỗng và không nâng cap.

Nguồn kết quả:

- [Đánh giá và giới hạn](../../pipeline_v1/outputs/kos_authoring_controls_20261024/EVALUATION.md).
- [Nghiệm thu](../../pipeline_v1/outputs/kos_authoring_controls_20261024/ACCEPTANCE.json).
- [Review các controls](../../pipeline_v1/outputs/kos_authoring_controls_20261024/balanced_agent_review.json).
- [Module và cách chạy](../../pipeline_v1/kos_authoring_controls/README.md).

## Phần còn lại

Chốt lại ý nghĩa read/assessed/uncertain để model không phải phát sinh thông tin dễ mâu thuẫn; không đánh đồng nhận ra thiếu context với xác nhận đã hoàn tất. Sau đó đối chứng notice trên cùng source/IDs/grammar để tách tác dụng ví dụ khỏi thay đổi wire/instruction/rendering. Mọi thay đổi dùng version/workload mới có budget khóa và control lại, không resume checkpoint cũ bằng code mới.

Chưa chứng minh ba ví dụ tốt hơn một ví dụ hoặc `empty_reason` gây lỗi bỏ sót: phép thử đã thay nhiều yếu tố giữa hai stage. Agent-review nguồn tổng hợp không là human gold hoặc kết quả chất lượng trên bản án. Authoring/ReadAssessment store, nhánh validate0AU, held-out vàK1 vẫn chờ cổng controls đạt.
