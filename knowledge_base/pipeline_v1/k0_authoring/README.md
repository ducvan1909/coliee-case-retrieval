# K0 authoring

Run from the repository root with `.venv/Scripts/python.exe`:

```powershell
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_authoring prepare --output-root ROOT
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_authoring preflight --output-root ROOT
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_authoring run --output-root ROOT
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.k0_authoring run --output-root ROOT --mock
```

`prepare` accepts `--parent-root A_ROOT` (default: the frozen A experiment).
Input is `ROOT/input/workload.json`. The default run is dry. `--mock` uses
local durable job envelopes with no provider usage; it makes no network calls.
`--execute` explicitly authorizes live requests using the current
`knowledge_base/.env` through `study_config`; model and endpoint must match A.
No command edits environment configuration or deploys anything.

For an authorized live smoke, add `--execute --max-new-requests 1`. This bounds
new POST attempts in that invocation, including retries. Resume without the
flag for the remaining cumulative budget; limits never reset. Native grammar
compilation remains `not_checked` by local/mock validation.

Live and mock checkpoints are separate (`ROOT/live/`, `ROOT/mock/`). Repeat the
same command to resume: source, code, job, runtime and receipt bindings must
match. State is derived from verified receipts before any new dispatch. An
exclusive `.lock` prevents simultaneous writers; a lock left by a killed
process requires operator review before removal.

Case turns are sequential and independent requests include active source,
navigation and current drafts. The frozen union is the actual 16 delivered
stage1 scopes across three cases. Tools cannot open evidence outside it.
There is no planner phase, fixed TARGET ownership, KOS answer input or repair.

Limits include retries: 12 model POST attempts globally, 6000 input reservation
per request and 800 output tokens; cumulative input plus output reservation
and observed provider usage each have a 30000 ceiling. Input reservation is
the maximum of locally rendered chat tokens and full serialized payload tokens
plus 128 margin, using Main's pinned Qwen tokenizer. If assets are unavailable,
the labeled fallback reserves full payload UTF-8 bytes plus 128. The report
records the method and asset identity; neither is provider usage.
Unknown provider usage blocks new live POST admission;
retrieval of existing durable jobs remains possible. Readiness uses GET only.

Receipts precede state commits. Invalid local AU candidates preserve other
valid drafts and pause that case. Incomplete output is invalid and never
repaired. Other cases retain their progress; budget/provider pauses are
checkpointed in `run.json`. `work_scope_complete` can hold while case source
assessment remains partial. Protocol completion never certifies semantic AU
quality, human gold, retrieval quality or corpus readiness.
