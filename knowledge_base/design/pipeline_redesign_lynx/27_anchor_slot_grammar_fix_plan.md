# Sửa ràng buộc thứ tự anchor và kiểm tra endpoint

## Bằng chứng và phạm vi

Nguồn: `outputs/evidence_first_20261015_205324_374/evidence_first_v1/smoke/` trong pipeline_v1. Stage1 án013009 trả JSON đầy đủ, finish_reason=stop, ba ID thuộc catalog nhưng thứ tự slot2,3,1; validator báo `anchor IDs must use host slot order`. Grammar cũ dùng một enum anchor-id chung cho mọi vị trí. Đây là lệch grammar/validator, không phải timeout hay lý do để tăng output/retry.

Đọc cùng kế hoạch26, `au_target_context/{contracts,grammar,core,runner}.py` và receipt thực. Giữ wire/schema, giới hạn0–3 AU, nguồn/hash/offset, model, prompt, .env và validator. Thứ tự slot là định danh, không là thứ hạng pháp lý. Không tự reorder output hoặc đổi artifact invalid thành PASS. Lỗi chọn heading, duplicate legal point, attribution/kind là câu hỏi ngữ nghĩa riêng.

## Thứ tự thực hiện

1. Main sửa stage1 grammar: anchor-slot-1/2/3 mỗi rule dùng literal ID riêng; chỉ nhận [],[1],[1,2],[1,2,3]. Positive chỉ1–3; negative rỗng; needs_context/unresolved0–3. Áp dụng mọi profile có cùng contract; evidence-first vẫn không có generated claim. Stage2 không thay.
2. Implementer bổ sung error_code an toàn cho receipt mới, giữ generic error cũ để tương thích. Không lưu tùy ý nội dung exception/provider. Thêm probe endpoint riêng bằng nguồn tổng hợp và grammar production, không sửa preflight để chấp nhận corpus giả. Mặc định không gọi mạng; remote cần --execute.
3. Main sửa script PowerShell UTF-8 BOM; khi lỗi hiện counts và đường dẫn receipt/error_code. Không tăng retry hoặc tự tạo root mới. Test parser/encoding local.
4. Tester độc lập replay receipt thật: vẫn bị từ chối; kiểm các hoán vị, lặp, bỏ slot đầu, ID lạ và các prefix hợp lệ. Kiểm tất cả profile/decision. Kiểm grammar bằng engine local nếu có; nếu không có phải tách structural PASS và compile/decode chưa kiểm. Test probe mock, lỗi/cắt output không thành PASS, defaults không gọi mạng, hồi quy source/stage2/cache.
5. Main prepare/preflight/mock32 hai arm và resume sau khi production .py ổn định. Giữ artifact/checkpoint lịch sử; code/payload hash mới yêu cầu workload/run root mới.
6. Người vận hành chạy probe remote nhỏ; chỉ sau protocol PASS mới chạy lại hai TARGET smoke. Kiểm source/evidence/ngữ nghĩa trước full32. Không dùng chênh thời gian giữa cached baseline và generation mới để suy speedup.

## Probe hình thức

Nguồn tổng hợp đủ ba điểm pháp lý độc lập, không chứa dữ liệu calibration. Tình huống yêu cầu đảo thứ tự, lặp ID, bắt đầu slot2, và yêu cầu đúng1/2/3 anchor. Mỗi request giữ grammar sản xuất và giới hạn output. Một profile/root mỗi lần; có thể chạy các profile khác bằng root riêng.

Phải báo riêng: ID/thứ tự hợp lệ, số anchor thực tế, số theo yêu cầu và compliance. Grammar cho phép1–3 anchor nên model trả số hợp lệ khác yêu cầu không tự chứng minh grammar lỗi. Provider failure/truncated/invalid phải giữ receipt và status rõ; không tính dừng sớm hoặc output rỗng là constrain thành công. Báo cả request/token/lỗi/usage thiếu; không test ngữ nghĩa.

## Gate và bàn giao

Code + tests + report local, probe CLI và lệnh chạy, script hiển thị đúng tiếng Việt, plan27. Hoàn tất sửa local khi positional grammar và host cùng contract, regression đạt, mock/resume/provenance không đổi. Endpoint constrained decoding chỉ được xác nhận sau probe thật; không inference/deploy trong đợt sửa local. Không sửa output cũ, không tự mở corpus hoặc đổi model.

## Nghiệm thu local — 2026-10-15

Đã triển khai grammar vị trí, diagnostic allowlist, CLI probe6ca và encoding/chẩn đoán script. Tester độc lập74/74 PASS; Main sửa thêm bộ đếm unknown_provider_attempts cho mock về0 và kiểm lại13/13 test liên quan PASS. Chi tiết tại `knowledge_base/pipeline_v1/outputs/anchor_slot_fix_20261015/RESULT.md`. Local mock32 mỗi arm39/39; endpoint decoder/grammar compile và ngữ nghĩa chưa xác minh. Không cần deploy server vì grammar đi trong payload client.
