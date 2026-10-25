# Các kế hoạch triển khai tăng dần cho pipeline P2

## 1. Cách sử dụng tài liệu

Mỗi mục dưới đây là một kế hoạch độc lập, ngắn gọn, có thể đưa riêng cho Codex để lập kế hoạch triển khai chi tiết. Chỉ chuyển sang kế hoạch kế tiếp khi cổng đánh giá của kế hoạch hiện tại đã đạt và kết quả đã được ghi thành artifact.

Khi dùng một mục làm prompt, sao chép toàn bộ mục từ tiêu đề Kế hoạch đến hết phần Không làm, gồm cả danh sách tài liệu bắt buộc. Mở prompt bằng yêu cầu: “Hãy đọc các tài liệu được chỉ định, kiểm tra code/artifact thật, rồi lập kế hoạch triển khai chi tiết cho đúng phạm vi dưới đây. Chưa viết code.”

Các tên file trong danh sách tài liệu được tính từ thư mục knowledge_base/design/pipeline_redesign_lynx. Khi gửi prompt, dùng đường dẫn đầy đủ tính từ repo hoặc đính kèm file bằng @-mention. Artifact sinh ở kế hoạch trước cũng phải được đính kèm hoặc chỉ đúng đường dẫn; không yêu cầu Codex dựa vào lịch sử chat. Nếu Codex không đọc được tài liệu bắt buộc thì phải ghi blocker, không tự đoán contract.

Khi nhận prompt, Codex phải:

1. đọc các tài liệu bắt buộc và tóm tắt những ràng buộc áp dụng;
2. kiểm tra code, dữ liệu và artifact thật trong repo;
3. nêu giả định, dependency và file dự kiến thay đổi;
4. đề xuất từng bước triển khai, test, dữ liệu đánh giá và lệnh chạy;
5. định nghĩa output schema, cache/version và cách rollback;
6. nêu điều kiện đạt, không đạt và dừng;
7. chỉ ra điểm nào trong tài liệu là bằng chứng, quyết định hiện hành hoặc giả thuyết chưa đo;
8. không triển khai phần thuộc kế hoạch tiếp theo;
9. không gọi inference trả phí nếu chưa được yêu cầu rõ.

Mọi kế hoạch giữ các ranh giới chung:

- source, source hash và exact offset là nguồn sự thật;
- schema PASS không đồng nghĩa đúng ngữ nghĩa;
- không dùng output cũ, KOS hoặc agent review làm gold;
- không mở rộng toàn corpus trước pilot và held-out gate;
- chưa triển khai NN–AU matching, retrieval view, reranker hoặc final case selection.

## 2. Tập file phải chạy trước

Mọi kế hoạch phải triển khai và đánh giá lần đầu trên đúng năm file đã được dùng trong KOS:

| Case ID | Raw source |
|---|---|
| 013009 | data/task1_train_files_2026/cases/013009.txt |
| 013948 | data/task1_train_files_2026/cases/013948.txt |
| 011904 | data/task1_train_files_2026/cases/011904.txt |
| 045155 | data/task1_train_files_2026/cases/045155.txt |
| 099980 | data/task1_train_files_2026/cases/099980.txt |

Manifest chuẩn là knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json. Mỗi prompt phải yêu cầu Codex đọc manifest này, xác minh đủ năm source path và hash trước khi lập kế hoạch chạy.

Artifact tham khảo KOS nằm tại G:/Legal-AI/kos_sample/cases/<case_id>/. Raw source trong manifest là input của pipeline; artifact KOS chỉ dùng để hiểu tình huống, loại record và tìm điểm cần audit. AU, NN, Issue, link hoặc nhận xét trong KOS không phải gold và không được đưa vào prompt model như đáp án.

Quy tắc chuyển tập:

1. mỗi component phải chạy offline/test trên KOS-5 trước;
2. component không áp dụng cho một file phải ghi not_applicable cùng lý do, không âm thầm thay file;
3. chỉ sau khi đạt cổng của kế hoạch hiện tại mới được chạy development/held-out đã khóa;
4. không thêm file vì kết quả KOS-5 xấu hoặc bỏ file vì khó;
5. KOS-5 chỉ dùng sửa contract và phân tích lỗi, không đủ chứng minh chất lượng tổng quát.

Khi sao chép một kế hoạch thành prompt, phải sao chép cả mục Tập file phải chạy trước này.

## Kế hoạch 01 — Khóa manifest và bộ đánh giá

**Mục tiêu:** tạo nền đánh giá cố định trước khi thay đổi parser hoặc model.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 01_current_pipeline_audit.md: lỗi và chi phí V13–V15;
- 05_experiment_plan.md, mục 1, 2, 6 và 7;
- 06_corpus_scale_inventory.md: corpus, năm án calibration và tài nguyên;
- 09_kb_build_plan.md, mục 3 và Giai đoạn A;
- 04_pipeline_spec.md, mục 1 để giữ ranh giới phạm vi.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** kiểm tra và khóa lại manifest KOS-5 hiện có, xác minh source hash, định nghĩa format nhãn và chọn các tình huống cấu trúc/AU khó. Chưa gán đầy đủ mọi nhãn và không tự chọn lại năm file.

**Đầu ra:** manifest versioned, split policy, annotation guideline tối thiểu, danh sách tình huống và script kiểm tra leakage/trùng case.

**Cổng chuyển bước:** source của năm case khớp manifest; split tái lập; schema nhãn biểu diễn được SourceBlock, AU, attribution, condition và ContextObligation.

**Không làm:** parser, model, prompt hoặc tuning.

## Kế hoạch 02 — CaseSource, SpanRef và source store

