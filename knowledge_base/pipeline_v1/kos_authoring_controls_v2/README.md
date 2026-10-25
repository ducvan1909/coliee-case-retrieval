# KOS contract v2 controls

Contract revision only: the same nine frozen fictional v1 sources, IDs, model,
AU contents in demonstrations, temperature and caps. No quota or semantic tuning.
The wire has exactly `aus`, `empty_reason`, `next_action`; AU fields and action
types remain K0's. Examples remove only `assessed_scope_ids`.

Host derives delivered/read IDs from its active catalog selection. Navigation
makes no assessment. Terminal `needs_context` leaves every active scope unresolved,
including responses with AUs. `work_scope_complete` with AUs or a negative reason
records active scopes as `author_self_report`, never semantic truth. Uncertain
reasons cannot complete work. Mixed facts/missing context stays uncertain for
the whole active set. Invalid AUs retain K0's `au_errors` and warnings, and cannot
certify completion. Delivery/read tracking is host protocol bookkeeping, not
proof the model understood the source.

New wire/workload versions and hashes bind v2 code, v1 controls/execution code,
execution dependencies, pinned token counter, and frozen parent artifacts,
including manifest and receipts. A fresh root is required; no v1/K0 migration.
The native CPU bundle has positive, multi-AU, negative and uncertain witnesses,
plus rejected legacy fields, unknown evidence IDs and unknown scope IDs.

Main prepares the ready root after code freeze. These commands are local:
prepare/preflight validate the configured model/endpoint against the original K0
profile without network access. Only nonsecret identity is frozen; credentials
are never written to artifacts. No inference, deployment or environment changes:

```powershell
$run = 'knowledge_base/pipeline_v1/outputs/kos_contract_v2_20261024_ready'
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 prepare --output-root $run
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 preflight --output-root $run
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 run --output-root $run
```

Native CPU replay uses the existing `experiments/k0_grammar_cpu_probe.py` in a
runtime with XGrammar 0.2.1 and the pinned local tokenizer (no model weights):

```powershell
& $cpuPython knowledge_base/pipeline_v1/experiments/k0_grammar_cpu_probe.py --bundle "$run/input/cpu_balanced.json" --output "$run/cpu_balanced.json"
```

`$cpuPython` must be the available native CPU runtime; no automatic installation
or remote fallback. Execution requires this report to pass with exact bundle
SHA256, tokenizer SHA256 and EOS 248044/248046, checked through v1 `require_cpu`.
Only after separate model-run authorization, the runnable opt-in command is:

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 run --execute --output-root $run
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.kos_authoring_controls_v2 evaluate --output-root $run
```

Execution reuses v1 `execution.run_jobs` unchanged for nine jobs: max 12 POSTs,
6000 input/800 output per request, 30000 cumulative reserved/measured tokens.
Immutable intents/receipts and unknown-usage resume behavior remain unchanged.
Reports retain usage and latency, count protocol validity separately from
structural control results, and always leave semantic review pending. There is
no automatic semantic pass, authoring branch, corpus dispatch or K1 permission.
