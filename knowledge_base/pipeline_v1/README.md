# Pipeline V1 — Source/AU và Mốc 1 so sánh KOS

Luồng triển khai nhanh mới: [milestone1/README.md](milestone1/README.md).
Manifest source-complete KOS-5 có 436 request, riêng với manifest pilot 10 target.
Module `milestone1` bổ sung build/preflight, runtime dùng compact jobs/cache;
`kos_comparison` tạo JSON/HTML đối chiếu tham khảo sau extraction. Chưa chạy full
436 request trong đợt triển khai local; protocol và source coverage không thay
thế ngữ nghĩa AU. Kế hoạch hai mốc: [13_fast_kos_comparison_plan.md](../design/pipeline_redesign_lynx/13_fast_kos_comparison_plan.md).

Kế hoạch 10 có zero-shot adapter cho Dedicated Modal endpoint ở `au_baseline/`.
`offline-run` vẫn chỉ dùng mock. Chỉ `probe --execute --max-requests 1` mới gọi provider;
`paired-run` đòi receipt probe thành công và cap request rõ ràng. Mọi provider output,
kể cả output không nhận được/truncated/vi phạm contract, được checkpoint atomically theo
fingerprint source/region/prompt/schema/model/caps; failure được biểu diễn `unresolved`,
không phải `hard_negative`. Artifact giữ `evaluation_against=model_silver` và không là
bằng chứng human gold, semantic quality hay retrieval quality.
`PLX_ENABLE_THINKING=false` là một phần của request identity/cache và được gửi qua
`chat_template_kwargs`; thay đổi mode này tạo request mới, không reuse output cũ.
Plan 10 giữ baseline output cap 1200 (`PLX_BASELINE_OUTPUT_TOKENS`) dưới hard endpoint
ceiling (`PLX_MAX_OUTPUT_TOKENS`, mặc định 2400). Chỉ `finish_reason=length` trong
`warmup-probe` mới có đúng một structural JSON-only retry với
`PLX_STRUCTURAL_REPAIR_OUTPUT_TOKENS`; repair không chạy cho schema/malformed/semantic
failure và không thay đổi paired P2 policy.

`python -m knowledge_base.pipeline_v1.au_baseline warmup --execute` là lane
cold-start source-free riêng, ghi checkpoint dưới `outputs/.../warmup/` và không
đọc hay sửa AU/P2 cache, receipt hoặc metrics. Retry chỉ áp dụng cho transport,
429, 502, 503, 504 theo `PLX_WARMUP_*` caps; output không lưu body, header hay secret.

`warmup-probe --execute` ghép một warmup source-free với đúng một locked P2a probe.
Chỉ một lỗi probe transport/service retryable có thể quay lại warmup trước lần probe thứ hai;
`PLX_WARM_PROBE_MAX_PROBE_ATTEMPTS` mặc định là 2. Ledger riêng ở
`outputs/.../warmup_probe/` lưu receipt đã redaction, không chạy paired workload.

`preflight` là read-only và không cần `--execute`: nó materialize P2a/P2b manifests,
ghi `preflight.json`, và kiểm tra aggregate `PLX_MAX_TOTAL_INPUT_TOKENS`/
`PLX_MAX_TOTAL_OUTPUT_TOKENS`. Hai limit này bắt buộc cho `paired-run`; chúng không
fallback sang per-request `PLX_MAX_OUTPUT_TOKENS`. Paired run không có structural retry:
mỗi `finish_reason=length` được ghi `unresolved` và đếm riêng trong report.

Paired-run chỉ retry lỗi provider có `retryable=true` thuộc HTTP `408/429/5xx` hoặc
transport. Trước đúng một source retry, runner chạy warmup source-free bị chặn bởi
`PLX_WARMUP_*`; `length`, schema/protocol error và lỗi không retryable là terminal.
`PLX_MAX_RECOVERY_CYCLES=1` là quota toàn cục cho cả paired-run: sau khi cycle đã
được dùng, lỗi retryable tiếp theo mở circuit breaker để phần còn lại được
checkpoint `provider_unavailable`, thay vì fan-out lỗi. `PLX_MAX_PROVIDER_ATTEMPTS`
đếm source attempts và warmup riêng với 192 logical locked rows; preflight từ chối
bound không đủ. Mỗi retry archive row cũ vào `attempt_history/`. `COMPLETE` chỉ khi
toàn bộ 192 row là `protocol_verified`; bất kỳ unresolved/truncated/provider failure/
budget stop đều là `INCOMPLETE`. Recovery này không có structural repair trong paired-run.

