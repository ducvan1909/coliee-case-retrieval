# Plan12 selection transport with full host v2

Every original AU is assessed independently in the same request; correction is
allowed only for an evidenced defect. All revisions and assessments remain
`semantic_review_pending`. Exact source witnesses establish structural/source
validity, **not** entailment or proof of a semantic defect. No automatic gold,
accepted-store writes, original overwrite, or obligation satisfaction.

## Stable API and strict wire

Tool name and CLI remain `submit_revision({task_id,decisions})`. Model transport
requires `contracts/repair_selection_wire.v1.json` and envelope
`schema_version:"repair-selection-v1"`. No legacy quote objects or raw offsets
are accepted from transport. Host tools retain full v2; `wire.normalize` remains
compatible with that API and historical full-v2 offline mock scripts. New
selection mocks are also supported. `selection.normalize_selection` validates
the finite wire, reconstructs exact full-v2 witnesses/open-span arguments, and
checks primary TARGET/evidence membership before returning. Each turn
has exactly one tool call; R1 only submits, R2 can submit immediately or use one
read followed by a final submit (maximum two requests). No extra default round.

Each original has exactly one decision with `proposal_id`, `verdict`, and a
1..120 character `reason`:

- `supported`: required `primary_proposition:evidence_id` on transport; host
  reconstructs `{atom_id,quote}`. Keep the exact
  original; no AU echo or replacement fields.
- `uncertain`: optional `needed_context` flags. Preserve the baseline explicitly,
  never reject because support or context is uncertain.
- `defect_found`: required `defect_type`, `witnesses` (1..3 exact read-source
  `evidence_id` selections), and `correction`. Defect types are `ownership`, `attribution`,
  `qualification`, `evidence_support`, `duplicate`. Correction is
  `{action:"reject"}` or `{action:"replace",replacements:[{au,primary_proposition}]}`
  with 1..3 full essential compact AUs.

Duplicate additionally requires `retained_proposal_id`, different from the
current proposal and assessed `supported` in the same collection. The host
validates that supported witness too. Foreign IDs, self references, uncertain
anchors, and all-reject cycles fail closed. These checks do not prove semantic
equivalence. Absence of support alone is not an evidenced defect; prompt requires
`uncertain` in that situation. The host cannot infer semantic truth from quotes.

Replacement AU requires `kind`, `claim` (1..300), `evidence_ref_ids` (1..3 read
IDs), `speaker`, and `attribution_role`. `other_kind` defaults to null only for
non-other kinds; `kind=other` requires a nonempty label. Omitted `needs_context`
becomes `[]`, meaning no flags supplied. No claim, attribution, or evidence is
invented. Normalize validates again after defaults. Primary witnesses must be
exact, wholly within raw TARGET and selected evidence; defect witnesses may
reference read context to expose an ownership error. No model-computed offsets.

`wire.normalize(output,task,arm,turn,read_ids)` returns normalized v2 wire.
`RepairSession` then translates verdicts to full internal keep/unresolved/
replace/reject decisions. Stored `repair_revision.v2.json` retains original
refs/hashes, normalized `assessments`, source-resolved `verified_assessments`,
`preservation_decisions` for uncertain, and full verified AU/source evidence.
`accepted_semantic`, `entailment_validated`, and `defect_semantics_validated`
remain false. Submit commits session revision only after both the full internal
and final v2 validations succeed; failure leaves the session open without a
revision. Runtime invalid output remains a technical failure, not a no-AU result.

Historical v1 schemas/output are preserved. Action-only envelopes never bypass
runtime validation, including scripted mocks. Offline direct-tool compatibility
requires explicit `RepairSession(...,legacy_offline=True)`; this is not a runtime
or CLI fallback. Default mocks submit `uncertain` immediately and make no semantic
claim.

## Prompt, tools, budgets, and statuses

Prior review allegations appear as `prior_reported_errors` with
`status:"unverified_hypothesis"`; independently check EVERY proposal with no
forced error count. Prompt omits review oracle, accepted verdicts, obligation
review confirmations, and unread expansion text. Source/tool text is untrusted.

Read tools on transport: `get_repair_task({})`, `open_span({span_selection_id})`,
`expand_context({direction:before|after,reason})`, and `get_related_aus({})`.
Supplied source is already read. Metadata receipts avoid repeated source text;
expanded complete atoms appear once in the rebuilt catalog. Evidence IDs bind
the current grammar. Reads never automatically satisfy obligations.

