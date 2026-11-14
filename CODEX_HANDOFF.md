# Bàn giao Pipeline V2 cho Codex trên máy khác

## Bàn giao retrieval mới ngày 14/11/2026

Nếu tiếp tục đợt tối ưu retrieval RT1–RT5, đọc thêm `pipeline_v2/docs/RETRIEVAL_HANDOFF_20261114.md` trước khi thao tác. Tại checkpoint này RT1/RT2 đã nghiệm thu engineering, RT3 chờ AG review cuối; profile mới input 8.500/context source 12.288 chưa nghiệm thu live. Pull commit bàn giao chứa cả code/tests/hướng dẫn mới, không chỉ base `c0ab182`. File bàn giao ghi phạm vi selector máy kia, trạng thái AG và gate trước RT4. Các nội dung phía dưới giữ làm lịch sử nền/khôi phục assets.

Cập nhật kết quả AG: deploy v2 báo exit 0 nhưng canary 8.500 của call `fc-01M7CBMZWGZDPFSPB4BBT9WB94` timeout/unknown, đã yêu cầu cancel; actual provider usage chưa biết. Không resend run đã admission hoặc coi context live PASS. Theo yêu cầu bàn giao mới nhất, chỉ push code/tests/hướng dẫn cần thiết, không yêu cầu chuyển run/evidence/inventory cũ; người dùng tiếp quản phần tiếp theo theo file bàn giao mới.

Cập nhật ngày 10/11/2026. Đọc file này trước, rồi `AGENTS.md`, `pipeline_v2/docs/PROGRESS.md` và ba tài liệu trong `pipeline_v2/docs/plan/`. Các đoạn trạng thái cũ trong tài liệu kỹ thuật là checkpoint lịch sử. Tiến độ dưới đây phản ánh kết quả hiện hành.

## Cập nhật checkout đã có dữ liệu Pipeline V2

Sau khi pull, dùng lại raw corpus, các bundle đã seal, cache embedding và sparse index tại đường dẫn cũ. Kiểm collection Qdrant nếu dùng hybrid. Phần tiến độ M4–M6 mới nhất nằm trong [PROGRESS.md](pipeline_v2/docs/PROGRESS.md).

Để kiểm đường chạy M6 trên máy đích, cài dependencies và chuẩn bị tokenizer controller đã pin nếu máy chưa có. Lệnh `prepare` kiểm nguồn, index, tokenizer và payload ban đầu với 0 request inference.

```powershell
& .venv/Scripts/python.exe -m pip install -r pipeline_v2/requirements-m4-local.txt
& .venv/Scripts/python.exe -m pipeline_v2.m4_live prepare-tokenizer --tokenizer-dir cache/tokenizers/qwen36_27b_fp8
$run = "cache/m6-preflight-$(Get-Date -Format yyyyMMdd-HHmmss)"
& .venv/Scripts/python.exe -m pipeline_v2.m6_live prepare --settings pipeline_v2/reviews/m6_local_v1/live_preflight_settings.json --run-dir $run
```

Settings trên dùng BM25. Với hybrid, chạy thêm `diagnostic-hybrid` bên dưới hoặc dùng [settings kiểm tích hợp hybrid](pipeline_v2/reviews/m6_hybrid_local_v1/live_settings.json) cho một thư mục preflight mới. Các log và ledger lịch sử được giữ trên máy đã chạy. Chuẩn bị thư mục run mới cho các lượt thử trên máy đích.

## Mục tiêu và các quyết định đã chốt

COLIEE Task 1 nhận query case A và trả tập candidate cases được A thực sự viện dẫn hoặc sử dụng theo nhãn chuẩn. Agent truy tìm nguồn và evidence A→B, phân biệt source identity, vị trí đoạn và cách sử dụng. Tương đồng nội dung là tín hiệu truy hồi. Lập luận của đương sự, lời tòa và trích dẫn lồng giữ attribution riêng.

