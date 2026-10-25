# Đánh giá độc lập Kế hoạch 01

## Kết luận

**FAIL** — artifact hiện tại của KOS-5 và schema fixture đang hợp lệ, nhưng cổng Plan 01 có thể báo PASS cho các trạng thái vi phạm contract. Vì vậy chưa đủ điều kiện chuyển sang đánh giá độc lập Kế hoạch 02.

Phân biệt kết quả:

- **Schema/contract artifact hiện tại:** PASS có giới hạn; Draft 2020-12 schema và fixture hiện tại validate được.
- **Run completion:** PASS; validator gốc chạy xong và báo `PLAN01 PASS`.
- **Độ tin cậy của transition gate:** FAIL; fault injection cho thấy false PASS.
- **Semantic correctness / AU / retrieval:** không đánh giá và không được suy ra từ các kết quả trên.

## Phạm vi và môi trường

- Checkout: `G:\Git\coliee-case-retrieval`
- Branch/commit: `main` / `5fbf5652e2048328f41d37676177927457c95050`
- Ngày đánh giá: `2026-10-03` (Asia/Saigon)
- Python: `3.10.0`; jsonschema: `4.26.0`; Windows build `22631`
- Workload: đúng KOS-5 (`013009`, `013948`, `011904`, `045155`, `099980`)
- Raw source là nguồn kiểm tra hash/length; `G:\Legal-AI\kos_sample` chỉ dùng audit inventory, không dùng làm gold.
- Không gọi LLM/inference trả phí, Modal, development, held-out hoặc toàn corpus.
- Không sửa implementation hay report gốc.

## Lệnh đã chạy

```powershell
python knowledge_base/pipeline_v1/scripts/validate_plan01.py --kos-root "G:\Legal-AI\kos_sample" --report "knowledge_base\pipeline_v1\evaluation\runtime\plan01_gate.json"
python -m unittest discover -s knowledge_base/pipeline_v1/tests -v
python -m unittest knowledge_base.pipeline_v1.evaluation.test_plan01_independent -v
```

## Kết quả dương tính

1. Validator gốc hoàn tất và báo PASS: 5 case, 61 KOS artifact files.
2. 14/14 test gốc của Plan 01–02 pass. Các test Plan 02 chỉ được ghi nhận là test gốc đã chạy; không phải đánh giá độc lập Plan 02.
3. Kiểm tra độc lập xác nhận 5 raw source hiện tại khớp tuyệt đối SHA-256, byte length và decoded character length trong `calibration_manifest.v1.json`.
4. Annotation schema và fixture hiện tại hợp lệ theo Draft 2020-12.

## Phát hiện độc lập

### P01-F01 — High — Plan 01 gate không xác minh raw source/hash

Contract yêu cầu workload đầu tiên dùng raw source trong `calibration_manifest.v1.json`, xác minh hash trước khi chạy, và transition gate phải chứng minh source của 5 case khớp manifest. Nhưng `build_report()` chỉ nạp `selected_kos_manifest`, split registry, annotation schema và hard-case catalog; report không có input/check cho calibration raw-source manifest.

Reproduction: `test_plan01_gate_must_report_raw_source_hash_check` thất bại vì report không có `inputs.calibration_manifest` hoặc `checks.raw_source_hashes`.

Tác động: Plan 01 có thể báo PASS khi một raw source đã đổi hoặc manifest raw-source sai. Plan 02 có preflight riêng không sửa được việc Plan 01 transition gate đã sai contract.

Đề xuất sửa: cho Plan 01 validator nhận `--repo-root`, nạp và khóa `calibration_manifest.v1.json`, kiểm tra đúng 5 case/path/hash/byte/char trước khi PASS; report phải ghi từng source và kết quả.

### P01-F02 — High — Split chỉ được đếm, không được tái lập hoặc xác thực provenance