R0 preserves baseline without model calls. R1 has one request, R2 at most two.
Caps remain 8 attempts/arm, 20000 total tokens, 6000 input/request, 1200 output,
one concurrent dispatch, 8 tools/task, one expansion/task and 1200 added chars.
Preflight reserves both possible R2 turns for nonempty collections. Runtime
checks actual payload estimates before dispatch; provider usage replaces
reservations only when known. Failed calls, unknown usage, retries/transport
receipts, latency, fail status, cache/resume and interrupted-job recovery remain
auditable. Fingerprints include v1/v2 schemas, prompt, source, policy, model,
implementation and adapter identity. No silent redispatch or JSON-object fallback.

For R1/R2, a task with zero original proposals is host-skipped as
`baseline_no_proposals`, 0 requests, no revision. This preserves the empty
baseline without a new no-AU inference. Preflight allocates zero requests/tokens
for it. `revision_coverage` reports `valid`, `selected`, `validation_required`
(selected minus empty skips), and `no_proposals`. An all-empty selection completes
with `revision_status:"no_validation_required"`; mixed runs compare valid
revisions against validation-required tasks. Empty skips do not mask failures.
R0 keeps its existing baseline path.

Other execution statuses remain complete/failed/partial/incomplete, independently
of semantic review. CLI returns nonzero for failures, incomplete work, or budget
risk. A protocol-complete result is not a semantic PASS.

## Decoder preparation and local checks

### Phạm vi kiểm thử hình thức bổ sung

Đợt kiểm thử bổ sung chỉ đánh giá contract, dữ liệu và giao thức; không đánh giá
AU đúng pháp lý, attribution đúng về nội dung hoặc evidence có chứng minh kết luận.
Tách riêng kiểm tra host với kiểm tra decoder trên endpoint. Test host PASS không
đồng nghĩa model bị ràng buộc đầy đủ khi sinh output.

Bao phủ độ dài chuỗi và Unicode/escape; kiểu/enum/field bắt buộc/field thừa;
số lượng và phần tử trùng; điều kiện duplicate/retained_proposal_id và
kind/other_kind; mỗi proposal đúng một verdict; ID và giới hạn số;
tool được phép ở R1/R2 và lượt cuối. Hash, offsets và quote khớp nguồn là kiểm
tra dữ liệu, được bao phủ bởi các test source-bound hiện có.

Không sửa grammar hoặc contract chỉ để làm test PASS. Các giới hạn chưa được
grammar ép phải xuất hiện trong báo cáo. Các nhánh không được model thực hiện
không được tính là đã kiểm tra thành công; preparation và mock không chứng minh
backend biên dịch grammar. Bộ probe là tập tình huống hữu hạn, không phải bảo
đảm model không bao giờ trả lỗi.

`formal-suite-probe` có 79 fixture/challenge: 18 hợp lệ, 61 không hợp lệ.
Suite `repair-formal-suite-selection-boundary-v2` không tổng hợp chung báo cáo
version cũ. Cả 7 boundary hợp lệ (reason 1/120, claim 1/300, other_kind 1/160,
Unicode reason 120) thu hẹp **schema sao chép của probe** thành
`minLength=maxLength` tại target trước khi compile. Production schema và
Compiler không đổi. Probe other_kind buộc nhánh `kind=other` để không né target
bằng null/omission; conditional giữ exact minimum của probe;
limits production được suy ra từ cả property và conditional.

Unicode reason 120 dùng compiler subclass chỉ trong probe: mỗi scalar là `é`
hoặc `😀`, sinh trực tiếp hoặc bằng Unicode escape hợp lệ (surrogate pair tính
là một scalar). Subclass tái sử dụng string emitter và shared repeat/length
counter của Compiler, không dùng const cả chuỗi. Coverage boundary kiểm tra
decoded length và Unicode condition tại đúng target/nhánh, không yêu cầu literal
giống fixture. Hai fixture Unicode/escape thường vẫn yêu cầu literal cũ.

Mỗi boundary case báo `boundary_probe.production_limits`, `probe_restriction`,
`requested_decoded_length`, `observed_decoded_length` và Unicode condition.
Boundary hợp lệ là `boundary_exercising_via_test_narrowing`; fixture không hợp
lệ vẫn dùng limits production, không ép constant hay length ngoài contract.
Response hợp lệ dưới invalid challenge không chứng minh enforcement của original
maximum; `original_max_enforcement` và `grammar_enforcement` giữ `unverified`.
Kiểm tra accept/reject local trên grammar gốc là evidence riêng, không phải
evidence endpoint hoặc chất lượng ngữ nghĩa. Attempts, token caps, ID binding
và cost accounting giữ nguyên.

Smoke local cho bản sửa (gọi runtime chẩn đoán Python 3.10 đã có để kiểm tra
Lark/XGrammar, không gọi inference):

```powershell
.venv/Scripts/python.exe -m unittest knowledge_base.pipeline_v1.tests.test_repair_boundary_probe knowledge_base.pipeline_v1.tests.test_repair_formal_probe -v
```