Trước query xây kho raw nguồn, cấu trúc, metadata quan sát được, passages, chỉ mục và công cụ đọc. Chưa xây doctrine/AU hoặc citation graph bằng suy luận toàn corpus. Nhãn chỉ dùng ở nghiên cứu/evaluator tách khỏi solver. Discovery/holdout và exposure ledger đã khóa ở M0. Kế hoạch hiện tại dùng micro-P/R/F1 trên unique `(query,candidate)`, đủ denominator. Kiểm lại protocol chính thức trước M7, giữ riêng mọi metric bổ sung.

- Marker `[số]` đầu dòng là boundary độc lập, role `current_case`, `quoted` hoặc `unknown` dựa evidence. Thứ tự số không điều khiển reset/gộp đoạn.
- Chunk bắt đầu từ paragraph theo cấu trúc. Parent dài tách theo tokenizer. BM25/dense dùng cùng core body và IDs, analyzer/tokenizer riêng được khai báo.
- Hit child `12b` mở full parent 12 và hàng xóm theo source order, giữ spans, hashes và pending continuation. Không dùng marker ±1 để tìm hàng xóm.
- Query vừa budget agent đọc toàn văn. Query dài dùng map, preview có provenance, context ưu tiên và mở thêm theo nhu cầu. Tokenizer/model/budget agent M4 còn cần chốt.
- Giữ nguyên tiếng Pháp, hiện chưa phân tích ngữ nghĩa hoặc tune riêng. Không dùng language metadata làm bộ lọc bỏ nguồn.
- Codex viết/sửa production. AG review, viết test độc lập và chạy các lệnh được giao. Codex chỉ đưa lệnh Modal để người dùng/AG chạy theo yêu cầu hiện hành.

## Tiến độ và nghiệm thu

| Mốc | Trạng thái |
|---|---|
| M0 | Khóa nguồn train, cohort 10 discovery + 10 holdout và exposure ledger. Embedding đã chốt sau checkpoint M0. |
| M1 | Nghiệm thu raw registry, UTF-8 offsets và cấu trúc marker/quotation/unknown theo contract. |
| M2 | Nghiệm thu toàn train, 7.708 án, 382.343 parents, 415.693 passages, tối đa 448 full-input tokens, mapping parent/context. |
| M3 | Full embedding/cache/Qdrant integrity đã nghiệm thu. BM25 sparse hai kênh và hybrid local dùng vector cache đã qua AG review. Còn các công cụ case/phrase/identity/context và query embedding thật. |
| M4 | Chưa có harness agent hoàn chỉnh. Cần tool delivery ledger, budgets, resume/fallback và invalidation assessments. |
| M5 | Chưa có baseline lịch tìm/đọc cố định end-to-end cho V2. |
| M6 | Chưa có controller thích ứng và targeted review. |
| M7 | Chưa chạy đánh giá khóa/F1. |

Full ingestion có 6.496 batch thành công, 55.346.360 input tokens và 55.360.576 padded tokens. Ledger còn 1 attempt `started` bị ngắt, tokens/elapsed `null`. Giữ nguyên khoản usage unknown này. Full DB có 415.693 points. Không cần embed lại corpus.

Sparse review đạt 37/37 unit/regression và 6/6 nhóm kiểm thử độc lập, 0 lỗi production chặn nghiệm thu. 16 phép đối chiếu corpus khớp IDs và điểm tuyệt đối. Ba truy vấn hybrid Qdrant local khớp từng kênh và top 20 RRF với bản SQLite. Tổng BM25 còn 0,41–0,61 giây. Mở session khoảng 35–39 giây, nên dùng một session xuyên nhiều truy vấn. Peak working set Python khoảng 523 MiB. Dense exact search và kiểm vector hiện chiếm phần lớn latency. Xem `pipeline_v2/reviews/m3_sparse_ag_review_v1/`.

## Tài sản và fingerprint hiện hành

