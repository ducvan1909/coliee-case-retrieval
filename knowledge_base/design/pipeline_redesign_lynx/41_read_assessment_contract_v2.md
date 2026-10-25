# Contract v2: host giữ phạm vi đọc, model không tự chứng nhận completion

Ngày2026-10-24. Sửa hẹp sau controls của39/40. Không đổi AU kind/claim/evidence/limits, không ép số AU, không đổi model/deploy và không sửa artifact cũ. Package mới: `knowledge_base/pipeline_v1/kos_authoring_controls_v2/`.

## 1. Lỗi cần sửa

Trong3controls thiếu context, model đã trả đúng `insufficient_context` và `finish_case(needs_context)` nhưng vẫn điền ID vào `assessed_scope_ids`. Contract cũ yêu cầu list đó rỗng, nên bị reject. Nhận ra thiếu context và đánh giá xong nội dung là hai việc khác nhau; không nên buộc model tự xuất một trường mà host đã có thể suy conservatively.

Control notice bị bỏ sót là lỗi khác. Bản sửa này không chứng minh đã chữa omission, và không chuẩn hóa output cũ để giả PASS.

## 2. Wire mới

```json
{
  "aus": [],
  "empty_reason": "insufficient_context",
  "next_action": {
    "tool": "finish_case",
    "reason": "needs_context"
  }
}
```

Chỉ có3field ở root. `assessed_scope_ids` bị loại khỏi output model, không đổi tên thành một list khác. AU không rỗng vẫn dùng `claim`, `kind` nullable, `evidence_ids`, `limits` nullable; revision theo contract khi có. `empty_reason` giữ enum39, positive dùng null. Navigation chưa kết luận có thể null; finish rỗng thiếu reason vẫn không hợp lệ.

Host không loại bỏ thông tin nguồn: case/hash/request, active scope IDs và evidence catalog do host sở hữu. Report vẫn giữ delivered/read/assessment/residual refs, nhưng các trường đó không còn do model liệt kê trong wire.

## 3. Cách host suy trạng thái

| Tín hiệu | Trạng thái host |
|---|---|
| Nguồn đã gửi trong request có receipt | Delivered/read exposure, không tự semantic assessed |
| `insufficient_context`/`uncertain` | Scope active chưa resolved; không âm/no-AU đã xác minh |
| `finish_case(needs_context)`, kể cả có AU | Giữ draft hợp lệ, phạm vi còn unresolved; không certify complete |
| Positive hoặc negative hợp lệ và finish work_scope_complete | Ghi nhận lời tự báo đã đánh giá phạm vi active, không semantic completeness |
| Navigation chưa kết luận | Không gán completion/no-AU cho scope active |
| Mixed scopes: facts và missing treatment | Giữ cả packet conservative uncertain/residual thay vì âm hóa đoạn thiếu context; không thêm lượt chỉ để gán nhãn từng block |

`has_au` không đồng nghĩa tìm đủ AU. `no_au_candidate` không human gold. Source chưa đọc vẫn not_assessed. Finish là work decision của agent, không kết luận pháp lý hoặc recall.

## 4. Phép thử và migration

Giữ đúng9source/ID fixtures của contract cũ để so, không chèn lời giải KOS. Ví dụ JSON và hướng dẫn phải bỏ field cũ; native grammar phải từ chối field cũ thay vì silently nhận rồi sửa. CPU kiểm đủ positive/multi/negative/uncertain; endpoint vẫn phải chạy lại controls vì grammar đã đổi.

Không dùng output cũ làm generation mới. Replay response thiếu context sau khi bỏ field cũ chỉ là regression unit test cho semantics mới, không phải endpoint PASS. K0 v1 và controls v1 được giữ nguyên package/manifest/receipt. Workload v2 riêng có code/payload/source/tokenizer bindings; resume cùng root, không gọi lại receipt hoàn tất.

Module controls v2 chưa tạo KB/ReadAssessment store cho toàn corpus. Chưa triển khai authoring bản án/validate0AU hoặc K1. Lỗi omission có thể vẫn làm control gate FAIL.

## 5. Cách chạy

Script `experiments/run_kos_contract_v2.ps1` gộp prepare khi cần, preflight, nativeCPU, warmupGET rồi controls khi có `-Execute`. Mặc định không inference. Budget giữ12POST/30000token, input6000/output800; report protocol và semantic review tách riêng. Không cần sửa `.env` hoặc deploy.

```powershell
G:
cd G:\Git\coliee-case-retrieval
& .\knowledge_base\pipeline_v1\experiments\run_kos_contract_v2.ps1 -Execute
```

Giữ cùng OutputRoot khi retry/resume; không chạy bằng command v1 hoặc trỏ vào root v1. Endpoint fail/control fail thì bảo toàn report để kiểm tra, không tự chuyển sang bản án.

## 6. Kiểm tra local đã thực thi

48test kết hợp PASS, gồm14test v2 độc lập; nativeXGrammar0.2.1 kiểm9grammar/36positive/27negative PASS. Một lượtCPU lỗi PermissionError khi ghi report được giữ trong cpu_history; chạy lại cùng bundle PASS, chưa xác định nguyên nhân file lock. Chính script ở mục5 đã chạy thành công ở chế độ không Execute, tạo workload/preflight/CPUreport và trả not_executed. 100file K0/v1 được bảo vệ vẫn nguyên hash. Ready root có ACCEPTANCE.json; chưa gọi endpoint hoặc model, chưa chứng minh chữa omission.

Checkpoint2026-10-25: người dùng đã thực thi9controls. Generation completed nhưng evaluator lỗi normalization kiểu số trong binding; đã khôi phục report offline,9/9structural controls PASS,8648token provider. Chưa đánh giá authoring bản án. Xem [42](42_v2_report_binding_recovery.md) và lệnh `-ReportOnly`; không sửa checkpoint cũ thành kết quả mới hoặc gọi lại generation.

Bước tiếp nối cùng ngày: [43 — K0 v2 trên nguồn cũ](43_k0_v2_same_source_authoring.md) triển khai runner riêng cho union16scope/58phần evidence/3án. Các đoạn nói chưa triển khai authoring ở trên mô tả checkpoint controls ban đầu; không dùng lệnh controls ở mục5 để chạy bản án. K0v2 chưa có kết quả ngữ nghĩa live.
