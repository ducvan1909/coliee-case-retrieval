# Plan22 paired AU runner

`runner.run(workload, *, source_store, atom_root, cfg, budget, output_root,
execute=False, smoke=False, opener=urlrequest.urlopen, warmup_policy=None)`
validates the locked workload with the paired preflight. With `execute=False`
it returns `not_executed` without opening a connection or writing runtime output.
The default opener is used only after explicit execution; local callers can
inject a fake opener for every warmup, decoder probe, job POST and GET.

Execution requires `Qwen/Qwen3.5-9B`, `enable_thinking=False`, `transport=jobs`,
`string_decoder=host_validated`, and an explicit jobs URL. The CLI owns loading
configuration and deriving that URL. The runner never reads or writes `.env`,
deploys, changes the schema/prompt, raises operator budgets, or silently falls
back to synchronous transport. Endpoint revision remains a separate operator
verification requirement; a local mock cannot establish the live revision.

Run `smoke=True` first. Warmup and a source-free probe precede the fixed physical
smoke subset. A full run requires the persisted successful smoke gate and its
matching immutable physical receipts. Smoke requests are reused, and shared
controls have one receipt. Schema/normalization failures and truncated output
stay unresolved; they are never repaired or resubmitted as semantic retries.

The operator must supply positive `max_requests`, `max_provider_attempts`,
`max_total_input_tokens`, and `max_total_output_tokens`. The shared loader maps
these from `AU_MAX_REQUESTS`, `AU_MAX_PROVIDER_ATTEMPTS`,
`AU_MAX_TOTAL_INPUT_TOKENS`, and `AU_MAX_TOTAL_OUTPUT_TOKENS`. Preflight requires
caps adequate for the locked workload; the runner additionally enforces at
most 34 unique extractions, 100 POST attempts globally (including warmup, probe,
and retry), 50 warmup attempts within 600 seconds, two decoder probes, and
800 output tokens per extraction. Default loader caps may be insufficient.
Only explicit operator arguments should change caps. Warmup/probe reservations
also consume input/output budgets; leave adequate headroom above extraction
reservations. GET polling has a separate persistent counter.

Input reservation uses actual rendered prompt UTF-8 bytes conservatively.
It is distinct from tokenizer estimates, HTTP bytes including grammar, and
provider usage. Missing usage remains `unknown`, with total tokens `null` and
known partial usage reported separately. Physical jobs contribute usage once.
Usage recovered from a completed server job is labeled as observed usage;
it is not proof of new billing for this output root. Explicitly rejected POST
attempts retain their own unknown cost, without duplicating completed job usage.

`runtime_ledger.json` is replaced atomically before each POST. Request receipt
files and numbered attempt receipts are immutable; recovery handles the
receipt-to-ledger crash window. Cache identity binds the complete workload,
nonsecret runtime config, runner code, request, schemas, prompt and decoder.
Changed identity rejects resume. A lost acknowledgement looks up/polls the
same payload-derived job ID. A further POST is blocked unless an explicit
503 gateway body says `accepted=false` and `error=provider_unavailable`; even
then at most one resubmission is permitted. A plain 503 proves no such fact.

An exclusive `.runner.lock` prevents concurrent writers. A hard process crash
can leave this lock: confirm that the writer stopped before removing only that
lock and resuming. Never remove ledgers or receipts to bypass budgets or gates.

Reports persist `request_ledger`, `runtime_ledger`, `pending_request_ids`, and
`stop_reason`. `execution_ledger` aliases the runtime ledger for comparison.
`run.json` is the canonical report, refreshed atomically on every execution
report, including incomplete resume; smoke/full reports are additional snapshots.
`protocol_verified` means host protocol checks succeeded;
semantic quality and gold correctness remain unassessed and require independent
review. No remote execution is authorized merely by the existence of this API.

## CLI và workload đã khóa

Module có các lệnh `build`, `preflight`, `run`, `review-packet`, `compare`.
CLI dùng profile cố định `jobs` và `host_validated`; không sửa `.env`.
Hạn mức lấy từ `AU_*`, trừ khi người chạy truyền override rõ ràng.
Workload nghiệm thu:

```text
knowledge_base/pipeline_v1/outputs/au_context_paired/implementation_20261014/locked01/workload.json
knowledge_base/pipeline_v1/outputs/au_context_paired/implementation_20261014/reference_checklist_locked.v2.json
```

Workload có32 TARGET/34 physical requests. Ba mươi control dùng chung response
G/S; hai TARGET thay đổi có hai request riêng. Checklist là source review bằng
agent, không gold; giữ ba trường hợp eligibility unknown.

Kiểm tra local, không gọi endpoint:

```powershell
G:
cd G:\Git\coliee-case-retrieval
& .\knowledge_base\pipeline_v1\au_context_paired\run_pilot.ps1
```

Sau khi kiểm tra model/revision thực của endpoint, chạy warmup/probe/smoke:

```powershell
$run = "knowledge_base\pipeline_v1\outputs\au_context_paired\pilot_$(Get-Date -Format yyyyMMdd_HHmmss)"
& .\knowledge_base\pipeline_v1\au_context_paired\run_pilot.ps1 -Execute -EndpointVerified -OutputRoot $run
```

Smoke PASS thì dùng cùng output root, reuse receipts để chạy pilot còn lại:

```powershell
& .\knowledge_base\pipeline_v1\au_context_paired\run_pilot.ps1 -Execute -Full -EndpointVerified -OutputRoot $run
```

`-EndpointVerified` là xác nhận người vận hành sau kiểm tra thực; script không
tự chứng minh revision từ file deploy local. Warmup dừng ngay khi thành công,
tối đa50 attempts/600 giây; tổng POST trần100 được giữ qua resume. Script
truyền cap34/100/500000/40000 cho requests/POST/input/output. Input500000 là
reservation bảo thủ, không dự đoán token thực; không dùng USD/request.
Smoke schema/length/lỗi thì dừng, không repair hoặc tự chạy full. Không xóa
receipt/ledger để vượt gate. `run.json` cập nhật sau mỗi resume.

Sau extraction dùng `review-packet`/`compare` cùng workload và
`--run <run>/live/run.json`. Khi chưa có decisions source-backed, comparison
giữ semantic review pending. Checklist nguồn không đồng nghĩa output model
đã được đánh giá hoặc đạt chất lượng.

### Phục hồi lần chạy 20261014_084923

Bản sửa transport yêu cầu checkpoint mới vì workload khóa hash code. Lệnh
`migrate` chỉ chạy local: kiểm tra hash runtime cũ từ bản lưu, giữ manifest,
prompt, grammar, TARGET và payload; sao chép receipt với provenance và giữ
nguyên mọi số đếm. Không chỉnh checkpoint gốc hoặc xóa chi phí đã phát sinh.

Checkpoint đã chuyển:
`outputs/au_context_paired/pilot_20261014_084923_recovered_v1/` (dưới pipeline_v1).
Đã giữ 4 receipt, 5 request được reserve, 24 POST, 18 warmup và 1 probe.
Resume bằng đúng checkpoint này:

```powershell
G:
cd G:\Git\coliee-case-retrieval
$run = "knowledge_base\pipeline_v1\outputs\au_context_paired\pilot_20261014_084923_recovered_v1"
& .\knowledge_base\pipeline_v1\au_context_paired\run_pilot.ps1 `
  -Execute -Full -EndpointVerified -OutputRoot $run `
  -Workload "$run\workload.json" `
  -ReferenceChecklist "$run\reference_checklist.json"
```

Trước request chưa hoàn tất, client kiểm tra `/health` hiện tại, tối đa 600 giây.
Job đã tồn tại chỉ được poll. Job mất ACK chỉ được gửi lại cùng payload/ID tối
đa một lần khi có hai `404 {"detail":"Unknown job"}` từ gateway đang ready,
cách nhau bằng backoff. Routing 404, 503 hoặc job đã từng được xác nhận tồn tại
không cho phép tạo lại. Lần gửi lại vẫn tính vào trần POST/token.
Nếu tất cả request được chọn đã có receipt hợp lệ thì không gọi readiness,
warmup, probe hoặc model. Những kiểm tra này chỉ xác nhận cơ chế thực thi;
ngữ nghĩa AU và tốc độ thực tế cần đánh giá sau khi resume remote.