| Tài sản | Đường dẫn hoặc giá trị |
|---|---|
| Raw train | `data/task1_train_files_2026/cases/` |
| Nhãn evaluator | `data/task1_train_files_2026/clean_task1_train_labels_2026.json` |
| M0 / M1 | `pipeline_v2/artifacts/m0_20261105_v2/`, `m1_20261105_v2/` |
| Navigation | `pipeline_v2/artifacts/m2_navigation_20261106_v3/` |
| Passages | `pipeline_v2/artifacts/m2_passages_20261106_v1/` |
| Full run | `pipeline_v2/artifacts/m3_full_train_20261108_v1/` |
| Sparse | `pipeline_v2/artifacts/m3_sparse_20261110_v1/`, 403.896.521 sealed bytes |
| Compatibility chain | `m3_pilot_20261106_l4_v1/`, `m3_opt_v2_index_20261108_v1/`, `m3_opt_v2_compat_20261108_v1/` dưới `pipeline_v2/artifacts/` |
| Full verify receipt | `pipeline_v2/reviews/m3_full_ag_review_v1/step5_verify_stdout.json` |
| Full collection | `coliee_m3_full_ef2f4d6950a5b9fd` |
| Qdrant | Docker local `qdrant/qdrant:v1.20.0`, REST `http://127.0.0.1:6333` |
| Modal app / class | `coliee-pipeline-v2-embed-m3-opt-v2` / `Embedder`, GPU L4 |
| Embedding | `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`, 2560-dim normalized FP32 output, BF16 weights |
| Tokenizer assets | `pipeline_v2/vendor/qwen3_embedding_4b_tokenizer/5cf2132abc99cad020ac570b19d031efec650f2b/` |

Các hash dùng đối chiếu, không sửa để vượt guard.

```text
accepted M2 seal
0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6
full implementation aggregate
e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503
sparse implementation aggregate
dd4eeb17401cbda28f9a14d7f9300fffde3765397e94e9bfe775385c7f2e5c7e
full manifest SHA-256
7bdf2bb5dda4b324147f5332f4c4a0ed95b15a953b2d3c40fe9f184ca74d45b0
full lexical.sqlite3 SHA-256
6ad1f818618bd6d4d66e0b89c3b06a5bc033da4ac19c86030859fdf9b8bc03fa
full verify receipt SHA-256
b841927b07e001435779a3575e3abccfd0f564e81680e63b801f39049b0ccd08
```

Full cache gồm 6.496 cặp `.npz`/`.json` trong `vectors/`, tổng 4.466.141.805 bytes. `lexical.sqlite3` là 4.357.505.024 bytes. Giữ ledger, invocations, receipts, manifests và seals cùng run. Code full phụ thuộc cả optimization/pilot readers và source/navigation/passages. Giữ nguyên modules/config đã bind hash khi thêm module mới. Sửa byte của code đã khóa có thể làm chain từ chối mở.

## Đợt dọn repo và Git

Nhánh bàn giao là `codex/pipeline-v2-handoff`, sau đó cập nhật `main` tới cùng commit. Dọn phần triển khai/thử nghiệm cũ ở `knowledge_base`, `research_bundle`, `kos_sample`, root `tests`, các `author_batch_*.py`, hướng dẫn bàn giao cũ và IDE files. Giữ 11 exposure manifests tại đường dẫn gốc trong `knowledge_base/pipeline_v1/` vì M0 vẫn bind chúng. Ba tài liệu nghiên cứu liên quan được đưa sang `pipeline_v2/docs/research/`. Giữ toàn bộ code/config/artifact/review thuộc V2 và `.codex` điều phối.

Các artifact V2 khoảng 14,3 GB giữ local và Git ignore, cùng `data/`, môi trường và secrets. Code, tài liệu, review và tokenizer vendor được đưa vào Git. `.gitattributes` giữ nguyên bytes dưới `pipeline_v2/` để bảo toàn hashes. Sau cleanup, Main đã chạy `unittest discover` đạt 204/204 tests trong 19,926 giây. Đối chiếu commit/receipt cuối của nhánh để biết kết quả kiểm bổ sung.

