# Selective context offline

Isolated LOCAL experiment implementing Main's design21 policy. No inference,
network, Modal or production changes. KOS-5 is development/calibration because
the known paragraph gap informed this experiment; no heldout quality claim.

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.selective_context_offline --output-root knowledge_base/pipeline_v1/outputs/selective_context_offline_20261013/implementation/revision01
```

Output must be empty. Existing files are never overwritten. Defaults require
validated baseline and order/context revision02 reports. Locks are checked
against rebuilt source inventory, packets, current helper code and full order.
Policy, inventory and all selections are written before KOS evidence is loaded.

## API for independent tests

- `POLICY`, `QUALIFICATION_DEPENDENCY_RE` in `policy.py`: frozen rules.
- `expand_context(inventory) -> inventory copy`: TARGET/features/order unchanged.
  Scan TARGET/baseline context using old `context._ownership`. A qualification
  cue scans one immediately preceding and following block in the same case.
  Only uniquely addressed opening numbered-paragraph markers are eligible.
  No neighbor is included merely for a cue; bridge/reference additions are
  admitted as one whole bundle after retaining baseline context. Union subtracts
  TARGET; 6000 characters/12 intervals; cap means unknown, never truncation.
  Fetched blocks are not recursively scanned. No-op packets and rendered bytes
  remain exactly baseline, including refs already fully delivered and caps.
- `request_cost(baseline_row, expanded_row, divisor=4, mode='preassembled')`:
  returns `serialized_bytes`, `estimated_tokens`, `hypothetical_requests`,
  `hypothetical_second_requests`, `packet_changed`, `mode`.
  `two_step` sends baseline plus the full expanded packet for changed rows;
  each request is rounded separately. No delta-only or free-memory assumption.
- `schedule_selective(baseline_inventory, expanded_inventory, ordered_ids,
  *, budget=None, bytes_per_token=4, mode='preassembled', arm=None)`:
  same old full-order scan/skip scheduler, with exact summed request costs.
  A temporary host cost proxy is never a model packet.
- `source_audit(inventory)`: source-only counts and row audits.
- `run(*, output_root, baseline_root=..., order_report=..., context_report=...,
  kos_root=..., **inventory_kwargs)`: builds, locks, writes, then audits KOS.
  Baseline builder keyword arguments allow explicit inventory paths in API.

## Output schema v1

- `frozen_snapshot.json`: prior lock, report/code bindings, policy and hashes
  of inventory/selection. `inventory.json`: selective rows without source texts.
- `selection_snapshot.json`: exhaustive schedules and selections at fixed
  `floor(247339*f)` budgets for f=.1/.25/.5/.75/1 and divisors 3/4/5.
- `source_audit.json`: all host-only row audits. Candidate cue/reference counts,
  actual context additions, caps and unresolved references are distinct.
  Reference observations retain seed provenance; one offset can be observed in
  baseline and bridge scan. Counts are observations, not unique legal needs.
- `report.json`: `protocol_status`, `protocol_checks`, `bindings`, hashes,
  `schedules`, `budget_curves` (old metrics including case/category/per-AU
  exposure), `target_matched_cost`, `source_audit` count summary,
  `source_audit_path`, `packet_probes`, `kos_inventory`, errors and `cost`.
  Arms are multi_queue/source_order/cue_control/global_priority and both
  aggressive/selective preassembled/two_step. Matched records use identical
  selected target IDs across baseline/aggressive/selective and both modes;
  dependency records report whole bridge plus referenced-block delivery.
  Probe `[21]`/`[5]` is selected only after freeze, solely for diagnosis.
- `summary.md`: /4 budget table. Main owns root result/design documents.

`context_audit.trigger_candidate` includes cue-only rows and owned references;
`opened_additional_context`/`packet_changed` identify accepted additions.
Schedules separately count hypothetical second requests only for changed rows.
Actual request/token counters are zero. Cost uses serialized UTF-8 bytes with
the unchanged renderer/scaffold, not a provider tokenizer. Two-step totals are
**hypothetical input LOWER BOUNDS** excluding output/planner/tool/retry and do
not measure real agent decisions. Host audits never enter transmitted packets.
Protocol success and excerpt exposure do not establish semantic AU quality,
complete legal dependency, speaker interpretation or retrieval performance.

Tester owns `tests/test_selective_context_offline.py`; this module does not
write or manage that file. Independent test status is reported separately.
