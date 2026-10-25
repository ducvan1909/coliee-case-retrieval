# Deploy Qwen3.5-9B trên Modal Workspace mới

File triển khai: `qwen35_9b_l40s.py`.

Deployment này không dùng Volume hoặc draft model của endpoint Modal Library cũ. Nó tự tạo Volume `coliee-qwen35-9b-model-cache`, tải revision đã khóa của `Qwen/Qwen3.5-9B`, rồi chạy SGLang trên một L40S. Endpoint yêu cầu Modal Proxy Token.

## 1. Chuẩn bị CLI và chọn đúng Workspace

Chạy từ thư mục gốc repo bằng PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r knowledge_base\pipeline_v1\deployments\modal\requirements-deploy.txt
.\.venv\Scripts\modal.exe setup
.\.venv\Scripts\modal.exe token info
.\.venv\Scripts\modal.exe profile current
```

Nếu máy có nhiều tài khoản Modal, dùng `modal profile list` và `modal profile activate <profile>` trước khi tiếp tục. Không lưu Modal API token vào repo.

## 2. Tải model vào Volume của Workspace mới

Bước này không dùng GPU và chỉ cần chạy một lần cho mỗi Workspace:

```powershell
.\.venv\Scripts\modal.exe run knowledge_base\pipeline_v1\deployments\modal\qwen35_9b_l40s.py::download_model
```

Nếu bỏ qua, container đầu tiên sẽ tự tải model trong cold start. Prefetch riêng giúp phân biệt lỗi tải model với lỗi khởi động SGLang.

## 3. Deploy endpoint

```powershell
.\.venv\Scripts\modal.exe deploy knowledge_base\pipeline_v1\deployments\modal\qwen35_9b_l40s.py --strategy recreate --stream-logs
```

`--strategy recreate` phù hợp với giới hạn `max_containers=1`: khi deploy lại, Modal thay container cũ thay vì cần thêm một container thứ hai cho rolling update.

Kiểm tra app và log:

```powershell
.\.venv\Scripts\modal.exe app info coliee-qwen35-9b-l40s
.\.venv\Scripts\modal.exe app logs coliee-qwen35-9b-l40s -f
```

## 4. Tạo token gọi endpoint

```powershell
.\.venv\Scripts\modal.exe workspace proxy-tokens create --name coliee-pipeline
```

Ghép ID và secret mà Modal in ra thành `wk-....ws-....`. Secret chỉ hiện một lần. Đây là Proxy Token gọi endpoint, không phải API token của Modal CLI.

Điền vào `knowledge_base/.env`:

```dotenv
AU_URL=https://<server-url>/v1/chat/completions
AU_TOKEN=wk-....ws-....
AU_MODEL=Qwen/Qwen3.5-9B
```

## 5. Xác minh trước khi chạy corpus

Dùng output root mới để tránh dùng lại cache từ endpoint cũ:

```powershell
$out = "knowledge_base\pipeline_v1\outputs\l40s_probe_$(Get-Date -Format yyyyMMdd_HHmmss)"

.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_only warmup `
  --execute `
  --output-root "$out\warmup"