## Chuẩn bị máy mới

Clone nhánh bàn giao hoặc `main` đã cập nhật. Dùng checkout ngắn trên Windows và chạy từ repo root.

```powershell
git clone -c core.longpaths=true https://github.com/ducvan1909/coliee-case-retrieval.git
Set-Location coliee-case-retrieval
git rev-parse --show-toplevel
git status --short
py -3.12 -m venv .venv
& .venv/Scripts/python.exe -m pip install -r pipeline_v2/requirements-m3-local.txt
```

Requirements local pin NumPy 2.4.4, Modal 1.5.3, requests 2.33.1 và tokenizers 0.22.2. Torch/Transformers chạy trong image Modal đã khóa. Tạo lại `.venv` trên máy mới.

Git không chứa toàn bộ runtime lớn và secrets. Chuyển riêng các thư mục sau từ máy cũ, bảo toàn đường dẫn tương đối và raw bytes.

1. `data/` chuẩn, đặc biệt raw train và nhãn evaluator.
2. Toàn bộ `pipeline_v2/artifacts/` để giữ chain M0→M3, pilot compatibility, cache và accounting. Không chỉ copy sparse index.
3. Kiểm đủ tokenizer assets trong `pipeline_v2/vendor/` theo lock sau clone.
4. Kiểm đủ evidence/review được code dẫn chiếu, đặc biệt full verify receipt.
5. Dữ liệu Qdrant Docker chuyển riêng bằng snapshot/backup nhất quán. Named volumes là `coliee_pipeline_v2_qdrant_storage_v1` và `coliee_pipeline_v2_qdrant_snapshots_v1`. Dừng writer trước backup, kiểm restore trên máy mới.

Compose mới tạo server/volume trống. Có thể nạp lại collection bằng quy trình cache-only bên dưới. Đây là script vận hành dùng các adapter hiện có, chưa có CLI restore riêng. Trước hybrid thật phải khôi phục collection rồi verify so cache. Không chạy `m3_full run` để thử khi chưa kiểm đầy đủ cache, vì đường đó có thể gọi model cho batch thiếu cache. Helper restore pilot có giới hạn RAM khi áp cho full corpus, xem M3_FULL.md.

Nếu cần auth Modal, copy `pipeline_v2/.env.example` thành `pipeline_v2/.env` rồi nhập credential local, hoặc dùng SDK profile đã đăng nhập. Không commit `.env` hay in token. Tên app hiện hành lấy từ `configs/m3_full.json` và `m3_opt_v2.json`; tài liệu pilot lịch sử có app khác.

Runtime chính dùng repo root tương đối. Đường dẫn `E:/...` trong receipts/script review là lịch sử máy đo. Không chỉnh receipts, seals hoặc raw để đổi ổ đĩa. Nếu script review hardcode đường dẫn, tạo script review mới dùng root mới và ghi rõ. Guard báo drift sau copy thì kiểm thiếu file, line endings và SHA-256 trước khi tiếp tục.

## Kiểm tra sau chuyển máy

Fixture tests chạy trước, không cần Docker/Modal.

```powershell
& .venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_m3_sparse_index pipeline_v2.tests.test_m3_lexical_reader pipeline_v2.tests.test_m3_hybrid_dense pipeline_v2.tests.test_m3_hybrid_fusion -v
& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse --help
```

Sau khi copy đủ raw/artifacts/vendor, thử lexical local. Mở session kiểm snapshot nên có thể mất hàng chục giây.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse search --channel passage --query "standard of review" --query-case 095448.txt --limit 100 --unique-cases
```

Sau khi Docker Engine chạy và collection đã restore, kiểm schema/count rồi diagnostic dùng vector cache. Các lệnh này không cần Modal.

```powershell
docker compose -p coliee-pipeline-v2 -f pipeline_v2/deployments/qdrant/compose.yaml up -d
Invoke-RestMethod -Uri http://127.0.0.1:6333/collections/coliee_m3_full_ef2f4d6950a5b9fd
& .venv/Scripts/python.exe -m pipeline_v2.m3_sparse diagnostic-hybrid --query "standard of review" --query-case 095448.txt --passage-id 095448:88b488d43fde1389756a8dd7
```

Full DB verification kiểm đủ 415.693 vectors/payload/IDs, mất khoảng 25 phút trên máy cũ. Chạy một lần sau restore, lưu stdout và exit code vào review mới.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_full verify --run-dir pipeline_v2/artifacts/m3_full_train_20261108_v1
```

