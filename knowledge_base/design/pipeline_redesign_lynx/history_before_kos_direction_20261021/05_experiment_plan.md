# Kế hoạch thực nghiệm preprocessing P2

## 1. Câu hỏi cần trả lời

1. SourceBlock có giữ source/offset tuyệt đối và nhận diện cấu trúc đủ ổn định không?
2. AnalysisRegion có giữ AU cùng attribution, condition, exception và court response cần thiết không?
3. ContextHint và ContextObligation có giảm omission đủ bù context lặp và request tăng thêm không?
4. P2 có tốt hơn baseline paragraph cố định và LegalUnit partition cũ khi dùng cùng model AU không?
5. Worker tùy chọn nào thực sự tạo lợi ích?
6. Chi phí cold build, resume và incremental update trên toàn corpus là bao nhiêu?

Pilot preprocessing không đo NN–AU matching, reranker hoặc final micro-F1.

## 2. Dữ liệu và khóa tập

### Calibration

Dùng năm án đã có để tái hiện lỗi và sửa contract:

- 013009;
- 013948;
- 011904;
- 045155;
- 099980.

Năm án này không đủ để tuyên bố chất lượng tổng quát.

### Pilot phân tầng

Chọn tối thiểu 60 án:

- 20 án development;
- 40 án held-out;
- phân tầng theo độ dài, mật độ marker/citation, paragraph format, court/year và số AU dự kiến;
- khóa theo case trước khi tuning;
- loại trùng và gần trùng giữa development/held-out.

KOS và output cũ chỉ là tài liệu tham khảo. Nhãn xác nhận phải được phân xử lại từ source.

### Tập nhãn tối thiểu

1. SourceBlock spans/type và lỗi parser.
2. AU exact spans, kind, attribution, conditions, exceptions và limits.
3. Context obligations cần để hiểu AU.
4. Hard negatives: party argument, quotation, editorial, fact thuần và citation mention không phải AU.
5. Query CiteSite/NN slices có marker và không marker.

Không dùng model output làm gold.

## 3. Các arm chính

Mọi arm dùng cùng source snapshot, AU model, few-shot examples, output schema và generation caps. Chỉ cách dựng context khác nhau.

| Arm | Context construction | Mục đích |
|---|---|---|
| P0 | SourceBlock/paragraph target + N neighbor cố định | Baseline rẻ nhất |
| P1 | Sentence → boundary scorer → global LegalUnit | Đối chứng pipeline cũ |
| P2a | SourceBlock + bounded local neighbors/relations | Đo kiến trúc P2 tối thiểu |
| P2b | P2a + ContextHint local | Đo giá trị hint |
| P2c | P2b + tối đa một ContextObligation expansion | Đo expansion có điều kiện |

P2b/P2c không được dùng model khác P0/P1 trong so sánh chính. Nếu P0 đạt chất lượng tương đương với chi phí thấp hơn, chọn P0. Nếu P1 thắng P2 về held-out AU/context và chi phí, xem lại quyết định bỏ global LegalUnit.

## 4. Ablation worker

Chạy trên cùng P2 region policy:

| Worker | Baseline | Biến thể | Phép đo chọn/bỏ |
|---|---|---|---|
| Citation/reference | Rule grammar | Sequence labeler | Protected-span lỗi, AU/context gain, compute |
| NER | Không NER hoặc gazetteer nhỏ | Legal NER checkpoint | AU/context gain, transfer error |
| Speaker | Cue + quote rules | Speaker model | Severe attribution error |
| Terms/topic | Không dùng | Term/topic detector | Missing context và region size |
| Rhetorical role | Không dùng | Sequence role model | AU recall/precision và routing gain |

Không bật gộp nhiều worker trước khi biết contribution của từng worker. Local model vẫn phải báo CPU/GPU giờ, RAM/VRAM, throughput và artifact/update cost.

## 5. Thử nghiệm AU extraction và repair

### AU extraction

So:

- rule/statistical baseline;
- ít nhất hai model zero-shot/few-shot nếu tài nguyên cho phép;
- cùng target/region manifest và schema;
- không fine-tune ở đợt này.

Model phải trả processed target ids để host phát hiện omission. Confidence tự khai không được coi là calibrated probability.

### Repair

Đánh giá repair budget 0%, 1%, 5% và 10% target hoặc token. Routing dựa trên:

- missing target;
- invalid/unsupported span;
- attribution hoặc condition risk;
- unresolved obligation;
- sidecar disagreement;
- duplicate/conflict.

Không route chỉ vì block không có citation hoặc confidence hơi thấp. Báo riêng lợi ích semantic và phần token/latency tăng thêm.