**Mục tiêu:** xây lớp source bất biến và exact-span contract.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, mục 2, Bước 0, mục 5 và mục 7;
- 09_kb_build_plan.md, Giai đoạn A và mục 5;
- 05_experiment_plan.md, Cổng cấu trúc;
- output/manifest của Kế hoạch 01.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** nạp source, tạo source version/hash, SpanRef, metadata và API mở exact span. Thiết kế invalidation khi source đổi.

**Đầu ra:** source store, manifest loader, open-span API, round-trip/hash/offset tests và mutation test.

**Cổng chuyển bước:** round-trip, hash và offset đạt 100%; source mới tạo version mới; không artifact nào ghi đè nguyên văn.

**Không làm:** phân block, sentence, annotation hoặc LLM.

## Kế hoạch 03 — Structural pre-pass và SourceBlock

**Mục tiêu:** tạo leaf SourceBlock có thứ tự mà không ép ranh giới ngữ nghĩa.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 1;
- 10_sourceblock_analysis_region_proposal.md, mục 2, 4 và 5;
- 03_decision_log.md: quyết định về SourceBlock, heading, block tree và LegalUnit;
- 05_experiment_plan.md, mục 6 và 7.1;
- source contract và manifest đã đạt gate ở Kế hoạch 02.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** paragraph, paragraph marker, dòng độc lập, list, quote block, footnote, editorial và heading candidate. Phân biệt paragraph marker với bracket year/citation.

**Đầu ra:** SourceBlock schema, parser rule/version, parser error ledger và block visualization/audit tool.

**Cổng chuyển bước:** block phủ 100% source, leaf block không chồng lấn, ghép theo thứ tự khôi phục source; hard cases được phân xử và báo lỗi riêng.

**Không làm:** block tree bắt buộc, heading semantics, LegalUnit hoặc AU.

## Kế hoạch 04 — SentenceAtom và protected spans

**Mục tiêu:** tạo địa chỉ câu bên trong SourceBlock mà không cắt sai citation, abbreviation, tên án, quote hoặc list.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 2 và record SentenceAtom ở mục 5;
- 10_sourceblock_analysis_region_proposal.md, mục 5.1 và 5.3;
- 03_decision_log.md: vai trò SentenceAtom và lý do bỏ global boundary scorer;
- 05_experiment_plan.md, mục 6 và 7.1;
- SourceBlock schema/parser report của Kế hoạch 03.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** sentence segmentation theo luật pháp lý, protected-span contract và derived slice boundary cho block quá dài.

**Đầu ra:** SentenceAtom schema, segmenter version, protected-span tests và báo cáo lỗi theo loại.

**Cổng chuyển bước:** atom nằm trong parent block, phủ text được phân câu, offset đúng; không có lỗi cắt protected span nghiêm trọng trong tập đã phân xử.

**Không làm:** chấm toàn bộ sentence seam, global LegalUnit partition hoặc semantic role.

## Kế hoạch 05 — Sidecar baseline và structural relations

**Mục tiêu:** tạo tín hiệu local tối thiểu phục vụ context construction.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 1, Bước 2 và mục 5;
- 02_lynx_research_review.md: document/annotation, NER và reference extraction;
- 07_supplemental_research.md: giới hạn transfer và segmentation/context;
- 08_component_audit_round2.md: chi phí, lỗi và phương án thay thế của worker;
- output SentenceAtom/protected-span của Kế hoạch 04.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** marker, citation/reference rule, nested quote/list spans, quote balance, speaker cue và các relation next/previous, containment, continuation, governed-by-heading có evidence.

**Đầu ra:** Annotation và StructuralRelation records có producer/version/evidence, worker error ledger và API lấy sidecar theo span.

**Cổng chuyển bước:** worker lỗi không làm mất source; relation có exact evidence; citation/marker/quote tests đạt ngưỡng đã khóa; không suy speaker từ NER hoặc treatment từ citation.

**Không làm:** NER model, terminology, topic model, rhetorical-role model hoặc semantic graph.

## Kế hoạch 06 — ContextHint tối thiểu

**Mục tiêu:** đề nghị context bổ sung bằng rule local, không dùng model ngôn ngữ.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 3 và record ContextHint ở mục 5;
- 10_sourceblock_analysis_region_proposal.md, mục 6;
- 03_decision_log.md: quyết định về ContextHint và semantic graph;
- 05_experiment_plan.md, P2a/P2b và metrics region;
- sidecar/relation report của Kế hoạch 05.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** open quote, open list, dependent lead-in, reference to previous, citation/quote continuation và speaker-continuity candidate.

**Đầu ra:** ContextHint schema, ru 
**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 3, mục 2 và record AnalysisTargetSlice/AnalysisRegionManifest;
- 10_sourceblock_analysis_region_proposal.md, mục 3, 7 và 8;
- 05_experiment_plan.md, các arm P0/P1/P2 và metrics region;
- 09_kb_build_plan.md, Giai đoạn C;
- ContextHint rules/report của Kế hoạch 06.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** primary target phủ mọi content block, derived slice cho block quá dài, batching, bounded context, render order, caps và AnalysisRegionManifest.

**Đầu ra:** scheduler, region builder, manifest schema, mock request renderer và thống kê unique/repeated chars.

**Cổng chuyển bước:** primary targets phủ mỗi content block đúng một lần; context overlap không bị tính lại thành target; không auto-skip theo citation/AU cue; mọi region nằm trong cap hoặc có stop reason.

**Không làm:** gọi LLM, trích AU hoặc tự mở whole case.

## Kế hoạch 08 — CoverageLedger, cache và resume bằng mock