## Khôi phục chi tiết từ artifacts local và cache đặt ở root

Quy ước trên máy mới là đặt vector cache tại `cache/vectors/` ở root repo. Nếu người dùng đặt tên khác, Codex hỏi tên hoặc kiểm inventory rồi sửa đường dẫn nguồn trong lệnh copy. Runtime vẫn đọc tại `pipeline_v2/artifacts/m3_full_train_20261108_v1/vectors/`. Chuyển cache về vị trí runtime bằng copy bảo toàn bytes, giữ bản nguồn ở root cho đến khi nghiệm thu xong. `cache/` và `restore_input/` đã được Git ignore.

### Chuẩn bị gói từ máy cũ

Dừng các writer trước khi copy, gồm full ingestion, benchmark có ghi ledger và mọi tiến trình đang sửa artifact. Nếu có SQLite WAL, để ứng dụng đóng kết nối bình thường trước khi copy toàn thư mục. Giữ cả file phụ còn tồn tại, tránh lấy riêng DB đang được ghi.

```text
<repo-moi>/
  cache/
    vectors/                       # 6.496 .npz + 6.496 .json, nguyên tên file
  restore_input/
    artifacts/                     # copy cây pipeline_v2/artifacts từ máy cũ
      m0_20261105_v2/
      m1_20261105_v2/
      m2_navigation_20261106_v3/
      m2_passages_20261106_v1/
      m3_pilot_20261106_l4_v1/
      m3_opt_v2_index_20261108_v1/
      m3_opt_v2_compat_20261108_v1/
      m3_full_train_20261108_v1/     # giữ manifest, seal, lexical, ledger, execution state...
      m3_sparse_20261110_v1/
      ...                          # giữ các checkpoint khác nếu chuyển toàn bộ
  data/                            # dữ liệu chuẩn copy riêng
```

Nếu đã tách `vectors/` sang `cache/vectors/`, có thể bỏ bản vector trùng trong gói `restore_input/artifacts/` để giảm dung lượng vận chuyển. Giữ mọi file khác của full run, đặc biệt `manifest.json`, `seal.json`, `lexical.sqlite3`, `execution_state.json`, `ledger.sqlite3` và lịch sử invocations/receipts. Giữ chain pilot compatibility trong bảng phía trên. Clone Git đã chứa vendor tokenizer, review receipt và 11 exposure manifests.

Kiểm trên máy cũ ngày 10/11/2026 xác nhận cache còn 6.496 `.npz` tổng 4.422.922.572 bytes và 6.496 `.json` tổng 43.219.233 bytes. Tổng 4.466.141.805 bytes, khoảng 4,16 GiB. Ledger có 6.496 committed batches, 6.496 success attempts và 1 started attempt lịch sử. Số lượng là kiểm inventory, bước kiểm SHA-256 theo schedule ở dưới mới xác nhận nội dung.

Chỉ vector cache không đủ tái tạo nguyên checkpoint hiện tại. Các manifest, metadata/schedule, upstream source bundles và compatibility receipts cần được chuyển cùng. Nếu thiếu, Codex liệt kê phần thiếu và dựng revision mới có nghiệm thu khi được giao. Không tự tạo receipt thành công, sửa seal hoặc chỉnh hash để nối snapshot mới vào lịch sử cũ.

### Copy về vị trí runtime

Chạy PowerShell từ root repo sau khi clone và cài môi trường. Ví dụ này yêu cầu đích artifacts mới, tránh trộn với một run đã có.

