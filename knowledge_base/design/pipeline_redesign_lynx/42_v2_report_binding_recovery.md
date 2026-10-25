# Khôi phục báo cáo controls v2 — 2026-10-25

## Nguyên nhân đã tái hiện

9request đã completed, usage8280input+368output=8648token. Preflight, nativeCPU và identity đều PASS. Lỗi nằm sau generation, tại `kos_authoring_controls_v2.__main__.evaluate()`.

Evaluator lấy `binding.config` đã chuẩn hóa rồi gọi lại transport dry-run. Biểu thức `min(float(value), cap)` có cap kiểu int: lần đầu giá trị vượt cap thành int600/int60; đọc lại các giá trị này thành float600.0/float60.0. Python coi hai dict bằng nhau nhưng canonicalJSON khác byte, nên SHA binding mới khác SHA trong immutable intent. Transport từ chối đúng theo checksum, CLI chỉ hiện `ValueError`.

Đây không phải lỗi schema model, context dài, output truncation, quota hay coldstart. Không được đổi hash trong intent/receipt hoặc coi numeric difference là lý do bỏ kiểm provenance.

## Phần đã sửa

Reporter độc lập `experiments/recover_kos_contract_v2_report.py` đọc persisted binding nguyên kiểu JSON, không chuẩn hóa lại config và không gọi transport. Nó kiểm manifest/code/source/counter/CPU, joblist, sealed intent/receipt và usage trước đánh giá. Output chỉ dưới `recovered_report/`; bản cũ có digest hợp lệ được giữ history khi report thay đổi, gọi lại cùng dữ liệu là idempotent.

Không sửa package generation K0/v1/v2 hoặc receipt/binding đã chạy. Wrapper có `-ReportOnly`; với checkpoint hoàn tất, `-Execute` cũng đọc báo cáo offline rồi kết thúc. Với checkpoint hợp lệ nhưng chưa đủ receipt, chỉ explicit `-Execute` mới được resume; report invalid/controls fail không mở thêm workload.

## Kết quả đã khôi phục

- 9/9 protocol/structural controls PASS; usage8648token, unknown client usage0.
- Ba mẫu dương sinh các point mong đợi (multi-point có2AU), các ngoại lệ được giữ.
- Ba mẫu âm trả rỗng phù hợp; ba mẫu thiếu context trả insufficient_context/needs_context và host giữ unresolved.
- Kind holding của ví dụ refund chưa có judicial provenance rõ trong nguồn giả định: kiểm subtype vẫn cần review, không coi toàn bộ semantics đã được chứng minh.
- Không thêm HTTP/model call để khôi phục. Đây chỉ là controls tổng hợp, chưa cho phép K1 hoặc khẳng định chất lượng AU trên bản án.

## Lệnh đọc báo cáo, không inference

```powershell
G:
cd G:\Git\coliee-case-retrieval
& .\knowledge_base\pipeline_v1\experiments\run_kos_contract_v2.ps1 -ReportOnly
```

[Report khôi phục](../../pipeline_v1/outputs/kos_contract_v2_20261024_ready/recovered_report/report.json). Giữ cùng root; không tạo run khác hoặc chạy lại9request để chữa lỗi reporting.