Plan 12 pilot tách R0 không repair, R1 một request cố định với context hiện có và R2 agent chọn tool (tối đa hai lượt model, một expansion, mỗi response một tool call và lượt cuối submit). Cùng model, task manifest và review policy; tính tool instructions/context vào chi phí. Preflight kiểm tra cả lượt hai; báo riêng token ước lượng và usage thực, không coi tổng request fail là tiết kiệm. Khóa request/token tuyệt đối trước chạy, không dùng "target hoặc token" như một mẫu số tùy chọn sau kết quả. Nhãn error_origin=agent_review ghi rõ oracle-assisted repair, chưa đo automatic routing. Ca thiếu context thật và ca tổng hợp báo riêng. Correct controls kiểm tra false repair; mọi revision cần review trước khi tính lỗi sửa được. Gate giao thức bổ sung gồm output bị cắt, AU sai kiểu, tool call quá số lượng và nguồn bị gửi lặp. Trạng thái failed/partial/incomplete phải được báo riêng, không gộp mọi task terminal thành complete. Đặc tả tại 12_plan12_agent_repair_implementation.md.

Đối chứng validate-first dùng cùng target/source/model/ngân sách với repair cũ, không thêm vòng model mặc định. Đo false defect/false rejection, supported và uncertain bị sửa sai hay mất, lỗi còn lại, correction có evidence, và tổng usage cả run lỗi. Probe mới thử supported/uncertain/defect_found; grammar cũ PASS không mở gate grammar mới. Fixture action-only reject cả collection phải bị runtime mới từ chối; đây là kiểm tra protocol, không phải chứng minh model sẽ không loại nhầm khi đã trả verdict/evidence hợp schema. Tính chi phí validation cùng repair trong cùng request; chưa có kiểm chứng độc lập thì không gọi correction là lỗi đã sửa.

## 6. Tình huống bắt buộc

- heading thiếu, sai hoặc bị nhầm từ dòng ngắn;
- bracket year/citation bị nhầm paragraph marker;
- paragraph rất dài chứa nhiều proposition;
- AU chạy qua hai block;
- condition/exception nằm ở block trước hoặc sau;
- party statement gần court finding;
- court response nằm xa;
- quotation/list chưa đóng;
- đoạn không citation nhưng có AU;
- án dài nhưng ít AU;
- output hợp schema nhưng bỏ target/AU;
- annotation sai hoặc thiếu;
- source đổi một phần và resume sau lỗi.

## 7. Metrics

### 7.1. Source và cấu trúc

- source round-trip/hash/offset: 100%;
- leaf block coverage: 100%, overlap ngoài policy: 0;
- paragraph marker precision/recall;
- false heading candidate;
- quote/list continuation error;
- protected citation/entity split error;
- structural relation false-positive rate.

Không dùng boundary F1 như chỉ số chính của P2. P1 có thể báo boundary F1 riêng, nhưng quyết định dựa trên AU/context và chi phí.

### 7.2. Region và coverage

- target coverage và processed-target agreement;
- primary-target spans phủ mỗi content block đúng một lần; slice của block dài không tạo gap;
- unique source chars, rendered chars và overlap ratio;
- context obligation precision và satisfaction;
- expansions/request;
- false no-AU rate;
- unresolved/budget-exhausted rate;
- context chứa đủ attribution/condition/exception/court response.

### 7.3. AU semantic

- AU span precision/recall/F1;
- proposition faithfulness;
- kind accuracy/confusion;
- severe attribution error;
- missing condition/exception/limit;
- cross-block AU recall;
- duplicate/fragment rate;
- accepted AU thiếu field-level witness.

### 7.4. Tool và vận hành

- schema/protocol errors;
- request, retry và repair counts;
- cache hit và resume idempotence;
- invalidation đúng dependency;
- failure ledger completeness;
- latency p50/p95;
- CPU/GPU giờ, RAM/VRAM;
- provider input/output/reasoning tokens;
- cold build, repeated build và incremental update.

### 7.5. Quy mô

Dự toán toàn corpus theo phân bố độ dài và độ khó, không nhân một case trung bình. Báo:

- tổng target/region/request;
- unique và repeated chars/tokens;
- throughput theo case/giờ và ký tự/giờ;
- compute/token tuyệt đối;
- tỷ lệ repair/expansion;
- phần chi phí do run lỗi;
- break-even theo số lần KB được tái sử dụng.

Giảm 30% token chỉ là mục tiêu thử nghiệm khi chất lượng tương đương; không tính thiếu coverage hoặc dừng sớm là tiết kiệm.

## 8. Cổng quyết định

### Cổng cấu trúc

- source/hash/offset/coverage đạt 100%;
- resume không áp dụng lặp;
- invalidation đúng phạm vi;
- block/region không làm source mất truy cập.

### Cổng chất lượng

- không có severe attribution/treatment error chưa xử lý trong tập phân xử;
- P2 không giảm AU recall hoặc tăng missing condition vượt khoảng bất định đã khóa;
- target complete trong ledger nhưng semantic omission vẫn được báo riêng;
- Issue thiếu không làm mất AU/NN.

### Cổng chi phí

- báo chi phí tuyệt đối của cold build, resume và update;
- P2b/P2c chỉ thắng nếu gain semantic đủ bù context lặp, request và repair;
- hint/worker/obligation không có gain bị bỏ;
- nếu P0 đạt chất lượng tương đương và rẻ hơn, dùng P0;
- nếu chưa đủ power để loại trừ regression nghiêm trọng, kết luận insufficient evidence.