```powershell
$artifactSource = Join-Path (Get-Location) 'restore_input/artifacts'
$artifactTarget = Join-Path (Get-Location) 'pipeline_v2/artifacts'
if (!(Test-Path -LiteralPath $artifactSource -PathType Container)) { throw 'Thieu goi artifacts nguon' }
if (Test-Path -LiteralPath $artifactTarget) { throw 'Dich da ton tai. Kiem inventory/hash truoc khi merge, khong ghi de tu dong.' }
robocopy $artifactSource $artifactTarget /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
if ($LASTEXITCODE -ge 8) { throw 'Copy artifacts that bai' }

$vectorSource = Join-Path (Get-Location) 'cache/vectors'
$vectorTarget = Join-Path $artifactTarget 'm3_full_train_20261108_v1/vectors'
if (!(Test-Path -LiteralPath $vectorSource -PathType Container)) { throw 'Thieu cache/vectors' }
if (!(Test-Path -LiteralPath $vectorTarget)) {
    robocopy $vectorSource $vectorTarget /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
    if ($LASTEXITCODE -ge 8) { throw 'Copy vectors that bai' }
} else {
    Write-Output 'Dich vectors da co tu goi artifacts. Kiem cache theo schedule o buoc tiep theo.'
}
```

Nếu artifacts đã có local trên máy mới, bỏ bước copy artifacts. Chỉ thêm `vectors/` khi đích chưa có. Khi đích chứa cache dở, giữ evidence và đối chiếu hash từng file trước khi bổ sung từ nguồn. Không dùng `/MIR`, không xóa run hoặc ledger để xử lý lỗi copy.

### Kiểm đầy đủ cache trước khi ghi Qdrant

Đoạn sau chỉ đọc snapshot và cache. Nó kiểm toàn bộ schedule, SHA-256 của từng `.npz`, metadata, IDs, input hashes, fingerprint, shape và vector norms qua adapter đã có. Thiếu/hỏng bất kỳ batch nào sẽ dừng bằng lỗi. Chạy từ root repo, chờ hoàn tất, giữ stdout và exit code nếu cần báo cáo chuyển máy.

```powershell
@'
from pathlib import Path
from pipeline_v2.full_corpus.runner import load_plan, batches
from pipeline_v2.full_corpus.storage import ReadonlyCache

root, run, manifest, lexical = load_plan(
    Path.cwd(), 'pipeline_v2/artifacts/m3_full_train_20261108_v1')
try:
    cache = ReadonlyCache(run, manifest['embedding_fingerprint'],
                          manifest['profile']['embedding']['dimensions'])
    batch_count = point_count = 0
    for number, docs in batches(lexical):
        values = cache.get_batch([p['passage_id'] for p in docs],
                                 [p['exact_input_sha256'] for p in docs])
        if values is None:
            raise RuntimeError(f'Missing cache batch {number}')
        batch_count += 1
        point_count += len(docs)
    if (batch_count, point_count) != (6496, 415693):
        raise RuntimeError('Unexpected full cache coverage')
    print({'status': 'PASS', 'batches': batch_count,
           'points': point_count, 'model_requests': 0})
finally:
    lexical.close()
'@ | & .venv/Scripts/python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Cache audit that bai. Dung khoi phuc DB.' }
```

`load_plan` cũng kiểm source hashes, full seal và compatibility chain. Vì vậy lỗi thiếu M0/M1/M2/pilot assets phải được giải quyết trước khi dùng full cache. Giữ nguyên đường dẫn tương đối khi đổi ổ hoặc tên thư mục checkout.

### Khởi động Qdrant và nạp lại từ cache

Mở Docker Desktop Linux Engine. Cấu hình Compose đã có image Qdrant 1.20.0, cổng loopback 6333/6334 và hai named volumes. Chạy `docker compose ... up -d` như mục trên, sau đó kiểm API. Nếu dùng DB backup đã restore và full verify PASS thì bỏ bước nạp lại này.

