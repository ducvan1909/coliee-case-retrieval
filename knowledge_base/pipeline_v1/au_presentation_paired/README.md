# Plan23 frozen presentation trial

This additive module executes exactly the source-only frozen 32 TARGET / 64 P0/P1
payloads. It never builds new payloads or reads semantic review labels. P0 and P1
both use the frozen common legend. Preflight verifies source, parent code/input
bindings, original G requests, catalogs, role roundtrip, grammar and 585718 prompt
UTF-8 bytes. UTF-8 bytes are conservative reservations, not provider token usage.

Local API: `core.preflight(manifest, *, parent=None, cfg=None)`.
Execution API: `runner.run(manifest, *, output_root, cfg, parent=None,
execute=False, opener=urlopen, clock=monotonic, sleep=sleep)`.
Manifest/parent can be paths or parsed dictionaries. Tests can inject a fake opener
and clock. Imports, preflight and `run(execute=False)` make no network requests.

```powershell
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.au_presentation_paired preflight --manifest knowledge_base/pipeline_v1/outputs/au_method_audit_20261014/presentation_preflight_v1/presentation_manifest.json --output-root knowledge_base/pipeline_v1/outputs/au_presentation_paired/trial_v1
.venv/Scripts/python.exe -m knowledge_base.pipeline_v1.au_presentation_paired run --manifest knowledge_base/pipeline_v1/outputs/au_method_audit_20261014/presentation_preflight_v1/presentation_manifest.json --output-root knowledge_base/pipeline_v1/outputs/au_presentation_paired/trial_v1
```

Main alone may append `--execute` to run remote. Repeating that exact command
resumes the same ledger and frozen manifest, without a new timestamp or reset.
The CLI uses the existing study_config / AU common environment loader; it never
edits `.env`. Model, URL, jobs endpoint, thinking=false and host_validated must
match the parent. Missing revision configuration uses the parent revision as a
historical operator-verified pin; it is not new live revision verification.

The fresh output directory has an exclusive writer lock. Unique reservations and
POST reservations are durable before dispatch. Caps persist: 64 unique requests,
100 provider POST attempts, 800000 input and 80000 output reservations. Existing
paired Accounting/PairedTransport performs bounded GET health readiness (600s),
retrieve-first jobs and at most one recovery POST with fresh durable absence proof.
There are zero warmup/probe POSTs, based on prior stable grammar evidence.
An existing lock requires confirmation the old process stopped before removal.

`runtime_ledger.json`, immutable `attempt_receipts/`, `receipts/`, and
`pending_receipts/` retain accounting, full successful provider responses, transport
traces, latency and source catalogs. `run.json` checkpoints after each request.
Transport uncertainty, timeout and failed/interrupted jobs stay pending for resume
or explicit review; a completed invalid output becomes terminal unresolved without
repair. Arbitrary server error bodies and credentials are not serialized.
`complete` means all requests have terminal receipts; consult protocol counts.
Protocol validation does not establish semantic quality; Main owns semantic review.