## 9. Trình tự chạy

1. Viết source, block, span, cache và resume tests bằng mock.
2. Khóa parser policy và tập tình huống calibration.
3. Chạy P0/P1/P2 bằng cùng mock/model interface.
4. Phân xử lỗi cấu trúc và semantic trên development.
5. Khóa model, prompt, schema, caps, hint và obligation policy.
6. Chạy held-out một lần.
7. Chạy workload lặp và source-copy mutation để đo resume/invalidation.
8. Dự toán toàn corpus.
9. Chọn P0, P1 hoặc cấu hình P2; ghi rõ thành phần bị bỏ.

Chỉ sau cổng này mới lập đợt mở rộng KOS hoặc toàn corpus.

## 10. Checkpoint phép thử metadata ContextHint — 2026-10-11

Bốn cặp target đã khóa tại `pipeline_v1/outputs/plan11_hint_pairs_20261011`; tám request Qwen3.5-9B hoàn tất. Hai arm giữ nguyên nguồn/context, prompt v4, schema, decoder và cap 800; chỉ P2b nhận nội dung hint có provenance. Đây là phép thử metadata, chưa thử mở thêm nguồn theo hint.

P2a: 9.880 input + 721 output = 10.601 token. P2b: 10.819 input + 809 output = 11.628 token, tăng 1.027 token (+9,69%). Overhead warmup/probe có usage là 116 token; tổng provider usage biết được là 22.345. Mười warmup HTTP 503 không có usage, chi phí tài nguyên và review agent chưa đo; không quy đổi USD. Resume đủ tám kết quả không gọi mạng và không thêm token.

Hồ sơ che arm và nguồn kiểm tra nằm tại `pipeline_v1/outputs/plan11_hint_pairs_run_20261011`. Phải dùng verdict có witness và ownership để phân xử lợi ích; số AU sinh thêm không phải gain. Mẫu này không chứng minh chất lượng toàn corpus hoặc đủ để bật ContextHint mặc định. Không mở Kế hoạch 12 trong checkpoint này.

Phân xử cuối trên pilot: review độc lập che arm và Main cho 3 accepted_agent_reviewed, 4 rejected; omission không thấy proposition riêng biệt bị thiếu. P2b có thêm AU ở 013948 giữ scope 112(3)/section97 qua condition witnesses, nhưng cả hai arm vẫn có lỗi qualification. Quyết định needs_measure; chưa có so chất lượng tương đương, không coi token tăng là vô ích hoặc lợi ích đã đủ bù chi phí. Review agent không phải gold.


### Checkpoint Plan 11 — vòng v5/v6 ngày 2026-10-11

Đã sửa renderer để phân biệt chính xác `TARGET_BODY` với `CONTEXT_PADDING`, giữ nguyên atom/source/offset; render và prompt version tham gia cache identity. V6 bổ sung ví dụ âm party argument/citation list bằng dữ liệu tổng hợp. Không đổi model Qwen3.5-9B, schema, endpoint hoặc giới hạn output.

Local Main 43 test PASS, tester độc lập 24 PASS. V6 chạy đủ 8 request trên bốn cặp development; resume 8 cache/0 lời gọi mạng. Review che arm có 4 supported/4 rejected trước dedup, mỗi arm 2 supported/2 rejected; negative controls đúng. Store lọc sau dedup có 3 accepted_agent_reviewed, 3 rejected, 2 superseded; review đầy đủ không đồng nghĩa extraction đạt chất lượng.

Lỗi còn lại: court interpretation bị gán statute và lặp hệ quả tại 013948. Không khẳng định mọi proposal bị loại đều context-only: TARGET có cơ sở liên quan, còn độ chi tiết của interpretation chưa chốt. Qualification từng contested ở v5 được reviewer v6 chấp nhận dạng tóm lược; không coi thay đổi verdict là bằng chứng model sửa nghĩa. Agent review không phải gold.

P2a 12.536 token, P2b 13.514 (+978, +7,80%); tổng v6 biết được 26.166 gồm warmup/probe. Tổng hai vòng v5/v6 50.190 token provider báo; usage warmup lỗi, review Codex và GPU/billing chưa đo. P2b bổ sung evidence cho referent holding, không thêm AU đúng được review hỗ trợ; tác dụng downstream chưa đo. ContextHint vẫn needs_measure, chưa bật mặc định; metadata-only arm là disable_candidate trên workload này, chưa suy rộng toàn corpus.

Dừng vòng tuning này; chưa chạy 20 target-holdback và chưa mở Plan12. Tập target khóa trong cùng KOS-5 không phải case-held-out. Bước riêng tiếp theo cần cô lập quoted statute/court interpretation/duplicate hoặc so model trên input khóa; chưa chạy thêm model/remote. Báo cáo, manifest, review, costs, cache và checkpoint: `knowledge_base/pipeline_v1/outputs/plan11_semantic_v6_gate_20261011/decision.md`. V5 vẫn giữ lịch sử tại `outputs/plan11_semantic_v5_gate_20261011`; code/artifact hiện local, chưa nằm trong Git HEAD.