Kế hoạch 08 bổ sung execution ledger offline, mock provider xác định, cache theo fingerprint, checkpoint nguyên tử, resume, bounded transient retry và dependency-scoped invalidation. Xem `execution_ledger_contract.md`.

Chạy bộ operational scenario trên KOS-5:

```powershell
python -m knowledge_base.pipeline_v1.execution_ledger
```

Terminal chỉ in trạng thái ngắn. Snapshot, JSONL projection, cache và suite manifest được ghi dưới `outputs/plan08_execution_v1/`; report mới nhất ở `reports/plan08_execution_validation.latest.json`.

Lifecycle v2 dùng `current.json` cho build hiện hành và `history/index.json` cùng `archive_record.json` để khóa toàn bộ payload archive bằng path, SHA-256, byte length và artifact type. Archive manifest-only cũ được giữ trong `history/legacy_unsealed/`; phạm vi phát hiện tamper của bản migration chỉ bắt đầu tại thời điểm tạo inventory.

Kế hoạch 09 tạo blank AU annotation packets và workflow human adjudication bằng `python -m knowledge_base.pipeline_v1.au_gold build`. Human gold vẫn ở trạng thái `gold_awaiting_independent_adjudication`. Terra có lane silver riêng (`model_proposed`/`model_adjudicated_silver`); không được giả thành human gold hoặc mở khóa held-out claim. Lane model-silver hiện là `partial_resumable`: 212/369 target đã checkpoint, còn 157 target của `099980`; sample audit độc lập đã phát hiện một lỗi attribution nghiêm trọng nên semantic-silver chưa đạt. Xem `au_annotation_guideline.v1.md`, `plan09_workflow.md`, `reports/plan09_model_silver_progress.latest.json` và `evaluation/plan09_independent_evaluation.md`.

Thư mục này là implementation mới, độc lập với các pipeline V13–V15. Kế hoạch 01 khóa input KOS đã chọn, split và hợp đồng annotation tối thiểu trước khi thay parser hoặc model.

## Phạm vi đã khóa

- Năm case calibration: `013009`, `013948`, `011904`, `045155`, `099980`.
- Input runtime là toàn bộ 61 file dưới năm thư mục `cases/<case_id>` của KOS: 40 file query-side và 21 file candidate-side.
- Calibration chỉ dùng tái hiện lỗi và sửa contract; không phải gold hay holdout xác nhận chất lượng.
- Registry pilot 20 development/40 holdout được tái dựng từ metadata raw corpus bằng policy/salt đã khóa; gate cũng kiểm tra assignment digest, case ID, existence và duplicate source hash trong 65 case khóa.
- Schema annotation biểu diễn được `SourceBlock`, `AuthorityUnit`, attribution, condition/exception/limit và `ContextObligation`.
- Danh mục hard case chỉ là hàng đợi annotation; các candidate kế thừa từ audit cũ không được coi là nhãn đúng.

Không có parser, model, prompt, tuning, retrieval hoặc gán nhãn đầy đủ trong thư mục này.

Ghi chú phạm vi: câu trên mô tả Kế hoạch 01. Kế hoạch 03 hiện bổ sung duy
nhất structural pre-pass deterministic và partition `SourceBlock` exact-span;
không có sentence, AnalysisRegion, LegalUnit, annotation, retrieval hay LLM.

## Kế hoạch 02 — source contract

Kế hoạch 02 dùng raw source của đúng năm case KOS-5 trong `manifests/calibration_manifest.v1.json`. Manifest KOS và report Kế hoạch 01 chỉ là audit gate, không phải source hoặc gold.

## Kế hoạch 03 — structural pre-pass