**Mục tiêu:** bảo đảm thực thi có thể dừng, tiếp tục và kiểm toán trước khi phát sinh chi phí model.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 6 và mục 7;
- 05_experiment_plan.md, metrics tool/vận hành và Cổng cấu trúc;
- 09_kb_build_plan.md, Giai đoạn C, mục 5 và Build readiness;
- 01_current_pipeline_audit.md: retry, output rỗng, run chưa hoàn tất và chi phí lặp;
- region manifests của Kế hoạch 07.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** target states, request ledger, cache fingerprint, atomic write, retry cap, resume và dependency invalidation.

**Đầu ra:** CoverageLedger, cache store, mock provider, fault-injection tests và báo cáo run hoàn tất/run lỗi.

**Cổng chuyển bước:** resume không gọi lại kết quả hợp lệ; lỗi một target không mất target khác; source/policy đổi invalidates đúng phạm vi; budget/provider stop không bị ghi complete hoặc no-AU.

**Không làm:** đánh giá semantic AU.

## Kế hoạch 09 — Khóa AU gold, kind và few-shot set

**Mục tiêu:** có thước đo độc lập trước khi chọn AU model hoặc prompt.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 4 và AuthorityUnit contract;
- 05_experiment_plan.md, mục 2, 5, 6 và 7.3;
- 03_decision_log.md: AU recall, field-level witness và model-role separation;
- 09_kb_build_plan.md, mục 3.2;
- 01_current_pipeline_audit.md: omission, attribution và treatment errors;
- manifest/split đã khóa ở Kế hoạch 01.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** phân xử AU exact span, kind, attribution, condition, exception, limit, cross-block AU và hard negatives trên calibration/development; khóa held-out.

**Đầu ra:** AU gold versioned, guideline, disagreement log, few-shot set tách khỏi held-out và scoring script.

**Cổng chuyển bước:** nhãn mở được lại source; kind conflicts được ghi rõ; held-out không bị dùng để sửa prompt; KOS/output model không được coi là gold.

**Không làm:** coi output model là human gold hoặc dùng nó để mở khóa held-out/Plan 10.

**Trạng thái thay thế 2026-10-06:** P09-R4 đã phủ 369/369 target; R5 audit độc lập PASS trong phạm vi model-silver development và R6 quyết định `allow_baseline_development_only`. Hiện có 188 AU, 186 hard negative và 8 unresolved. Mọi artifact downstream phải ghi `evaluation_against=model_silver`; không phải human/semantic gold hay ước lượng retrieval độc lập. Nguồn trạng thái hiện hành là `pipeline_v1/outputs/plan09_au_gold_v1/r6_use_decision.v1.json` và `pipeline_v1/reports/plan09_r5_r6_final_verification.v1.json`, thay cho progress `.latest.json` lịch sử.

**Ranh giới thực thi:** quyết định R6 chỉ mở development baseline. Lệnh chạy provider/model thật cần được ghi ngân sách, model và giới hạn riêng; Plan 10 không tự biến model-silver thành human gold.

## Kế hoạch 10 — AU extraction baseline

**Mục tiêu:** chọn và chạy một AU extraction baseline trên AnalysisRegion đã khóa.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 3 và Bước 4;
- 05_experiment_plan.md, các arm chính, mục AU extraction và metrics AU/tool;
- 06_corpus_scale_inventory.md: model/tài nguyên và giới hạn cần kiểm tra lại;
- 09_kb_build_plan.md, Giai đoạn D;
- region/ledger interfaces của Kế hoạch 07–08;
- AU gold, few-shot set và scoring script của Kế hoạch 09.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** fixed prompt/schema, processed target ids, kết quả từng target (`positive`, `hard_negative`, `unresolved`), AU candidates, context requests và warnings. So rule baseline với model zero-shot/few-shot nếu được phép chạy.

**Đầu ra:** provider adapter, prompt/schema version, raw response cache, parsed AU candidates, token/request/latency report và semantic score.

**Kiểm tra trì hoãn ContextHint:** Kế hoạch 07 cho thấy trên KOS-5, P2b không thêm source span hoặc source character nào so với P2a; phần tăng chỉ là metadata provenance và token ước lượng. Đây là finding về cách dựng region, chưa phải bằng chứng ContextHint vô ích về ngữ nghĩa. Sau khi Kế hoạch 09 đã khóa AU gold, Kế hoạch 10 phải chạy P2a và P2b bằng cùng AU model, prompt, schema, examples và caps để đo AU exact-span recall, omission, attribution, condition/exception/limit, `needs_context`, token, context lặp và latency. Không đổi cap hoặc model riêng cho P2b để tạo lợi thế.

**Cổng chuyển bước:** host phát hiện missing target, invalid span và truncated output; AU mở được exact evidence; báo riêng protocol success và semantic quality; không vượt budget.

**Không làm:** repair agent, optional feature workers hoặc Issue matching.

**Trạng thái triển khai 2026-10-07:** đã có harness offline/mock tại `pipeline_v1/au_baseline/`. Nó materialize request manifest P2a/P2b từ AnalysisRegion đã khóa, paired-control manifest, cache/ledger từng arm, rule baseline và accounting từ rendered span thực. Kiểm thử độc lập chỉ PASS cho runtime/experiment contract offline; semantic AU extraction, zero/few-shot provider run, semantic score và retrieval score chưa chạy.

### Contract response dự kiến cho model

Contract dưới đây được khóa ở mức thiết kế để triển khai provider adapter sau; chưa thay đổi runtime hiện tại. Một response xử lý một `AnalysisRegion` và có thể chứa nhiều target. `start_char`/`end_char` là offset toàn cục trong raw source đã được hiển thị trong prompt.