if ($LASTEXITCODE -eq 0) {
  .\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.au_compact structured-output-probe `
    --execute `
    --output-root $out
}
```

Sau đó chỉ chạy một target smoke. Chưa chạy toàn manifest cho đến khi xác nhận: không OOM, schema được áp dụng, response không bị cắt và AU có chất lượng ngữ nghĩa chấp nhận được.

## Giới hạn đã chủ động đặt

- `max_containers=1`, gateway `target_concurrency=4`, `max_concurrency=8`; SGLang `max-running-requests=1` và mutex inference vẫn giới hạn một inference;
- context và tổng token phía server là 12.288;
- CUDA Graph chỉ capture batch size 1;
- scale về 0 sau 120 giây không hoạt động;
- không dùng DFLASH hoặc speculative draft model;
- giữ XGrammar/structured output của SGLang;
- giữ multimodal và các tham số Mamba từ recipe Qwen3.5 đã chạy được; chỉ đánh giá bỏ chúng trong một thử nghiệm riêng.

`structured-output-probe` chỉ xác minh giao thức. Nó không chứng minh AU extraction đúng về ngữ nghĩa.

## Durable job gateway (chưa xác minh remote)

SGLang chạy nội bộ tại `127.0.0.1:8001`; FastAPI/uvicorn expose port 8000.
`POST /v1/chat/completions` vẫn proxy đồng bộ cho warmup/probe, không hỗ trợ
streaming. Warmup startup gửi trực tiếp payload có `enable_thinking=false` qua
urllib trong `chat_template_kwargs`, tránh helper cũ làm mất cờ này. Không đổi grammar hay schema trong
deployment: client có thể gửi payload ablation nhẹ hơn và tạo job ID mới.

Module `job_gateway.py` được `.add_local_file` vào `/opt/coliee/job_gateway.py`
và load bằng importlib; không phụ thuộc package path. API Python:
`canonical_payload(payload) -> bytes`, `payload_job_id(payload) -> str`,
`create_app(store_root, commit, backend_url=..., backend_timeout=1800,
max_body_bytes=4194304) -> FastAPI`. `app.state.gateway` quản lý worker;
lifespan gọi start/recover và stop. Callback production là **job_volume.commit**,
không commit model Volume khi lưu job. Timeout phải trong `(0, 1800]` giây.

Client phải dùng chính xác thuật toán:

```python
import hashlib, json
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode("utf-8")
job_id = hashlib.sha256(canonical).hexdigest()
```

`POST /v1/jobs` nhận đúng `{"job_id": job_id, "payload": payload}`. Giới hạn
toàn request body là 4 MiB, ID là 64 ký tự hex thường; JSON duplicate keys,
NaN/Infinity, streaming và ID sai bị từ chối. POST commit `queued` trên Volume
riêng `coliee-qwen35-9b-durable-jobs` mount `/job-store` **trước** HTTP 202.
Gửi lại payload giống hệt trả trạng thái hiện tại, kể cả `completed`, không
inference lại; ID/payload xung đột trả 409. Mọi trạng thái tồn tại trả 202.

`GET /v1/jobs/{job_id}` trả job metadata, trạng thái, timestamps; không trả
request payload. `completed` có `response` là toàn bộ JSON provider, `usage`,
`payload_sha256=job_id`, `provider_http_status`, `inference_seconds`, `response_sha256` (SHA-256
của response theo cùng canonical JSON). GET unknown ID trả 404, ID sai trả 400.
Volume chứa request evidence và response riêng tư; gateway không ghi payload,
auth headers hay raw exception vào log. Modal Proxy Token tiếp tục bảo vệ toàn
endpoint; gateway không forward/lưu auth headers. Đây là quyền truy cập cấp
workspace, không có phân quyền riêng theo từng job. Không chia sẻ token.

Một mutex toàn process serialize atomic replace + Volume commit; một worker
và một inference mutex serialize cả queued jobs lẫn synchronous probes.
Sync probe dùng nonblocking acquire: khi inference mutex đang bận trả HTTP 409
ngay, không chiếm slot chờ làm nghẽn poll. Worker quét hàng đợi chỉ giữ store
mutex; chỉ lấy inference mutex khi có candidate, rồi kiểm tra lại trạng thái
trước dispatch. Hàng đợi rỗng không giữ inference mutex. Warmup retry có giới
hạn khi 409 chứa đúng thông báo `Inference busy`; các 409 khác vẫn dừng.
Worker commit `running` trước gọi
urllib nội bộ; không retry backend. HTTP
error => `failed`; lỗi decode sau nhận response => `failed`; timeout/transport
với kết quả chưa biết => `interrupted`, chặn mọi inference tiếp đến restart.
`error` chỉ có phase, loại lỗi, outcome_unknown khi phù hợp; không có exception
message. Job kết thúc có thời gian backend kể cả lỗi. Commit failure khóa
admission/dispatch và GET trả 503 vì durability không còn xác nhận được.

Startup chuyển mọi `running` thành `interrupted` và commit; **không tự retry**.
`queued` được resume sau recovery, dù client mất kết nối trước nhận 202.
`failed`/`interrupted` cũng không được chạy lại khi POST cùng ID. Muốn chủ động
thử lại phải review outcome và gửi payload mới có identity mới; không có route
reset/delete. Atomic replace tránh đọc JSON dở, commit mới là durability boundary.

Poll GET định kỳ (ví dụ 10 giây) để giữ hoạt động HTTP trong thời gian job chạy
và lấy kết quả sau client timeout. Background thread tự nó **không đảm bảo**
Modal giữ container sống: ngừng poll có thể dẫn đến scaledown sau 120 giây,
ngay cả lúc inference chạy. Exit grace là 60 giây; worker chờ tối đa 50 giây.
Abrupt shutdown có thể mất kết quả chưa commit: durable `running` chỉ chứng minh
đã dispatch, không chứng minh backend chưa hoàn tất. Restart đánh dấu unknown
outcome. Không hứa exactly-once khi crash; chỉ không tự dispatch lại running.
Giữ `max_containers=1` và dùng recreate để tránh nhiều writer cùng Volume.
Volume riêng này không tự xóa job; cần chính sách retention riêng nếu dùng lâu dài.

### Kiểm tra local, không inference/deploy

Chạy syntax/import deployment bằng Python repo (không gọi Modal remote):

```powershell
.\.venv\Scripts\python.exe -c "import ast,pathlib; root=pathlib.Path('knowledge_base/pipeline_v1/deployments/modal'); [ast.parse((root/n).read_text(encoding='utf-8')) for n in ('job_gateway.py','qwen35_9b_l40s.py')]; print('syntax PASS')"
```

Kiểm thử HTTP cần `fastapi`, `httpx` (TestClient) trong môi trường local.
Load module bằng importlib; tạo app bằng `create_app(temp_dir, fake_commit)`
và thay `app.state.gateway.call_backend` bằng fake trả `(200, response_bytes)`.
Dùng `with TestClient(app)` để chạy recovery/worker. Fake backend cần event
chặn để có thể kiểm tra GET/poll khi job đang `running`:

- Assert commit `queued` xảy ra trước POST 202, commit `running` trước fake dispatch;
  POST trùng nhiều lần chỉ có một dispatch; `completed` lấy lại response/usage/digest.
- Assert ID sai, path traversal, body >4 MiB, duplicate keys, NaN và streaming bị reject;
  GET không chứa `payload`, unknown ID 404; error không chứa prompt/auth.
- Seed records `running`/`queued`, start app mới: running thành interrupted,
  queued chạy một lần; completed/failed/interrupted không dispatch lại.
- Fake HTTPError => failed; fake TimeoutError => interrupted, job kế tiếp còn queued;
  commit callback raise trước dispatch => không gọi backend và trả 503.
- Nhiều POST đồng thời và synchronous probe: fake backend đo active count <=1;
  GET vẫn trả nhanh trong lúc fake inference chặn. Test stop/start với job đang
  chạy, chỉ recovery mới quyết định unknown outcome nếu chưa lưu kết quả.

Các kiểm tra local này không chứng minh persistence trên Modal Volume thực,
timeout xuyên proxy, grammar latency hoặc chất lượng AU. Cần validation remote
riêng khi được cho phép.

## Runtime JSON diagnostics riêng cho Plan 12

`json_diagnostic.py` được mount cùng gateway. Main deploy bằng lệnh ở mục 3;
implementer chỉ kiểm tra local. Các route mới kế thừa `unauthenticated=False`
của Modal server: cần Proxy Token, không có auth độc lập trong FastAPI.
Không expose gateway trực tiếp ra public network. Local test chỉ kiểm tra
khai báo private; xác minh Proxy Token/HTTP unauthorized cần Main chạy remote.

- `GET /v1/diagnostics/json/info`: GET nội bộ `/get_server_info` và
  `/get_model_info`, mỗi call timeout 3 giây, response tối đa 1 MiB; đọc đúng
  `config.json`, `generation_config.json`, `tokenizer_config.json` dưới model
  path đã khóa. Trả version package và whitelist typed EOS/stop IDs/config;
  không trả path, template, model text, environment, credential hay exception.
  API backend không hỗ trợ được ghi `available=false`, không fallback inference.
  `text_config.eos_token_id` và tokenizer `eos_token` chỉ dùng allowlist được
  giữ lại. `scheduler` lấy metadata từ hook constructor thật, xem dưới đây.
- `POST /v1/diagnostics/json/replay`: chỉ nhận `case_id=invalid_reason_int`,
  canonical payload SHA-256
  `62245e6597435a6d9012b558f45ace72bb0064abc2ee1529c41480cd090893ee`
  và đúng saved payload. Old job phải tồn tại và terminal. Hash sai trả 409,
  request field ngoài whitelist trả 400; không có arbitrary path/URL/env input.
  Route trả job metadata đã lọc, không trả model text.
- Inspection và admission replay dùng nonblocking `INFERENCE_MUTEX`, busy trả
  409; backend unknown/poisoned/stopping trả 503. Replay qua worker hiện có,
  không gọi backend trực tiếp, không retry. Replay thêm duy nhất OpenAI `user`
  với binding cố định `coliee-plan12-json-diagnostic-20261012-attempt-1`, làm
  identity mới và được báo trong report. Messages, grammar, token cap và sampling
  giữ nguyên. Đây là thay đổi control metadata so với exact payload cũ; chưa
  xác minh remote SGLang nhận/ignore field `user`. POST lặp trả cùng job kể cả
  failed/interrupted; tối đa một dispatch cho binding này trên durable store,
  không hứa exactly-once qua crash/Volume rollback.

Chạy từ repo root, sau khi Main deploy. CLI dùng `settings()` và
`load_au_runtime_config(..., "AU_COMPACT_")` để đọc `knowledge_base/.env`;
process environment ưu tiên như runner hiện có. Không truyền token trên
command line. Mỗi command dùng report mới, CLI từ chối overwrite:

```powershell
# GET info + GET old job; không POST, không retry
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.deployments.modal.json_diagnostic `
  --output knowledge_base\pipeline_v1\outputs\plan12_runtime_info_20261012.json

# Main: chỉ khi được phép thực hiện failing-request repro
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.deployments.modal.json_diagnostic `
  --execute --output knowledge_base\pipeline_v1\outputs\plan12_runtime_replay_20261012.json