Hợp đồng, cache/invalidation và ý nghĩa gate nằm tại
`sourceblock_contract.md`. Lệnh chạy chỉ in một dòng trạng thái; kết quả chi tiết
được ghi vào `reports/plan03_structural_validation.latest.json` và audit HTML.

## Kế hoạch 04 — SentenceAtom

Kế hoạch 04 tạo địa chỉ SentenceAtom exact-span bên trong SourceBlock v1.3,
protected spans có mode rõ ràng và derived slice plan cho block dài. Xem
`sentence_atom_contract.md`. Không tạo LegalUnit, semantic role, AU, retrieval
hay LLM output.

## Kế hoạch 05 — sidecar baseline

Kế hoạch 05 tạo marker/citation/reference/quote/list/speaker-cue annotations và
chỉ các structural relations bề mặt có evidence. Xem `sidecar_contract.md`.
Không gán speaker, authority/treatment, semantic relation, ContextHint hay AU.

## Kế hoạch 06 — ContextHint tối thiểu

Kế hoạch 06 tạo bảy loại đề nghị context bằng rule local deterministic trên
KOS-5, có exact evidence, dependency-addressed cache, cap/dedup ledger và API
query nửa mở. Xem `context_hint_contract.md`. Hint không phải semantic fact và
không loại bất kỳ primary target nào.

```powershell
python -m knowledge_base.pipeline_v1.context_hints
```

Terminal chỉ báo PASS/FAIL và đường dẫn report. Kết quả chi tiết nằm trong
`reports/plan06_context_hint_validation.latest.json`; artifact nằm dưới
`outputs/plan06_context_hints_v1/`.

## Kế hoạch 07 — AnalysisTarget và AnalysisRegion offline

Kế hoạch 07 tạo target/slice, batch và hai view P2a/P2b trên cùng workload
KOS-5. Region chỉ lưu SpanRef, reason, render order, metrics, caps và fingerprint;
mock renderer mở immutable source on demand. Xem `analysis_region_contract.md`.

```powershell
python -m knowledge_base.pipeline_v1.analysis_regions
```

Terminal chỉ báo PASS/FAIL và đường dẫn report. Chi tiết nằm trong
`reports/plan07_analysis_region_validation.latest.json`; artifact nằm dưới
`outputs/plan07_analysis_regions_v1/`. Caps và token estimator là giả định pilot,
không phải cấu hình tối ưu hoặc bằng chứng P2 tốt hơn P0/P1.

Đầu ra:

- `source_contract/`: manifest loader, `CaseSource`, `SpanRef`, immutable store và `open_source`/`open_span` API;
- `contracts/source_contract.v1.json`: JSON Schema của source contract;
- `outputs/source_store_v1/`: năm source version bất biến và index;
- `reports/plan02_source_validation.latest.json`: round-trip/hash/offset report;
- `source_contract.md`: layout và invalidation contract.

Chạy build KOS-5:

```powershell
python -m knowledge_base.pipeline_v1.source_contract --repo-root . --manifest knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json --plan01-report knowledge_base/pipeline_v1/reports/plan01_validation.latest.json --store knowledge_base/pipeline_v1/outputs/source_store_v1 --report knowledge_base/pipeline_v1/reports/plan02_source_validation.latest.json
```

Terminal chỉ báo PASS/FAIL và đường dẫn report.

## Cấu trúc

- `manifests/selected_kos_manifest.v1.json`: inventory/tree hash của 61 file KOS trong năm case.
- `manifests/split_registry.v1.json`: chính sách và danh sách split khóa.
- `contracts/annotation_schema.v1.json`: JSON Schema cho annotation tối thiểu.
- `examples/minimal_annotation.v1.json`: fixture chứng minh các quan hệ nhãn bắt buộc biểu diễn và validate được.
- `annotation_guideline.md`: quy tắc gán nhãn và ranh giới bằng chứng.
- `hard_cases.v1.json`: tình huống cấu trúc/AU cần adjudication.
- `split_policy.md`: chính sách calibration/development/holdout và leakage.
- `scripts/validate_plan01.py`: kiểm tra raw KOS-5 hash, KOS audit tree hash, split provenance/reproducibility, Draft 2020-12 schema/fixture và hard-case contract; ghi báo cáo JSON.
- `tests/test_plan01.py`: regression tests không gọi model hay parser.