`validate_split_registry()` chỉ tạo ba tập role, kiểm tra số lượng và overlap. Nó không tái chạy thuật toán band/rank đã khóa, không kiểm tra case ID, existence/provenance, và không thể kiểm tra duplicate source hash giữa locked sets.

Reproduction:

- thay một development case bằng `888888`, giữ nguyên count và không overlap: validator trả không lỗi;
- thay bằng `not-a-case`: validator vẫn trả không lỗi.

Tác động: registry bị sửa hoặc không được sinh từ policy vẫn có thể PASS, trái điều kiện “split tái lập” và mục tiêu leakage/trùng case.

Đề xuất sửa: tách hai mode. Mode KOS-only chỉ được gọi là static registry sanity check. Transition gate phải có phép tái lập registry từ metadata snapshot đã khóa hoặc một versioned selection manifest/provenance digest đủ để kiểm chứng mà không mở label; đồng thời validate format/existence và duplicate source hash theo policy.

### P01-F03 — Medium — Schema gate chấp nhận JSON Schema không hợp lệ

Fault injection đổi `$defs.spanRef.type` thành một JSON Schema type không tồn tại. `Draft202012Validator.check_schema()` từ chối, nhưng `validate_annotation_schema()` trả danh sách lỗi rỗng.

Tác động: CLI gate chính có thể báo PASS cho contract không thể dùng. Test gốc hiện tại giảm rủi ro đối với artifact hiện tại, nhưng không làm validator CLI tự đủ.

Đề xuất sửa: validate metaschema và validate fixture ngay trong report gate, hoặc hợp nhất rõ hai lệnh thành một gate duy nhất có report.

### P01-F04 — Medium — Mandatory hard-case coverage chỉ được kiểm tra bằng count/class

Fault injection xóa `struct-bracket-year-vs-marker` rồi thêm placeholder để giữ count/class. `validate_hard_cases()` vẫn PASS.

Tác động: một tình huống bắt buộc có thể biến mất mà transition gate không phát hiện.

Đề xuất sửa: khóa tập `situation_id` bắt buộc và validate shape, candidate case thuộc KOS-5, `required_labels`, status `annotation_queue_not_gold` và tuyên bố non-gold.

## Kết quả kiểm thử độc lập

- Tổng: 7
- PASS: 2
- FAIL: 5
- PASS xác nhận artifact hiện tại; 5 FAIL là negative/fault-injection chứng minh validator chấp nhận trạng thái sai.

File test: `knowledge_base/pipeline_v1/evaluation/test_plan01_independent.py`.

## Giới hạn

- Không đánh giá đúng/sai ngữ nghĩa của AU, NN, Issue hoặc KOS artifact.
- Không đo parser, retrieval, recall, precision hoặc generalization.
- Không đọc/chạy development hay held-out để tránh vượt phạm vi. Vì vậy lỗi split được chứng minh bằng contract mutation, không bằng resampling corpus.
- Không thay đổi implementation để kiểm tra fix.

## Điều kiện cho phép chuyển bước

Chỉ cho phép chuyển sang đánh giá độc lập Plan 02 sau khi:

1. Plan 01 gate tự xác minh raw-source manifest/hash của KOS-5;
2. split provenance/reproducibility được kiểm chứng theo contract, không chỉ count/overlap;
3. malformed registry và invalid JSON Schema bị từ chối;
4. mandatory hard-case IDs bị khóa và negative tests tương ứng pass;
5. validator gốc, toàn bộ test gốc và test độc lập đều pass, với report mới vẫn ghi rõ không có semantic/retrieval claim.

---

## Retest sau bản sửa — 2026-10-03 15:53 +07:00

### Bảo toàn evaluation baseline

Ba file baseline được kiểm tra trước khi retest vẫn giữ nguyên byte length đã ghi ở lượt đầu, không có dấu hiệu bị agent triển khai sửa:

| File | Bytes | SHA-256 tại đầu retest |
|---|---:|---|
| `plan01_independent_evaluation.md` | 7004 | `88427e66b752bd62c241ba2f1f3df700e2644cbed86d267e56d7156c0159960b` |
| `plan01_independent_summary.json` | 2863 | `86b2ca3d676fc554d62b1780f3052198a09443f56906ee3efcfb53785c0af08a` |
| `test_plan01_independent.py` | 4476 | `86659a3741c1bdb99087aaaaf6d8cef1b832dfcca27b99f03607523d9aaf76d9` |

Agent triển khai thay đổi validator, regression tests, split registry và README; không thay các file baseline trên.

### Xác minh các sửa đổi P01-F01–F04

- **P01-F01:** FIX VERIFIED — report mới có `calibration_manifest` và `raw_source_hashes`; CLI xác minh 5 raw source.
- **P01-F02:** FIX VERIFIED — validator kiểm tra format, assignment digest, tái lập policy, existence và duplicate source hash.
- **P01-F03:** FIX VERIFIED — metaschema Draft 2020-12 và fixture được kiểm tra trong gate.
- **P01-F04:** FIX VERIFIED — mandatory situation IDs, class, shape, KOS-5 candidate và non-gold rules được kiểm tra.

Kết quả chạy lại:

- Plan 01 CLI: PASS.
- Test gốc: 18/18 PASS.
- 7 test độc lập ban đầu: 7/7 PASS.

### P01-RF01 — Medium — malformed non-string case ID làm validator crash

Fault injection mới thay một development case ID bằng số nguyên `123`. Validator nhận diện được ID malformed ở bước đầu, nhưng sau đó vẫn đưa tập chứa cả `str` và `int` vào `sorted(case_ids)`. Python ném:

```text
TypeError: '<' not supported between instances of 'int' and 'str'
```

Reproduction:

```powershell
python -m unittest discover -s knowledge_base/pipeline_v1/evaluation -p "test_*.py" -v
```

Kết quả toàn bộ test độc lập retest: 8 test, 7 PASS, 1 FAIL. Test mới nằm tại `evaluation/test_plan01_retest.py`.

Tác động: input registry sai kiểu không tạo được report JSON và exit FAIL có kiểm soát; gate crash giữa chừng. Điều này vi phạm vai trò validator contract và làm pipeline/CI mất bằng chứng lỗi có cấu trúc.

Đề xuất sửa: sau shape/type validation, chỉ đưa case ID là chuỗi sáu chữ số vào phase existence/hash; hoặc normalize danh sách valid IDs riêng trước khi sort. Mọi malformed input phải trả `errors` và `details.status=fail`, không ném exception ngoài dự kiến.

### Kết luận retest

**FAIL** — bốn defect ban đầu đã được sửa, nhưng P01-RF01 khiến bộ kiểm thử độc lập chưa xanh. Plan 02 tiếp tục **BLOCKED** và không được đánh giá độc lập ở lượt này.

Điều kiện chuyển bước cập nhật: sửa P01-RF01, chạy lại CLI + 18 test gốc + toàn bộ test dưới `evaluation/`, và tất cả phải PASS.

---

## Retest P01-RF01 — 2026-10-03 16:03 +07:00

**PASS** — trạng thái này thay thế kết luận FAIL của retest trước, nhưng lịch sử FAIL được giữ nguyên ở trên.

Xác minh trực tiếp với development case ID kiểu số nguyên `123`:

- validator không crash;
- trả `details.status=fail`;
- trả ba lỗi có cấu trúc: malformed case ID, assignment provenance mismatch và assignment không tái lập.

Kết quả gate đầy đủ:

- Plan 01 CLI: PASS;
- test gốc: 19/19 PASS;
- toàn bộ test độc lập Plan 01: 8/8 PASS.

P01-RF01: **FIX VERIFIED**. Plan 01 đạt gate độc lập và cho phép bắt đầu đánh giá Plan 02. PASS này chỉ xác nhận manifest/split/schema/hard-case contract; không xác nhận semantic correctness, AU quality hoặc retrieval quality.