# GET replay status; lặp command với output filename mới nếu còn queued/running
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.deployments.modal.json_diagnostic `
  --replay-status --output knowledge_base\pipeline_v1\outputs\plan12_runtime_replay_status_20261012.json
```

CLI kiểm tra identity của payload/result local và old remote job trước replay.
Không tự poll, không redirect auth, timeout HTTP 20 giây, read tối đa 1 MiB.
Info lỗi vẫn thử GET old job; report giữ HTTP status, không lưu raw error.
Nếu cold start chưa sẵn sàng, Main có thể chạy lại GET-only command mỗi 30 giây
với report mới, tối đa 600 giây; CLI không tự warmup hay POST để readiness.
POST timeout không retry: GET fixed replay ID qua `--replay-status` trước hành
động tiếp theo. Giữ GET polling dưới 120 giây để tránh scaledown khi job chạy.
Read-only ở đây mô tả diagnostics không dispatch inference; cold start của
deployment **vẫn có warmup inference hiện có**, ngoài diagnostic replay budget.
`startup_warmup` ghi requests/usage/latency/outcome từ warmup hiện có; không
gọi thêm request. Nếu chưa quan sát được thì các field số là `null`, outcome
`not_observed`; không biến thiếu evidence thành zero usage. Container startup
thất bại không expose gateway, nên accounting của warmup lỗi vẫn không lấy
được qua API này.