## Cổng chuyển bước

Chạy từ repository root:

```powershell
python knowledge_base/pipeline_v1/scripts/validate_plan01.py --repo-root . --kos-root "G:\Legal-AI\kos_sample" --report "knowledge_base\pipeline_v1\reports\plan01_validation.latest.json"
python -m unittest discover -s knowledge_base/pipeline_v1/tests -v
```

Terminal chỉ in `PLAN01 PASS/FAIL` và đường dẫn report. Chi tiết từng file, hash, lỗi và phạm vi kiểm tra nằm trong `reports/plan01_validation.latest.json`.

Test schema dùng `jsonschema` (Draft 2020-12) trong môi trường phát triển; script gate chính vẫn chỉ dùng Python standard library.

Chỉ chuyển sang Kế hoạch 02 khi cả hai lệnh đạt. PASS xác nhận raw-source KOS-5, KOS audit inventory, split provenance và schema/hard-case contract; không xác nhận nhãn sẵn có trong KOS, parser accuracy, AU semantic quality hay retrieval quality. `gold_noticed`/`gold_for_queries` có thể tồn tại trong KOS nhưng validator chỉ dùng path, bytes và hash; KOS này không phải holdout độc lập.

## Tài liệu nền bắt buộc

Cập nhật 2026-10-11: AU compact có baseline prompt v4 và kết quả ba target tại `outputs/au_semantic_v4_dev3_20261011` (giao thức complete, cổng ngữ nghĩa chưa đạt). Kế hoạch 11 có lớp offline `au_candidate_store`; xem [hướng dẫn](au_candidate_store/README.md). Chưa đánh dấu Plan 11 PASS hoặc phép thử ContextHint hoàn tất. Không tự mở Plan 12.

Implementation này bám theo:

- `design/pipeline_redesign_lynx/01_current_pipeline_audit.md`;
- `design/pipeline_redesign_lynx/05_experiment_plan.md`, mục 1, 2, 6, 7;
- `design/pipeline_redesign_lynx/06_corpus_scale_inventory.md`;
- `design/pipeline_redesign_lynx/09_kb_build_plan.md`, mục 3 và Giai đoạn A;
- `design/pipeline_redesign_lynx/04_pipeline_spec.md`, mục 1.


### Checkpoint Kế hoạch 11 — ownership và phép thử hint (2026-10-11)

Review sidecar và primary proposition trong raw TARGET đã triển khai; 51 kiểm thử local đạt. Run v4 được review lại: 1 accepted_agent_reviewed, 4 rejected. Phép thử [ContextHint](context_hint_experiment/README.md) bốn cặp hoàn tất 8/8 request, resume không gọi mạng. Kết quả và giới hạn nằm trong `outputs/plan11_hint_pairs_run_20261011`; P2b tăng token +9,69% và thêm một AU được hỗ trợ trong review phát triển. Phân xử cuối: 3 accepted_agent_reviewed, 4 rejected; cả hai arm còn lỗi qualification. ContextHint cần đo thêm, chưa bật mặc định. Review agent không phải gold; chưa mở Plan 12.


### Checkpoint Plan 11 — vòng v5/v6 ngày 2026-10-11

Đã sửa renderer để phân biệt chính xác `TARGET_BODY` với `CONTEXT_PADDING`, giữ nguyên atom/source/offset; render và prompt version tham gia cache identity. V6 bổ sung ví dụ âm party argument/citation list bằng dữ liệu tổng hợp. Không đổi model Qwen3.5-9B, schema, endpoint hoặc giới hạn output.

Local Main 43 test PASS, tester độc lập 24 PASS. V6 chạy đủ 8 request trên bốn cặp development; resume 8 cache/0 lời gọi mạng. Review che arm có 4 supported/4 rejected trước dedup, mỗi arm 2 supported/2 rejected; negative controls đúng. Store lọc sau dedup có 3 accepted_agent_reviewed, 3 rejected, 2 superseded; review đầy đủ không đồng nghĩa extraction đạt chất lượng.

