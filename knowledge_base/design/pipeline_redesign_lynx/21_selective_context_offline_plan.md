# Thử context có chọn lọc trước khi gọi model

## Mục tiêu và phạm vi

Kiểm tra có giảm phần context bổ sung không cần thiết so với kế hoạch20, đồng thời mở được dependency có dấu hiệu cụ thể. Chỉ chạy offline toàn nguồn KOS-5; không LLM, Modal, training, đổi pipeline mặc định hoặc thiết kế retrieval. Năm án đã dùng để nghiên cứu lỗi, nên không phải tập xác nhận giữ riêng.

Main khóa policy trước khi đối chiếu KOS. Implementer sở hữu module `knowledge_base/pipeline_v1/selective_context_offline/`; tester sở hữu `tests/test_selective_context_offline.py`. Output mới dưới `outputs/selective_context_offline_20261013/`; không sửa artifact cũ.

## Policy thử nghiệm

Giữ full order ưu tiên toàn cục, TARGET, features và packet baseline của kế hoạch20. Không chấm lại AU hoặc chọn vùng bằng KOS.

1. Scan tham chiếu paragraph trong TARGET và context ban đầu. Chỉ nhận tham chiếu cùng án có dấu hiệu ownership rõ; giữ guard quotation/reporting/external hiện có. Marker phải là opening marker của `numbered_paragraph` và khớp duy nhất trong cùng án; citation year không phải địa chỉ paragraph.
2. Nếu TARGET có cue `subject [only] to`, `provided that`, `unless`, `except/exception` hoặc `conditional on/upon`, host scan tối đa một SourceBlock ngay trước và một ngay sau cùng án. Đây là cue có thể thiếu điều kiện, chưa chứng minh dependency.
3. Không mở neighbor chỉ vì cue. Chỉ bổ sung nguyên bridge block chứa reference có ownership rõ và nguyên referenced block đang thiếu. Không scan tiếp các block vừa fetch; tối đa một reference hop.
4. Giữ context baseline trước, union span bổ sung và trừ TARGET. Cap 6.000 ký tự/12 intervals như đối chứng. Không cắt block để vừa cap; thiếu hoặc mơ hồ ghi unknown/unresolved.
5. Audit/trigger metadata chỉ lưu host; packet dùng renderer/scaffold hiện tại. Không giả định model nhớ request khác.

Policy này kiểm tra routing bằng host. Chưa kiểm tra agent nhận biết khi nào cần mở tool, và không thể phát hiện mọi condition/speaker/court response xa chỉ bằng cue.

## Đối chứng và chi phí

Đối chiếu cue-control, multi-queue, global priority packet gọn, context mở rộng trước đây và selective context. Giữ cùng ngân sách tuyệt đối `floor(247339 × fraction)` ở 10/25/50/75/100%; sensitivity UTF-8 bytes/3,/4,/5, chưa phải tokenizer Qwen.

Đo riêng hai cách thực hiện:

- **Host mở trước một request:** chỉ gửi packet đã ghép, tính toàn bộ TARGET/context/scaffold.
- **Mô phỏng hai request:** gửi packet ban đầu, rồi với mỗi packet có bổ sung gửi lại packet đầy đủ. Tính cả TARGET, context và prompt gửi lặp; đây là chi phí input giả định, chưa tính output/planner/tool/retry, chưa phải chạy agent thật. Không ghi token delta như thể model có bộ nhớ miễn phí.

Đo full-TARGET evidence KOS và CONTEXT exposure sau khi khóa selections; không coi hai metric này là AU quality. So bổ sung trên cùng tập target: bytes/token, packet được mở, dependency span đủ/chưa đủ, context gửi lặp. Tập không đọc là unknown, không được xem là negative.

## Nghiệm thu local

Giữ source/hash/offset/order/features/TARGET và artifact cũ; snapshot policy/input/selection trước KOS. Test ownership external/quoted, paragraph marker mơ hồ/citation year, cue không reference, reference đã đủ, cap nguyên block, không recursive và lỗi lock. CLI chạy output mới và từ chối overwrite.

Probe điều kiện xa `[21]→[20]→[5]` và các exception/attribution đã biết chỉ dùng phân tích lỗi sau freeze. Nếu cải thiện trên ví dụ đã biết, ghi đó là sửa gap trên calibration, không phải bằng chứng tổng quát. Không thêm cue theo output KOS trong cùng đợt đo.

Giữ selective ở mức thử nghiệm nếu chi phí tăng mà dependency vẫn thiếu. Dù kết quả tốt hơn, chỉ đề xuất thử bằng model trên workload khóa; không tự chuyển sang inference.

## Trạng thái

Đã triển khai module thử nghiệm riêng và chạy local trên toàn nguồn KOS-5. Main chạy bộ test do tester thiết kế: 19/19 PASS; verifier kiểm tra fingerprint/snapshot/chi phí gửi đầy đủ và 15 hash bảo toàn: PASS. Báo cáo cuối ở `knowledge_base/pipeline_v1/outputs/selective_context_offline_20261013/RESULT.md`, artifact chạy ở `main/revision01/`, nghiệm thu bindings/cost ở `ACCEPTANCE.json`.

Selective ghép trước chỉ mở thêm2/431 packet: input đọc đủ nguồn 248.396 so baseline247.339 (+0,43%), thấp hơn mở rộng cũ277.098. Mô phỏng hai request là249.563 (+0,90%), chưa tính output/planner/tool/retry. Gap `[21]` đã giao nguyên `[20]` và `[5]`. Ở /4, TARGET excerpt coverage giữ17/18 tại50%; sensitivity /3 giảm15→13/18. Không khẳng định giữ coverage/token thực hoặc semantic quality. Chưa đổi default hoặc gọi model. Hướng thử tiếp được đề xuất: so extraction packet gọn/selective trên cùng TARGET và contract, có workload khóa; chưa triển khai inference.