Giới hạn evidence: checkpoint EOS/tokenizer metadata không chứng minh active
scheduler stop set. `sitecustomize.py` được mount dưới
`/opt/coliee/diagnostics`, nạp qua `PYTHONPATH` trước SGLang child startup;
startup cũng cài hook trong interpreter hiện tại. `json_runtime_hook.py`
intercept import `sglang.srt.constrained.xgrammar_backend`, bọc constructor
`XGrammarGrammarBackend.__init__`. EOS sync là **mandatory**: trước khi gọi
constructor gốc, thay riêng argument `model_eos_token_ids` bằng union đã kiểm tra
của input model IDs, `tokenizer.eos_token_id` và `additional_stop_token_ids`.
Không mutate tokenizer hoặc tập model IDs của scheduler. Không sửa checkpoint
weights/config, source pháp lý, schema, limits, sampler; không dùng broad masks
hoặc `ignore_eos`. Các argument khác giữ nguyên giá trị và object identity.
Hook capture **đúng TokenizerInfo trả về cho constructor đó** và xác minh stop
set bằng chính xác union **trước khi backend gốc tạo GrammarCompiler**. Nếu
`override_stop_tokens` khác `None`, nó cũng phải bằng union. Constructor không
capture TokenizerInfo (kể cả nhánh init_xgrammar khác), signature không hỗ trợ,
EOS không đọc được/không hợp lệ/rỗng/ngoài vocab hoặc actual stop set không khớp
đều fail closed. Không fallback về runtime EOS cũ.
Không sửa source đã cài, không đổi `dispatch_ebnf`, matcher hoặc decode policy.
Original return/exception identity khi sync state hợp lệ và TokenizerInfo
factory được bảo toàn; install idempotent, factory luôn restore trong finally.
`scheduler.model_eos_token_ids` và `input_model_eos_token_ids` là IDs đầu vào;
`effective_grammar_eos_token_ids` và `expected_eos_union` là union truyền vào
constructor; `eos_sync_status=validated`, `eos_sync_mode=mandatory` chỉ được ghi
sau kiểm tra actual TokenizerInfo và override. `active_grammar_stop_set` vẫn lấy
`xgrammar_stop_token_ids` thật từ TokenizerInfo, không suy từ metadata checkpoint.
Hook ghi JSON tối đa 16 KiB bằng atomic replace vào đúng
`/tmp/coliee-json-scheduler-info.json`; gateway đọc file cố định qua whitelist.
Startup xóa snapshot cũ trước backend mới. Diagnostic field lỗi ghi sentinel
`available=false`, không ghi exception string; lỗi ghi file không làm fail
constructor gốc. Trước nghiệm thu remote phải xác minh `scheduler.available=true`,
sync status/mode, expected union và actual stop IDs. Hook ghi constructor state,
không theo dõi mutation
state sau constructor. Chưa có live grammar mask;
`grammar_mask.available=false` là giới hạn rõ ràng.
Parent startup import/install hook bắt buộc, ngoài try cleanup diagnostic:
install lỗi dừng startup. Trong child, `sitecustomize.py` chuyển lỗi bootstrap
thành `SystemExit` với thông báo cố định vì Python bỏ qua ordinary sitecustomize
exceptions. Hook loader không swallow lỗi sync khi backend module được import.
Chỉ lỗi I/O unlink/snapshot là tùy chọn và không làm hỏng successful sync.
Unlink lỗi khiến gateway ghi `scheduler.setup_available=false`, bỏ đọc snapshot
để tránh evidence cũ. Giữ cách bổ sung inherited PYTHONPATH sau Modal runner
bootstrap; không đặt PYTHONPATH trong image `.env`.