Script bên dưới chỉ dùng `ReadonlyCache`, `FullQdrant` và các hàm kiểm snapshot. Nó kiểm hết cache trước khi tạo/sửa collection, rồi upsert theo batch 64. Nó không khởi tạo embedder hoặc gọi hàm inference. `run_lock` tránh writer cùng run của repo. Dừng mọi writer DB khác trong thời gian restore. Script tạo lock DB nếu chưa có, dữ liệu vector và lịch sử usage được đọc nguyên trạng. Log tiến độ ở console, nếu bị ngắt có thể chạy lại để bỏ qua các batch đã khớp DB.

```powershell
@'
from pathlib import Path
from pipeline_v2.full_corpus.runner import (
    load_plan, batches, make_store, guard, verify_batches)
from pipeline_v2.full_corpus.storage import ReadonlyCache
from pipeline_v2.retrieval.cache import run_lock

root, run, manifest, lexical = load_plan(
    Path.cwd(), 'pipeline_v2/artifacts/m3_full_train_20261108_v1')
try:
    cache = ReadonlyCache(run, manifest['embedding_fingerprint'],
                          manifest['profile']['embedding']['dimensions'])
    with run_lock(run):
        count = 0
        for number, docs in batches(lexical):
            values = cache.get_batch([p['passage_id'] for p in docs],
                                     [p['exact_input_sha256'] for p in docs])
            if values is None:
                raise RuntimeError(f'Missing cache batch {number}')
            count += len(docs)
        if count != manifest['passages']:
            raise RuntimeError('Cache coverage differs')
        guard(root, manifest)
        store = make_store(manifest)
        if store.server_info()['version'] != manifest['profile']['qdrant']['version']:
            raise RuntimeError('Qdrant version differs')
        store.ensure()
        store.validate_existing(lexical)
        if store.count() > manifest['passages']:
            raise RuntimeError('Unexpected collection count')
        upserted = skipped = 0
        for number, docs in batches(lexical):
            guard(root, manifest)
            values = cache.get_batch([p['passage_id'] for p in docs],
                                     [p['exact_input_sha256'] for p in docs])
            if values is None:
                raise RuntimeError(f'Cache disappeared at batch {number}')
            if store.matches(docs, values):
                skipped += 1
            else:
                store.upsert(docs, values)
                upserted += 1
            if number % 100 == 0:
                print({'batch': number, 'upserted': upserted,
                       'skipped': skipped, 'model_requests': 0}, flush=True)
        guard(root, manifest)
        result = verify_batches(lexical, cache, store, manifest)
        print({**result, 'upserted_batches': upserted,
               'skipped_batches': skipped, 'model_requests': 0}, flush=True)
finally:
    lexical.close()
'@ | & .venv/Scripts/python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Restore Qdrant that bai. Giu log va resume sau khi sua nguyen nhan.' }
```

Nếu DB có ID/payload/vector khác snapshot, adapter sẽ báo lỗi. Giữ nguyên collection để kiểm tra, không xóa tự động. Cache thiếu/hỏng phải lấy lại file từ máy cũ hoặc bản backup. Một lần restore có thể mất nhiều phút đến hàng chục phút, riêng full verify trước đây khoảng 25 phút. Tránh để Windows sleep khi chạy.

Đây là đoạn hướng dẫn mới, đã kiểm cú pháp Python nhưng chưa chạy restore thật trong đợt cập nhật tài liệu. Codex trên máy mới cần thử một collection tạm bằng fixture/cache nhỏ trước khi chạy toàn bộ nếu chuyển thành tool production. Sau restore, chạy CLI `m3_full verify` và diagnostic hybrid ở mục kiểm tra sau chuyển máy, lưu evidence mới. Chỉ chốt phục hồi khi full verify PASS đủ 415.693 points và diagnostic có provenance đúng.

### Khi thiếu artifact ngoài vector cache