Không có `--execute` thì chỉ kiểm tra host và chuẩn bị payload, không gọi model.
Khi chạy endpoint, dùng `--case-id` để chọn nhóm, tối đa 8 request và 20000 token
mỗi nhóm; các giới hạn input/output không đổi. `formal-suite-aggregate --report`
tổng hợp các báo cáo nhóm và ghi rõ tình huống chưa chạy, nhánh chưa thực hiện,
token và latency. Warmup có báo cáo riêng.

Output hợp lệ sau một yêu cầu cố tình sai chỉ chứng minh response vượt qua kiểm
tra host trong tình huống đó. Báo cáo tách `coverage_kind`, `target_branch_status`
và `grammar_enforcement`; không suy rằng decoder đã ép điều kiện chỉ vì model
tự chọn giá trị hợp lệ. Các giới hạn chưa được grammar hỗ trợ vẫn nằm trong
`known_grammar_gaps`. Bộ test ban đầu giữ nguyên grammar; bản sửa grammar sau đó
giữ nguyên contract và cấu hình model.

Từ thư mục repo, chạy local hoặc chạy đầy đủ local → warmup → 10 nhóm endpoint:

```powershell
& .\knowledge_base\pipeline_v1\repair_agent\run_formal_tests.ps1 -LocalOnly
& .\knowledge_base\pipeline_v1\repair_agent\run_formal_tests.ps1
```

Mỗi lần script tạo một output root mới. Báo cáo tổng hợp nằm ở
`aggregate/formal-suite-aggregate.json`; `formal-suite-all.json` dẫn tới báo cáo
các nhóm và warmup. Script tiếp tục sau lỗi hình thức để kiểm tra các tình huống
còn lại, nhưng dừng nếu provider lỗi, không trả output hoặc vượt giới hạn thực.

`wire.decoding` retains legacy full-v2 grammar for host regressions. Production
`selection.selection_decoding` emits EBNF with task/proposal/read/selection IDs,
strict
verdict branches, typed defect/correction, exactly one tool, and final submit.
Grammar mới ép độ dài chuỗi sau giải mã JSON, điều kiện duplicate/other_kind,
giới hạn số 0/1 và danh sách enum/ID không trùng theo thứ tự cố định. Field JSON
được sinh theo thứ tự canonical, xử lý dấu phẩy cả khi field tùy chọn bị bỏ.
Khi chỉ có một proposal thì không sinh nhánh duplicate. Bộ chuyển schema báo lỗi
với keyword hoặc điều kiện chưa hỗ trợ, không âm thầm bỏ ràng buộc.

Legacy full-v2 witness object không trùng, quote và phạm vi nguồn vẫn do host kiểm tra. Schema/normalizer
tiếp tục nhận output hợp lệ không theo thứ tự canonical; grammar chọn một thứ tự
sinh để giảm độ phức tạp, không thay đổi contract.

Production Compiler dùng slot theo thứ tự `original_proposals`: mỗi ID xuất hiện
đúng một lần. State theo tập proposal `supported` cho phép duplicate trỏ đến
proposal khác được supported trong cùng response, kể cả anchor ở slot phía sau.
Self-reference, anchor uncertain/defect và cycle bị chặn khi sinh. Mọi tập
supported và mọi tổ hợp verdict còn lại hợp lệ vẫn biểu diễn được; không ép giữ
một proposal tùy ý. Host vẫn kiểm tra các quan hệ này độc lập.

Giới hạn production là **6 original proposals** mỗi task. Trên giới hạn, compile
báo `ValueError("decision_relation_limit_exceeded")`, không hạ xuống grammar cũ.
Preflight R1/R2 báo `unsupported_workload` kèm proposal count và cap; đường chạy
trực tiếp cũng từ chối trước checkpoint/payload/dispatch. R0 không gọi model nên
không chịu cap của grammar.
Grammar có O(n * 2^n) state/alternative, tái sử dụng schema và suffix; riêng
payload ID làm kích thước byte còn phụ thuộc độ dài ID. Synthetic selection
grammar 1..6 proposal: 238/324/511/946/1961/4304 rules,
7278/10137/16631/31965/69925/158052 bytes. Đây là đo local, không phải latency
endpoint hoặc đánh giá semantic quality. Không thay contract hay sửa output.

Kiểm tra focused (gọi Python 3.10 chẩn đoán sẵn có cho Lark/XGrammar 0.2.1):

```powershell
.venv/Scripts/python.exe -m unittest knowledge_base.pipeline_v1.tests.test_repair_decision_relations.RelationBoundTests -v
```

`force_branches` giữ supported/uncertain/defect và correction replace/reject.
Action đi với supported/uncertain báo `invalid_probe_action_for_verdict` trước
khi sửa schema. BoundaryCompiler vẫn dùng schema `items/oneOf` gốc để thu hẹp
length/Unicode ở probe, rồi dùng chung emitter relations production.