Không gọi `/generate`: chưa xác minh đường lấy **cùng tokenized chat
prompt** và grammar/sampling semantics, nên không dùng probe khác làm bằng
chứng cho exact request. `choices[].finish_reason` chỉ là normalized chat reason;
`choices[0].matched_stop` được giữ nguyên khi backend cung cấp numeric stop ID;
server job đã lưu của case này có 248046. Đây là evidence riêng với raw trace.
raw finish reason/matched token IDs và `output_ids` chỉ được ghi khi thực sự có
trong saved backend response. Với chat response thông thường chúng unavailable.
Không tự replay: Main đọc actual constructor stop IDs trước; nếu chúng cùng
saved matched_stop và local mask đủ phân xử thì không cần inference mới.
Chỉ đổi grammar EOS input bằng union; schema, policy, model/version và source
SGLang đã cài được bảo toàn. Implementer không chạy inference/deploy remote.

Kiểm tra local (mock backend; không deploy/inference remote):

```powershell
.\.venv\Scripts\python.exe -m unittest `
  knowledge_base.pipeline_v1.tests.test_eos_sync `
  knowledge_base.pipeline_v1.tests.test_eos_sync_independent `
  knowledge_base.pipeline_v1.tests.test_modal_json_diagnostic `
  knowledge_base.pipeline_v1.tests.test_modal_json_diagnostic_independent `
  knowledge_base.pipeline_v1.tests.test_au_job_gateway_asgi `
  knowledge_base.pipeline_v1.tests.test_au_job_gateway
```

`test_eos_sync` chạy từ `.venv` Python 3.12; phần native XGrammar 0.2.1 dùng
Python 3.10 đã có sẵn vì wheel diagnostic local là cp310. Test đọc dependency
đã giải nén ở `outputs/grammar_diagnostic_deps`, tokenizer và failing payload
đã lưu; không download/install, không ghi đè artifact lịch sử. Thiếu runtime
native hoặc dependency làm test fail, không skip. Mask xác minh hai EOS chặn
trước root và cho dừng sau root; rooted JSON, finite IDs và ràng buộc AU/evidence
được kiểm tra bằng grammar production giữ nguyên. Đây là local protocol evidence,
không chứng minh auth/Volume/runtime remote hay semantic AU quality.

Main sở hữu `run_eos_sync_test.ps1` và quyết định deploy/GET metadata sau kiểm
tra local. Script có warmup và probe trả phí khi chạy đầy đủ; implementer không
chạy script này. Inference xác minh endpoint cần scope riêng do Main quản lý.
