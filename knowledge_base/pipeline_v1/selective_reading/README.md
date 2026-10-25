# EXACT30 selective-reading pilot

Local preparation and H/P runtime reuse the deployed private BULK app without
changing its schema. Only Main runs remote, after local checks and a production
code freeze. This directory does not deploy, train, join NN/AU or read historical
predictions to choose source regions. The exact universe is the 30 requests in
`manifest.parent.parent.requests`, six targets each in five cases. Old bulk/corpus
outputs cover those targets only and are comparison references, never whole-case
gold. Comparison is owned by Main in `selective_comparison/`.

## API and host tools

`build_manifest(parent_bulk, workload_id, seed=20261013)` stores the full bulk
manifest as `parent`, its digest as `parent_sha256`, and the digest of the original
30 requests as `universe_sha256`. `prepare(manifest, source_store, atom_root)`
returns 30 immutable-bound tasks with raw first/last/salient previews (<=3 x 120
characters). `run(manifest, cfg, arm, output_root, execute=False, *, source_store,
atom_root, transport=None, capability_fetch=None, warmup_fn=None, policy=None,
clock=..., sleep=...)` returns and atomically persists `run.json`.

Host functions in `catalog.py`: `get_case_overview`, `list_blocks` (at most six
workload regions per page), `find_source`, `read_region`, `expand_context`, and
`get_reading_state`. Overviews are metadata plus bounded previews of the six
workload regions, not whole-source text/summaries. Navigation IDs and find hits
are never evidence IDs. Rendered extraction catalogs contain real SentenceAtoms.
Unchanged raw TARGET spans remain authoritative even when atoms include padding.

H selects two priority regions using local preview cues, plus one independent
seeded discovery region. Citation/heading absence is never a hard filter.
P receives all six options and selects two once/case using EBNF enumerated exact
JSON strings (15 ordered pairs). Host adds discovery outside those two. P may
replan once/case when a committed assessment has `needs_context` or discovery
produces a positive proposal. Replan selects one previously unselected region
from a finite catalog (outside initial selection). No hidden model history is
used. Output cap remains 800; initial planner output is roughly 200 bytes, not
an 800-token reasoning narrative. Selection/phase/trigger is recorded by host.

One expansion/case is implemented: local term/distance search over same-case
whole atoms for attribution, response, conditions or exceptions, selecting at
most three hits with <=1,200 added rendered characters. A new extraction request
rerenders the original TARGET and CONTEXT plus these CONTEXT-only atoms, using
the existing `au_compact` prompt/schema and `host_validated` EBNF, <=3 AUs and 800
output tokens. This is a bounded heuristic, not guaranteed context resolution.
No hit or remaining needs_context leaves obligations unresolved. Additional
targets outside the locked 30 are never introduced.

Fixed 3/6 initial selection is a budget experiment. It cannot retain all positive
reference targets if their count exceeds 15 (the supplied baseline has 16).
Cost reduction alone is not an adoption criterion; omission and qualification
tradeoffs need Main's comparison/review. No coverage or quality-equivalence claim.

## Durability, limits and report

Atomic state sequence: reservation -> remote job -> raw receipt -> combined
assessment/interval/obligation/cost commit -> next intent. New groups contain
<=4 independent capsules, enabling server C4; actual provider usage is committed
before the next group reservation. Existing reservations use GET on the same
group/job IDs only; 404/unknown never authorizes another POST. Unhealthy backend
allows recovery GETs and blocks all new admissions. Lost ACK recovery marks the
run resumed and excludes it from fresh performance. Stale lock needs manual
crash investigation/removal; no automatic lock breaking.

Fingerprints bind source, map, navigation/preview policy, seed, catalog, render,
prompt, schemas, decoder, model/settings, implementation and acceptance policy.
Changes invalidate resume rather than silently reuse earlier outputs.

Manifest caps: full prompt UTF8 bytes plus 128 framing <=11,488/request, output
800/request, total input estimate <=200,000 bytes/arm, actual provider input
<=100,000 and output <=30,000 tokens/arm, <=30 H / <=35 P requests. The complete
prompt includes framing/demos/source; EBNF is separate transport data, not model
prompt text. Conservative admission reserves new prompt bytes as a token upper
bound against remaining actual cap, releasing that reservation to reported
provider usage after each subgroup. Estimate is never relabeled actual usage.
Errors/unknown usage still consume request/estimate reservation; unknown usage
blocks new admissions. Budget stop is incomplete and never savings eligibility.
Warmup attempts/usage/latency remain separate setup accounting; server startup
usage is explicitly unavailable. No monetary estimate. No automatic backend
retry; transport recovery/retries appear in transport stats.