Không yêu cầu model lặp lại `source_hash`, model ID, prompt version, token usage, latency hoặc `finish_reason`. Host đã biết các giá trị này từ request/provider envelope và phải gắn chúng vào receipt. `truncated` cũng do host suy từ `finish_reason`, lỗi parse hoặc thiếu target. Không dùng `no_au_target_ids` song song với kết quả từng target vì hai biểu diễn có thể mâu thuẫn. Không dùng confidence số chưa được hiệu chỉnh; bất định được biểu diễn bằng `candidate_status`, `unresolved` và `uncertainty_reasons`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:coliee:pipeline-v1:plan10-au-model-output-v1",
  "title": "Plan 10 AU model output",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "request_id",
    "processed_target_ids",
    "target_results",
    "context_requests",
    "warnings"
  ],
  "properties": {
    "schema_version": {"const": "plan10-au-model-output-v1"},
    "request_id": {"$ref": "#/$defs/identifier"},
    "processed_target_ids": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/identifier"}
    },
    "target_results": {
      "type": "array",
      "minItems": 1,
      "items": {"$ref": "#/$defs/targetResult"}
    },
    "context_requests": {
      "type": "array",
      "items": {"$ref": "#/$defs/contextRequest"}
    },
    "warnings": {
      "type": "array",
      "maxItems": 16,
      "items": {"$ref": "#/$defs/warning"}
    }
  },
  "$defs": {
    "identifier": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "span": {
      "type": "object",
      "additionalProperties": false,
      "required": ["start_char", "end_char", "quote"],
      "properties": {
        "start_char": {"type": "integer", "minimum": 0},
        "end_char": {"type": "integer", "minimum": 1},
        "quote": {"type": "string", "minLength": 1}
      }
    },
    "attribution": {
      "type": "object",
      "additionalProperties": false,
      "required": ["role", "speaker", "evidence_span"],
      "properties": {
        "role": {
          "enum": [
            "proposition",
            "authority",
            "current_court_response",
            "condition",
            "exception",
            "limit",
            "other"
          ]
        },
        "speaker": {
          "enum": [
            "current_court",
            "cited_authority",
            "party",
            "statute",
            "editor",
            "mixed",
            "unknown"
          ]
        },
        "evidence_span": {"$ref": "#/$defs/span"}
      }
    },
    "authorityUnit": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "local_au_id",
        "claim_text",
        "kind",
        "other_kind",
        "evidence_spans",
        "attributions",
        "condition_spans",
        "exception_spans",
        "limit_spans",
        "candidate_status",
        "uncertainty_reasons"
      ],
      "properties": {
        "local_au_id": {"$ref": "#/$defs/identifier"},
        "claim_text": {"type": "string", "minLength": 1, "maxLength": 1500},
        "kind": {
          "enum": [
            "holding",
            "standard_of_review",
            "statutory_hook",
            "procedural_rule",
            "fact_pattern_rule",
            "foreign_law",
            "other",
            "unresolved_kind"
          ]
        },
        "other_kind": {"type": ["string", "null"], "maxLength": 160},
        "evidence_spans": {
          "type": "array",
          "minItems": 1,
          "maxItems": 8,
          "items": {"$ref": "#/$defs/span"}
        },
        "attributions": {
          "type": "array",
          "minItems": 1,
          "maxItems": 8,
          "items": {"$ref": "#/$defs/attribution"}
        },
        "condition_spans": {
          "type": "array",
          "maxItems": 8,
          "items": {"$ref": "#/$defs/span"}
        },
        "exception_spans": {
          "type": "array",
          "maxItems": 8,
          "items": {"$ref": "#/$defs/span"}
        },
        "limit_spans": {
          "type": "array",
          "maxItems": 8,
          "items": {"$ref": "#/$defs/span"}
        },
        "candidate_status": {"enum": ["complete", "needs_context"]},
        "uncertainty_reasons": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "enum": [
              "ambiguous_speaker",
              "ambiguous_kind",
              "missing_condition",
              "missing_exception",
              "missing_limit",
              "possible_duplicate",
              "insufficient_court_response",
              "other"
            ]
          }
        }
      },
      "allOf": [
        {
          "if": {"properties": {"kind": {"const": "other"}}},
          "then": {"properties": {"other_kind": {"type": "string", "minLength": 1}}},
          "else": {"properties": {"other_kind": {"const": null}}}
        }
      ]
    },
    "targetResult": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "target_id",
        "decision",
        "authority_units",
        "hard_negative_reason",
        "unresolved_reason",
        "reason_detail"
      ],
      "properties": {
        "target_id": {"$ref": "#/$defs/identifier"},
        "decision": {"enum": ["positive", "hard_negative", "unresolved"]},
        "authority_units": {
          "type": "array",
          "maxItems": 8,
          "items": {"$ref": "#/$defs/authorityUnit"}
        },
        "hard_negative_reason": {
          "enum": [
            null,
            "party_argument_only",
            "fact_only",
            "procedural_history_only",
            "citation_without_proposition",
            "editorial",
            "insufficient_context",
            "other"
          ]
        },
        "unresolved_reason": {
          "enum": [
            null,
            "insufficient_context",
            "ambiguous_speaker",
            "ambiguous_kind",
            "ambiguous_boundary",
            "conflicting_evidence",
            "other"
          ]
        },
        "reason_detail": {"type": ["string", "null"], "maxLength": 500}
      },
      "allOf": [
        {
          "if": {"properties": {"decision": {"const": "positive"}}},
          "then": {
            "properties": {
              "authority_units": {"minItems": 1},
              "hard_negative_reason": {"const": null},
              "unresolved_reason": {"const": null}
            }
          }
        },
        {
          "if": {"properties": {"decision": {"const": "hard_negative"}}},
          "then": {
            "properties": {
              "authority_units": {"maxItems": 0},
              "hard_negative_reason": {
                "enum": [
                  "party_argument_only",
                  "fact_only",
                  "procedural_history_only",
                  "citation_without_proposition",
                  "editorial",
                  "insufficient_context",
                  "other"
                ]
              },
              "unresolved_reason": {"const": null}
            }
          }
        },
        {
          "if": {"properties": {"decision": {"const": "unresolved"}}},
          "then": {
            "properties": {
              "authority_units": {"maxItems": 0},
              "hard_negative_reason": {"const": null},
              "unresolved_reason": {
                "enum": [
                  "insufficient_context",
                  "ambiguous_speaker",
                  "ambiguous_kind",
                  "ambiguous_boundary",
                  "conflicting_evidence",
                  "other"
                ]
              }
            }
          }
        }
      ]
    },
    "contextRequest": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "target_id",
        "au_local_id",
        "obligation_type",
        "direction",
        "anchor_span",
        "reason"
      ],
      "properties": {
        "target_id": {"$ref": "#/$defs/identifier"},
        "au_local_id": {"type": ["string", "null"]},
        "obligation_type": {
          "enum": [
            "attribution",
            "condition",
            "exception",
            "limit",
            "current_court_response",
            "cross_block_context",
            "other"
          ]
        },
        "direction": {"enum": ["before", "after", "both", "unknown"]},
        "anchor_span": {
          "oneOf": [
            {"$ref": "#/$defs/span"},
            {"type": "null"}
          ]
        },
        "reason": {"type": "string", "minLength": 1, "maxLength": 500}
      }
    },
    "warning": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "target_id", "detail"],
      "properties": {
        "code": {
          "enum": [
            "possible_duplicate",
            "multiple_speakers",
            "citation_without_visible_context",
            "region_boundary_risk",
            "other"
          ]
        },
        "target_id": {"type": ["string", "null"]},
        "detail": {"type": ["string", "null"], "maxLength": 500}
      }
    }
  }
}
```

Host validation bắt buộc ngoài JSON Schema:

- `processed_target_ids` phải bằng chính xác tập target trong request;
- mỗi target xuất hiện đúng một lần trong `target_results`;
- mọi span phải nằm trong source và `quote == source[start_char:end_char]`;
- `local_au_id` không được trùng trong response;
- `context_requests.target_id` và `au_local_id` phải tham chiếu record tồn tại;
- output bị cắt phải được phát hiện từ provider `finish_reason`, lỗi parse hoặc thiếu target;
- model ID, prompt/schema version, source hash, raw-response reference, usage và latency do host ghi vào receipt;
- host chỉ xác minh cấu trúc/hash/offset/quote ở Plan 10; không được ghi nhận đó là xác minh ngữ nghĩa.

## Kế hoạch 11 — Host validation, ownership và dedup

**Mục tiêu:** chuyển model output thành AU candidate có provenance mà không giả vờ đã xác minh ngữ nghĩa.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 4, Bước 5 và AuthorityUnit contract;
- 10_sourceblock_analysis_region_proposal.md, mục 8 và 9;
- 05_experiment_plan.md, metrics AU semantic và Cổng chất lượng;
- 03_decision_log.md: field-level witness và semantic/structural distinction;
- raw/parsed AU outputs của Kế hoạch 10.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** hash/offset/quote validation, target ownership theo primary proposition trong raw TARGET, overlap/duplicate handling, status transition và field-level witness checks.

**Đầu ra:** AU store candidate layer, validator, rejection/unresolved reasons và audit view.

**Phân xử sơ bộ ContextHint:** chỉ so sánh P2a/P2b sau khi output đã qua validation, ownership và dedup của Kế hoạch 11. Nếu P2b không cải thiện AU/context quality, không giảm omission hoặc nhu cầu mở context, nhưng tăng token/metadata, ghi `disable_candidate` cho ContextHint; chưa xóa implementation và chưa coi calibration là quyết định cuối.

**Cổng chuyển bước:** invalid span không được accepted; cross-region duplicate có quyết định tái lập; thiếu attribution/condition bắt buộc thành unresolved; structural validation được báo riêng.

**Không làm:** tự sửa claim hoặc tự bổ sung evidence bằng model.

**Checkpoint ban đầu 2026-10-11 (lịch sử, đã được bổ sung bên dưới):** module `knowledge_base/pipeline_v1/au_candidate_store` đã có CLI offline, kiểm tra source/atom/evidence, cách ly lỗi từng AU, field witness `MODEL_ASSERTED`, dedup cùng case/source và audit. 24 kiểm thử local đạt. Đã xử lý run compact v4 ba target thành 5 AU `unresolved`; không accepted. Ownership chỉ là điểm neo cấu trúc, chưa có vị trí proposition chính và witness ngữ nghĩa riêng từng field; vì vậy chưa đánh dấu toàn bộ Kế hoạch 11 PASS. Chi tiết trong `au_candidate_store/README.md` và `outputs/plan11_candidate_store_v4_20261011`.

**Readiness trước phép thử (lịch sử):** đánh giá ContextHint trong phạm vi Kế hoạch 11, chưa mở Kế hoạch 12. Trước phép thử phải xác minh cặp cùng target/context và nội dung hint thực sự được gửi: AU compact hiện không truyền `hint_payload`, manifest P2b baseline lịch sử thiếu payload hint. Build Plan07 hiện tại có 11 request P2b chứa 16 hint ID đã resolve; khác phiên bản build lịch sử. Không dùng các run cũ để kết luận lợi ích ngữ nghĩa. Phép thử metadata đầu tiên giữ nguyên model/prompt/schema/context/cap giữa hai arm, chỉ khác nội dung hint có provenance; việc mở rộng nguồn theo hint là một đối chứng riêng. Dùng lỗi baseline đã lưu để đo claim/evidence, TARGET contribution, omission và điều kiện, đồng thời báo token/latency. Không tự sửa claim hoặc coi review agent là human gold. Readiness report tại `outputs/plan11_context_hint_readiness_20261011/readiness.json` khóa bốn target có hint thật cho phép thử nhỏ kế tiếp.

**Checkpoint bổ sung 2026-10-11:** đã triển khai review sidecar khóa run/proposal hash, primary proposition trong raw TARGET, witness theo field và điều kiện, omission review, stale/conflict fail-closed. 51 kiểm thử local đạt; review run v4 cũ cho 1 accepted_agent_reviewed và 4 rejected, không coi là gold. Nội dung ContextHint thật đã được resolve, kiểm tra provenance và truyền vào prompt. Phép thử metadata bốn cặp đã hoàn tất 8/8 request; resume gọi mạng 0 lần. P2b tăng 1.027 token (+9,69%); tổng usage biết được gồm warmup/probe là 22.345. Hồ sơ review che arm, bảng chi phí và quyết định được lưu ở `outputs/plan11_hint_pairs_run_20261011`. Phân xử sau review độc lập che arm của tester_advanced: 3 accepted_agent_reviewed, 4 rejected, 0 unresolved; không phải gold. P2b thêm một AU hợp lệ với condition witnesses tại 013948 nhưng cả hai arm còn lỗi qualification. ContextHint là needs_measure, chưa bật mặc định. Kết quả review đầy đủ không đồng nghĩa extraction đạt cổng chất lượng; chưa mở Plan 12.

## Kế hoạch 12 — ContextObligation và repair chọn lọc

**Mục tiêu:** so agent repair có tool với một request repair cố định và không repair; đo lỗi sửa được, lỗi mới, omission và tổng chi phí. Tách sửa trên context hiện có với mở thêm context.

**Đặc tả triển khai bổ sung:** [12_plan12_agent_repair_implementation.md](12_plan12_agent_repair_implementation.md). Đây là pilot sửa lỗi đã biết dù extraction Plan 10–11 chưa đạt gate mở rộng; không coi ngoại lệ development này là cho phép chạy toàn KOS-5, held-out hoặc Plan 13. Giai đoạn triển khai đầu chỉ offline/mock; live pilot cần preflight và review riêng.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 5 và ContextObligation contract;
- 10_sourceblock_analysis_region_proposal.md, mục 6.2 và 9.3;
- 05_experiment_plan.md, mục Repair, metrics region/AU và Cổng chi phí;
- 03_decision_log.md: repair không đọc toàn corpus;
- unresolved/rejected AU audit từ Kế hoạch 11.
- 12_plan12_agent_repair_implementation.md: task/tool/revision, caps, R0/R1/R2 và cache/resume;
- run.json và review.bound.json tại pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/run/.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** RepairTask có error_origin; tools get_repair_task/open_span/expand_context/get_related_aus/submit_revision; obligation/revision ledger; R0 không repair, R1 một request, R2 tối đa hai lượt model và một expansion. Dùng Qwen3.5-9B hiện tại, không tự đổi model. Khóa số request/token tuyệt đối cho pilot; budget 0/1/5/10% chỉ thử sau khi chốt mẫu số và có workload đủ lớn. Review chỉ lỗi không chứng minh routing tự động.

**Đầu ra:** frozen task manifest, tool contracts, runtime/adapters, traces/cache, revision và obligation ledgers, before/after AU review packet và bảng chi phí R0/R1/R2. Host-valid revision vẫn semantic_review_pending, không tự accepted.

**Cổng chuyển bước:** local tests và live/semantic gates được báo riêng; obligation không tự satisfied chỉ vì mở thêm text; nguồn/hash/offset giữ nguyên; expansion có cap/stop reason; resume không gọi lại task terminal hợp lệ; lỗi một task không mất task khác; so lỗi mới/omission và correct controls. Chỉ giữ R2 nếu có lợi so với R1 đủ bù chi phí. Mock không chứng minh repair tốt.

**Không làm:** repair toàn case hoặc vòng tự sửa không giới hạn.

## Kế hoạch 13 — Ablation từng worker tùy chọn

**Mục tiêu:** chỉ giữ metadata có lợi cho AU/context sau khi đã có baseline đo được.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 2;
- 02_lynx_research_review.md: NER, reference, terminology và orchestration;
- 07_supplemental_research.md: nghiên cứu ngoài Lynx và giới hạn;
- 08_component_audit_round2.md: cost/error/alternative của từng worker;
- 05_experiment_plan.md, mục Ablation worker và metrics quy mô;
- AU baseline và repair reports của Kế hoạch 10–12.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** thử riêng từng worker: citation sequence labeling, legal NER, terminology/topic shift, speaker model và rhetorical-role model. Mỗi lần chỉ thay một worker.

**Đầu ra:** adapter/version cho worker đang thử, sidecar output, transfer-error audit, compute report và AU/context delta.

**Cổng chuyển bước:** worker chỉ được giữ nếu held-out gain vượt ngưỡng và có chi phí toàn corpus chấp nhận được; worker thất bại bị tắt và artifact ghi rejected.

**Không làm:** bật đồng thời nhiều worker rồi quy lợi ích cho một thành phần.

## Kế hoạch 14 — Query preprocessing, CiteSite và NN

**Mục tiêu:** tạo query-side records có exact evidence mà chưa nối sang AU.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, mục 4 và contracts CiteSite/NoticeNeed;
- 03_decision_log.md, mục vai trò marker theo KOS;
- 01_current_pipeline_audit.md: source selection, omission và leakage risks;
- 05_experiment_plan.md: marker/non-marker slices và tình huống bắt buộc;
- source/open-span contract của Kế hoạch 02.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** marker/citation cue, marker origin, fallback không marker, bounded context, NN proposition/constraints và leakage checks.

**Đầu ra:** QuerySource, CiteSite, NoticeNeed, trace và marker/non-marker evaluation.

**Cổng chuyển bước:** mọi CiteSite/NN mở được exact query span; marker không bị suy thành authority identity; không dùng citation chưa che hoặc gold; fallback có origin riêng.

**Không làm:** NN–AU matching, candidate retrieval hoặc reranking.

## Kế hoạch 15 — Issue metadata và alias

**Mục tiêu:** lưu Issue mở cho AU/NN mà không biến nó thành hard gate.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, Bước 7 và Issue contracts;
- 03_decision_log.md: Issue mở, alias, parent/child và hard-gate decisions;
- 09_kb_build_plan.md, mục 3.3 và Giai đoạn E;
- 02_lynx_research_review.md: terminology và terminological KG;
- AU records từ Kế hoạch 11–13 và NN records từ Kế hoạch 14.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** Issue, IssueAlias, IssueProposal, IssueLink, lookup normalization, nil/unresolved và registry versioning.

**Đầu ra:** issue store, proposal/adjudication workflow, provenance và false-alias test set.

**Cổng chuyển bước:** string/embedding match không tự tạo accepted link; alias không chứa parent/child; thiếu Issue không làm mất AU/NN; registry update invalidates đúng link phụ thuộc.

**Không làm:** hierarchy tự động, merge/split tự động hoặc NN–AU matching.

## Kế hoạch 16 — Snapshot và tool interface

**Mục tiêu:** publish KB snapshot có thể đọc và kiểm toán mà không sao chép source text vào mọi record.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 04_pipeline_spec.md, mục 2, Bước 8 và mục 5–7;
- 09_kb_build_plan.md, mục 2, 5, 6 và 7;
- 02_lynx_research_review.md: document/annotation/provenance contract;
- 03_decision_log.md: cache, full KG và phạm vi retrieval;
- manifests, stores và ledgers đã đạt gate ở Kế hoạch 02–15.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** versioned snapshot, get case/block/atom/annotation/relation, open/expand span, build region, get coverage/AU/Issue/CiteSite/NN.

**Đầu ra:** snapshot manifest, read-only tools, audit view, migration/invalidation report và access tests.

**Cổng chuyển bước:** tool luôn trả case id, source hash, exact spans, producer/version/status; source vẫn mở được khi annotation thiếu; snapshot tái lập từ manifest.

**Không làm:** retrieval planner hoặc candidate ranking.

## Kế hoạch 17 — Pilot tích hợp và quyết định P0/P1/P2

**Mục tiêu:** quyết định có giữ P2 và cấu hình nào trước khi mở rộng corpus.

**Tài liệu bắt buộc phải đọc trong prompt:**

- 03_decision_log.md: quyết định hiện hành và các arm đối chứng;
- 04_pipeline_spec.md: toàn bộ contract cuối;
- 05_experiment_plan.md: toàn bộ thiết kế thí nghiệm và cổng quyết định;
- 06_corpus_scale_inventory.md: quy mô/tài nguyên;
- 09_kb_build_plan.md, Giai đoạn G và readiness;
- 10_sourceblock_analysis_region_proposal.md, mục 11–13;
- toàn bộ implementation/evaluation reports của Kế hoạch 01–16.

**Workload chạy đầu tiên:** KOS-5 theo knowledge_base/pipeline_v1/manifests/calibration_manifest.v1.json; xác minh hash trước khi chạy. Dùng raw source làm input, KOS artifact chỉ để audit và không làm gold.

**Phạm vi:** chạy P0, P1, P2a, P2b và P2c bằng cùng source, AU model, prompt/schema, examples và caps; sau calibration mới chạy held-out.

**Quyết định cuối về ContextHint:** P2a và P2b phải được so sánh trên development rồi held-out đã khóa. Chỉ giữ ContextHint trong cấu hình mặc định nếu P2b cải thiện AU/context quality hoặc giảm omission, ContextObligation hay repair mà không tạo severe regression, và lợi ích đủ bù token, context lặp, latency cùng chi phí toàn corpus. Nếu P2b giữ nguyên source context và AU result nhưng chỉ tăng metadata/token, tắt ContextHint khỏi cấu hình mặc định; code có thể được giữ như arm thực nghiệm có version. KOS-5 không đủ để tự quyết định giữ hoặc bỏ.

**Đầu ra:** bảng AU/context quality, severe errors, token/request/latency/compute, overlap, cache/resume/update cost và dự toán toàn corpus.

**Cổng hoàn tất:** trước hết các arm phải chạy đủ KOS-5 và ghi lỗi theo từng file; sau đó mới chạy development/held-out đã khóa. Chọn một cấu hình dựa trên chất lượng và chi phí tuyệt đối. Nếu P0 hoặc P1 tương đương và rẻ hơn thì bỏ P2; nếu dữ liệu chưa đủ thì ghi insufficient evidence, không mở rộng toàn corpus.

**Không làm:** giải thích tiết kiệm bằng thiếu coverage, dừng sớm hoặc thay retrieval stack giữa các arm.

## 3. Thứ tự và dependency

~~~text
Nhánh corpus: 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13
Nhánh query:              02 → 14
Hợp nhất:                13 + 14 → 15 → 16 → 17
~~~

Kế hoạch 14 có thể được lập chi tiết song song sau khi source contract ở Kế hoạch 02 ổn định, nhưng kết quả chỉ được tích hợp ở Kế hoạch 16. Kế hoạch 13 chỉ bắt đầu sau AU baseline để mỗi worker có thước đo downstream. Kế hoạch 17 là cổng duy nhất cho phép đề xuất mở rộng từ KOS-5 và các tập development/held-out đã khóa sang toàn corpus.


### Checkpoint Plan 11 — vòng v5/v6 ngày 2026-10-11

Đã sửa renderer để phân biệt chính xác `TARGET_BODY` với `CONTEXT_PADDING`, giữ nguyên atom/source/offset; render và prompt version tham gia cache identity. V6 bổ sung ví dụ âm party argument/citation list bằng dữ liệu tổng hợp. Không đổi model Qwen3.5-9B, schema, endpoint hoặc giới hạn output.

Local Main 43 test PASS, tester độc lập 24 PASS. V6 chạy đủ 8 request trên bốn cặp development; resume 8 cache/0 lời gọi mạng. Review che arm có 4 supported/4 rejected trước dedup, mỗi arm 2 supported/2 rejected; negative controls đúng. Store lọc sau dedup có 3 accepted_agent_reviewed, 3 rejected, 2 superseded; review đầy đủ không đồng nghĩa extraction đạt chất lượng.

Lỗi còn lại: court interpretation bị gán statute và lặp hệ quả tại 013948. Không khẳng định mọi proposal bị loại đều context-only: TARGET có cơ sở liên quan, còn độ chi tiết của interpretation chưa chốt. Qualification từng contested ở v5 được reviewer v6 chấp nhận dạng tóm lược; không coi thay đổi verdict là bằng chứng model sửa nghĩa. Agent review không phải gold.

P2a 12.536 token, P2b 13.514 (+978, +7,80%); tổng v6 biết được 26.166 gồm warmup/probe. Tổng hai vòng v5/v6 50.190 token provider báo; usage warmup lỗi, review Codex và GPU/billing chưa đo. P2b bổ sung evidence cho referent holding, không thêm AU đúng được review hỗ trợ; tác dụng downstream chưa đo. ContextHint vẫn needs_measure, chưa bật mặc định; metadata-only arm là disable_candidate trên workload này, chưa suy rộng toàn corpus.

Dừng vòng tuning này; chưa chạy 20 target-holdback và chưa mở Plan12. Tập target khóa trong cùng KOS-5 không phải case-held-out. Bước riêng tiếp theo cần cô lập quoted statute/court interpretation/duplicate hoặc so model trên input khóa; chưa chạy thêm model/remote. Báo cáo, manifest, review, costs, cache và checkpoint: `knowledge_base/pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/decision.md`. V5 vẫn giữ lịch sử tại `outputs/plan11_semantic_v5_gate_20261011`; code/artifact hiện local, chưa nằm trong Git HEAD.

### Checkpoint Plan 12 — triển khai offline/mock (2026-10-11)

Theo yêu cầu tiếp tục riêng của người dùng, đã triển khai đặc tả [repair agent](12_plan12_agent_repair_implementation.md) mà không nâng gate ngữ nghĩa Plan 10/11. Main chạy 43 test PASS, tester độc lập 27 PASS (các bộ có phần trùng nhau). Integration mock hai target: R0/R1/R2 complete, lần lượt 0/2/3 lượt mock; resume cả ba không gọi lại. Bốn task được dựng từ review v6, nguồn năm án giữ nguyên. Hai quote witness lệch nguồn được sửa trong sidecar mới có audit, không sửa lịch sử. Revision còn chờ review; chưa gọi endpoint, chưa chứng minh lợi ích repair, chưa mở Plan 13. Bàn giao: `knowledge_base/pipeline_v1/outputs/plan12_agent_repair_20261011/implementation_report.md`; CLI: `knowledge_base/pipeline_v1/repair_agent/README.md`.

### Checkpoint Plan 12 — sửa sau live ngày 2026-10-11

Lượt live đầu chưa có revision hợp lệ; status complete cũ của R1 không phải PASS. Đã triển khai response gọn, EBNF cho envelope/action/type/enum, một tool mỗi lượt, context lượt hai không lặp nguồn, ngân sách dự phòng hai lượt và trạng thái failed/partial/incomplete. Main 68 test PASS; tester độc lập 19+27 PASS. Mock smoke riêng 013948 complete/resume không dispatch lại; preflight R2 một target 13.054 token PASS, hai target 24.650 budget_risk. Control 011904 hoãn trong smoke, không đặt lại ngân sách bằng chia run âm thầm. EBNF mới chưa probe trên endpoint, semantic review còn pending. Bàn giao và script warmup/probe/smoke: `knowledge_base/pipeline_v1/outputs/plan12_repair_fix_20261011/implementation_report.md`. Chưa mở Plan 13.

### Checkpoint Plan12 — validate-first cùng request

Sau smoke v1 đã chạy protocol nhưng reject cả collection, triển khai v2 supported/uncertain/defect_found. Các reported errors là giả thuyết; chỉ defect có exact witness mới được correction, quote không tự chứng minh defect đúng. Supported/uncertain giữ original; duplicate không được loại cả nhóm. Không thêm vòng gọi mặc định hoặc tăng cap. Main/tester 90 test PASS, mock source-bound smoke và resume đạt; collection rỗng 0 calls. Single-target R2 preflight 13.512 token PASS. Probe v2 mới prepared local, chưa đo semantic/false-defect trên model; lịch sử v1 không đổi, chưa mở Plan13. Bàn giao: `knowledge_base/pipeline_v1/outputs/plan12_validate_first_20261011/implementation_report.md`.
