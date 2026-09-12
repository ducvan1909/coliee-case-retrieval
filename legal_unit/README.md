# LegalUnit

Tạo các `LegalUnit` cấu trúc ban đầu bằng rule local
(`structural-boundaries-v5.1`).

Chạy mọi lệnh từ thư mục gốc `coliee-case-retrieval`. Chi tiết output xem
[`SCHEMA.md`](SCHEMA.md).

## Chạy development

Chọn 20 query và tạo manifest:

```powershell
python -m legal_unit.cli select `
  --train-root data/task1_train_files_2026 `
  --samples-dir legal_unit/samples
```

Phân đoạn và kiểm tra artifact:

```powershell
python -m legal_unit.cli segment `
  --samples-dir legal_unit/samples `
  --outputs-dir legal_unit/outputs/development

python -m legal_unit.cli validate `
  --samples-dir legal_unit/samples `
  --artifact legal_unit/outputs/development/legal_unit_candidates.jsonl
```

## Chạy validation 

Tập validation loại các case đã có trong development:

```powershell
python -m legal_unit.cli select `
  --train-root data/task1_train_files_2026 `
  --samples-dir legal_unit/samples_validation `
  --split validation `
  --exclude-manifest legal_unit/samples/manifest.json

python -m legal_unit.cli segment `
  --samples-dir legal_unit/samples_validation `
  --outputs-dir legal_unit/outputs/validation

python -m legal_unit.cli validate `
  --samples-dir legal_unit/samples_validation `
  --artifact legal_unit/outputs/validation/legal_unit_candidates.jsonl
```

## Output chính

- `legal_unit_candidates.jsonl`: các unit code-provisional.
- `boundary_decisions.jsonl`: quyết định `split`, `keep` hoặc `defer`.
- `review_queue.jsonl`: vùng cần đọc lại.
- `report.json` và `run_manifest.json`: kết quả kiểm tra, version và hash.
- `boundary_review.md` và `debug/`: nội dung hỗ trợ kiểm tra biên theo nguồn.

Các thư mục `samples/`, `samples_validation/` và `outputs/` do code sinh ra không được commit.