`request_ledger`: one FINAL extraction row/original target. `extraction_history`
and `request_history` retain every initial/expanded extraction/planning receipt,
raw response and provenance; cost counts all attempts. `planner_receipts` is
separate. `selected_request_ids` includes all planned/replanned targets;
`protocol_verified_request_ids` means wire/source validation; `assessed_request_ids`
requires a usable positive/negative TARGET assessment, complete coverage and no
needs_context. `unresolved`/`needs_split`/truncated outputs are not assessed;
partial AU proposals remain preserved. Unselected targets stay `not_assessed`.
Exposure, actual delivered atoms and raw TARGET assessment intervals are separate.
Block states are partial projections, never whole-block negative inference.
Every proposal remains `semantic_review_pending`, never autoaccepted.

Execution complete and `selective_pass` are separate: complete may retain explicit
unresolved obligations; selective pass requires successful policy assessment with
none remaining. Both keep `semantic_quality_claim=false`. Injected test transport,
capability or warmup marks `execution_evidence=mock/injected` and cannot be
`performance_eligible`. Fresh default remote runs may be operationally eligible
only after selective pass. Freshness, workload wall, setup and total client wall
are separate; resumed wall cannot be used for speed/savings.

## Commands (repo root)

```powershell
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.selective_reading prepare --output-root knowledge_base/pipeline_v1/outputs/selective_trial30_20261013
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.selective_reading preflight --manifest knowledge_base/pipeline_v1/outputs/selective_trial30_20261013/manifest.json --output-root knowledge_base/pipeline_v1/outputs/selective_trial30_20261013 --arm P
.venv/Scripts/python.exe -m unittest tests.test_selective_reading tests.test_selective_comparison -v
```

Main only, frozen code, existing private BULK URL explicit, separate arm roots:

```powershell
./knowledge_base/pipeline_v1/selective_reading/run_trial.ps1 -Command run -Arm H -Manifest knowledge_base/pipeline_v1/outputs/selective_trial30_20261013/manifest.json -OutputRoot knowledge_base/pipeline_v1/outputs/selective_trial30_20261013/H -Url '<existing-bulk-url>/v1/chat/completions' -Execute
./knowledge_base/pipeline_v1/selective_reading/run_trial.ps1 -Command run -Arm P -Manifest knowledge_base/pipeline_v1/outputs/selective_trial30_20261013/manifest.json -OutputRoot knowledge_base/pipeline_v1/outputs/selective_trial30_20261013/P -Url '<existing-bulk-url>/v1/chat/completions' -Execute
```

Remote CLI loads `knowledge_base/.env` through the shared AU loader with process
environment precedence. It never prints token/config secrets. Preparation and
preflight do not load credentials or call providers.

## Kết quả live 2026-10-13

Đã chạy H/P trên manifest mới `outputs/selective_trial30_fix1_20261013/manifest.json`.
H: 15 target, 36.884 token, giữ 6/16 positive target của reference. P: 19 target,
76.755 token, giữ 11/16; planning/replan dùng 27.970 token. Đây là model-reference
retention, không phải gold recall. Không thay default exhaustive.
Xem `../outputs/selective_trial30_fix1_20261013/RESULT.md` và `FINAL_REVIEW.json`.

Các lệnh dùng root `selective_trial30_20261013` phía trên là ví dụ của đợt đầu,
không dùng lại để đo fresh speedup. Mỗi thử nghiệm mới phải có workload ID mới
và output root mới; chỉ đổi output directory không đổi ID inference.

Nếu P dừng riêng vì estimate byte guard, có thể dùng
`--resume-input-estimate-bytes 260000` trên checkpoint phù hợp: metadata/code
migration được kiểm tra, source/model/prompt/schema/actual token caps không đổi,
receipt đã lưu không gọi lại. Chỉ dùng cờ này lúc budget-stop, không dùng sau
run complete hoặc khi provider/usage unknown. Run resume không là fresh timing.