M0, M1, navigation, passages và lexical/sparse indices có code dựng local. Tuy nhiên rebuild có thể thay manifest, elapsed time, collection identity và seals, làm chain hiện tại từ chối mở. Dựng vào output mới, kiểm lại theo milestone và tạo revision/config/receipt mới khi cần. Chỉ riêng cache gốc không phục hồi được lịch sử ledger hoặc chứng nhận compatibility bị mất. Nếu mất cache vector thì việc tạo lại vector cần Modal và một run trả phí được người dùng/AG thực hiện.

Ưu tiên lấy đủ artifact đã có trên máy cũ, chuyển cache vào root như quy ước, copy về vị trí runtime và kiểm hash. Giữ gói nguồn cho đến khi full cache audit, DB verify và diagnostic hoàn tất.

## Việc Codex tiếp tục làm

Đọc `docs/plan/M3_FULL_SEARCH.md`, `reviews/m3_full_search_plan_ag_review_v1/` và review sparse. Draft full-search còn mô tả lựa chọn đã điều chỉnh trong code, như dense một request exact top 4.096. Chốt decision delta trước triển khai phần còn lại, giữ policy các kênh đã nghiệm thu.

1. `search_case` và query-reading helpers `case_map`/`case_anchors`. Tìm trong án đã biết, cho phép đọc query case, trả handles/preview/coverage có provenance.
2. `search_phrase` trên raw stream xuyên ranh giới chunk. Khóa matching mode, Unicode casefold mapping, char↔UTF-8 byte offsets, repeated matches và cursor. Mọi hit round-trip đúng raw bytes.
3. `search_identity` cho tên/citation quan sát được, kèm raw source spans và method version. Giữ rõ lead chưa xác minh danh tính.
4. `open_source` đọc M2 JSON đã seal, mở full parent + neighbors, dedup raw intervals, byte budget/pagination và requested/delivered/pending. Tránh tokenize/rebuild cả case chỉ để mở hit. Agent token budget áp ở M4.
5. AG kiểm local các công cụ mới. Codex chuẩn bị manifest/lệnh cho một query embedding thật qua Modal bằng `m3_sparse search-hybrid`; người dùng/AG chạy, lưu latency/usage/errors, Main nghiệm thu để chốt M3.

Khi tích hợp harness, giữ session xuyên nhiều tools. Guard hiện lặp khoảng 7 lần mỗi hybrid query, có thể gom tại biên request nếu tests vẫn bắt drift/invalidation. `revalidate()` mở session thứ hai tạm thời, cần tính thêm catalog heap khi chạy nhiều worker. AG đã ghi hai mục này non-blocking.

Sau M3 mới triển khai M4 rồi M5–M7 theo plan. Chưa tự chốt controller model/tokenizer/budget, threshold selector, reranker, approximate dense policy hoặc tune trên holdout. Giữ request/token/latency cả lỗi và retry. Báo đúng phạm vi nghiệm thu engineering và đánh giá nhãn.

## Prompt mở đầu cho Codex mới

> Đọc CODEX_HANDOFF.md và AGENTS.md. Kiểm checkout, commit, runtime assets và fingerprints thực tế. Tôi đặt vector cache ở cache/vectors/ tại root repo. Dùng mục khôi phục chi tiết để copy artifacts/cache về đúng vị trí, kiểm đủ cache và phục hồi Qdrant local bằng cache-only khi DB chưa có. Kiểm script bằng collection tạm trước khi dùng full, ghi báo cáo restore riêng và giữ nguyên ledger lịch sử. Báo phần đã phục hồi, phần thiếu và tiến độ M0–M7. Sau đó chốt decision delta của M3 full-search rồi triển khai search_case/case_map/case_anchors, phrase/identity và open_source theo thứ tự phụ thuộc. Giữ modules/config/artifacts đã bind hash, thêm revision/module mới khi cần. Dùng implementer và tester theo AGENTS.md. Chuẩn bị lệnh Modal để tôi hoặc AG chạy. Thiếu data/DB chỉ chặn kiểm tích hợp tương ứng, vẫn tiếp tục code và fixture tests làm độc lập được.