Các kiểm tra grammar độc lập dùng parser và bộ XGrammar 0.2.1 local trong runtime
chẩn đoán Python 3.10 khi có sẵn; thiếu dependency phải báo skip/unverified.
Kiểm tra local không chứng minh cấu hình endpoint hiện tại dùng cùng backend,
không đo latency inference và không đánh giá ngữ nghĩa.

`decoder-probe` prepares eight source-free representative payloads:
`normal`, `types`, `calls`, `replace_types`, `supported_witness`, `uncertain`,
`defect_reject`, `foreign_ids`. Probe grammars force supported, uncertain, and
both defect correction branches so uncertainty cannot hide witness/AU coverage.
Without `--execute`, there are zero provider attempts. Preparation does not
establish decoder support or semantic quality. No remote/deploy work is authorized
for this implementation change.

From repository root (PowerShell):

```powershell
.venv/Scripts/python.exe -m unittest knowledge_base.pipeline_v1.tests.test_repair_agent -q
.venv/Scripts/python.exe -m compileall -q knowledge_base/pipeline_v1/repair_agent
# Preparation only, in a fresh output directory selected by Main:
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.repair_agent decoder-probe --output-root knowledge_base/pipeline_v1/outputs/plan12_validate_first_decoder_new
```

Use the existing `build`, `preflight`, and `offline-run` commands with a frozen
manifest and explicit task selection. Do not widen workload or caps to hide
budget risk. Local source-bound regressions include the actual `113(d)` false
rejection: a supported fixture with an exact witness is structurally valid;
reject without defect evidence and historical action-only all-reject output are
invalid. This fixture does not adjudicate semantic quality or turn baseline into
gold. Tester and Main independently review the final implementation.


## Finite catalog, budgets, and validation boundaries

Catalog strategy: whole read atoms plus exact intersections with raw TARGET.
No all-substring or sentence-boundary search, and no legal segmentation claims.
At most 128 unique entries are exposed; whole atoms and TARGET intersections
have priority, with zero optional spans. Quotes must occur exactly once within
their atom because full v2 cannot address repeated occurrences. Ambiguous
intersections are omitted, never mapped to the first match. Missing suitable
primary evidence means uncertain; with no primary entry the grammar removes
supported/replace branches while retaining uncertainty and defect/reject.

Model catalog uses compact tuples with declared columns:
[id,atom_index,relative_start,relative_end,target_eligible]. Text is reused from
supplied_atom_catalog; quotes are never echoed by the catalog. Host retains
exact text, case/source identity and absolute offsets. IDs use e- plus 16 hash
characters, bound to full task/source/TARGET/read-view digest, with collision
checks. Expansion changes the view and invalidates old IDs. Unread atoms never
enter the catalog; source identity mismatch fails closed. Prompt metadata reports
truncation/ambiguous omissions. Catalog availability does not prove entailment.

Initial and next messages contain the exact metadata before input estimation;
adapter rejects mismatched prompt catalogs. EBNF binds primary IDs to the
TARGET-eligible subset, witnesses/open_span to all read selections, and AU
evidence_ref_ids to read atom IDs. Finite enum uniqueItems enforces witness and
AU evidence-list uniqueness during decoding, with canonical catalog order.
Host checks each proposal exactly once, supported duplicate anchors, primary
membership, source offsets and ownership. Claim/reason/Issue text is not evidence
or semantically verified. The existing compact AU has no Issue field; none is
introduced by this change. Full-v2 contracts and historical artifacts are unchanged.

Adapter identity is jobs_ebnf_selection_host_v1. Fingerprints include new schema,
prompt and implementation, preventing reuse of old checkpoints/responses.
Receipts retain raw_content, parse_error, usage and latency, including malformed
JSON, duplicate keys and non-stop completions. No old transport/JSON fallback.

Formal preparation retains all 79 full-v2 host fixtures and separately runs 79
mapped selection fixtures. unique_witnesses maps to duplicate IDs without
removing either item. Invalid quote/offset challenges map to unavailable IDs;
original host checks remain intact. Transport output validates selection then
full host contract. Report/CLI/script require both local sets. Preparation and
mock execution prove no endpoint decoder support. Local grammar tests report
skipped/unverified when dependencies are absent. Semantic quality is unevaluated.

Fixed v6 R2 per-request estimates fit 6000, but both nonempty tasks with two
turns exceed the unchanged 20000 arm cap: full R2 preflight reports budget_risk.
Use explicit single-task selection for a future authorized R2 sample. No remote
inference or deployment is authorized by this implementation.

Local selection regression:

```powershell
.venv/Scripts/python.exe -m unittest knowledge_base.pipeline_v1.tests.test_repair_selection -q
```