Lỗi còn lại: court interpretation bị gán statute và lặp hệ quả tại 013948. Không khẳng định mọi proposal bị loại đều context-only: TARGET có cơ sở liên quan, còn độ chi tiết của interpretation chưa chốt. Qualification từng contested ở v5 được reviewer v6 chấp nhận dạng tóm lược; không coi thay đổi verdict là bằng chứng model sửa nghĩa. Agent review không phải gold.

P2a 12.536 token, P2b 13.514 (+978, +7,80%); tổng v6 biết được 26.166 gồm warmup/probe. Tổng hai vòng v5/v6 50.190 token provider báo; usage warmup lỗi, review Codex và GPU/billing chưa đo. P2b bổ sung evidence cho referent holding, không thêm AU đúng được review hỗ trợ; tác dụng downstream chưa đo. ContextHint vẫn needs_measure, chưa bật mặc định; metadata-only arm là disable_candidate trên workload này, chưa suy rộng toàn corpus.

Dừng vòng tuning này; chưa chạy 20 target-holdback và chưa mở Plan12. Tập target khóa trong cùng KOS-5 không phải case-held-out. Bước riêng tiếp theo cần cô lập quoted statute/court interpretation/duplicate hoặc so model trên input khóa; chưa chạy thêm model/remote. Báo cáo, manifest, review, costs, cache và checkpoint: `knowledge_base/pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/decision.md`. V5 vẫn giữ lịch sử tại `outputs/plan11_semantic_v5_gate_20261011`; code/artifact hiện local, chưa nằm trong Git HEAD.

### Checkpoint Plan 12 — triển khai offline/mock (2026-10-11)

Theo yêu cầu tiếp tục riêng của người dùng, đã triển khai [repair agent có tool](repair_agent/README.md), giữ nguyên giới hạn ngữ nghĩa của Plan 10/11. Có R0/R1/R2, revision chờ review, ngân sách, cache và checkpoint. Tester độc lập đạt 27 test; integration mock hai target complete, resume không gọi lại. Chưa gọi endpoint hoặc chứng minh repair AU tốt hơn. Bàn giao và giới hạn: [implementation_report.md](outputs/plan12_agent_repair_20261011/implementation_report.md). Không tự mở Plan 13.

### Checkpoint Plan 12 — sửa giao thức sau lượt live đầu (2026-10-11)

Run `plan12_live_20261011_164339` không tạo revision hợp lệ; R1 từng báo complete dù task lỗi. Đã sửa response gọn, EBNF envelope, một tool/lượt, context không lặp, preflight hai lượt và status/coverage. Main 68 test PASS; tester 19+27 PASS trên cùng code. Mock smoke 013948 complete, resume 0 lượt gọi. Một target R2 dự phòng 13.054 token; hai target 24.650 nên budget_risk dưới trần 20.000. Chưa chạy grammar mới trên endpoint, chưa có semantic PASS. [Báo cáo](outputs/plan12_repair_fix_20261011/implementation_report.md) và [script smoke](outputs/plan12_repair_fix_20261011/run_smoke.ps1); script chưa được Main chạy remote.

### Checkpoint Plan12 — validate-first cùng request (2026-10-11)

Sau smoke v1, chuyển sang verdict supported/uncertain/defect_found trước correction. Supported và uncertain bảo toàn original; defect cần evidence. Runtime strict v2, không action-only bypass; duplicate cần supported anchor khác nó. Không thêm request mặc định, giữ model/cap. Main và tester đều chạy 90 test PASS; mock smoke/resume đạt. Collection rỗng host skip, không phải semantic negative. Single-target R2 preflight dự phòng 13.512 token; grammar v2 chưa probe remote, chất lượng ngữ nghĩa chưa đo. [Bàn giao](outputs/plan12_validate_first_20261011/implementation_report.md) và [script mới](outputs/plan12_validate_first_20261011/run_smoke.ps1). Lịch sử v1 giữ nguyên; chưa mở Plan13.
