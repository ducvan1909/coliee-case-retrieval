# Isolated offline sequential variants

Implements Main's plan20. No network, inference, training, model downloads or
production runtime changes. KOS is loaded only after policy/order/packet and
all budget selections have been frozen and materialized. It is reference, not
formal gold; structural checks cannot establish semantic AU quality.

```powershell
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.region_priority_variants --stage order
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.region_priority_variants --stage context --order-report knowledge_base/pipeline_v1/outputs/region_priority_variants_20261013/order/report.json
```

Default outputs are the new `order/` and `context/` children. Nonempty stage
directories are refused; use `--output-root` with a new directory for repeats.
Main's files at the parent root and original report are preserved.

Stage 1 retains the exact rebuilt original 431-block inventory and features,
packets, serialized cost and control schedules. The global order uses tier3
for review, duty with rights/standard/qualification, or fact+consequence+rationale;
tier2 for doctrine>=2/application>=3/reported_authority>=2; tier1 any other
nonzero lane; otherwise tier0. Within tiers use the original saturated
citation+standard+duty+reporting score descending, then case and source offsets.
No benefit/cost ranking, round robin, additional features or KOS/query scoring.

Stage 2 validates Stage 1 report, inventory, policy/code fingerprints, target,
features, original input identity and full order. It expands baseline nearby
atom hints to containing blocks on qualification/reporting/open-quote cues,
and scans target plus seed context for at most one explicit owned paragraph
reference hop. Only unique opening markers of validated `numbered_paragraph`
blocks are addresses. External/ambiguous/quoted/reported references stay
unresolved; explicit unquoted current narration may overcome a reporting cue
elsewhere in the supplied segment. Ownership is lexical and conservative;
every dependency remains an unconfirmed legal hint. Fetched blocks never seed
another hop. Context admission gives whole owned references priority over
whole neighbors and old hints, unions spans and subtracts target, with 6000
character/12 interval caps and no truncation. Cap residuals stay unknown.

Every arm uses absolute budgets floor(247339 × 10/25/50/75/100%). Sensitivity
bytes/3 and bytes/5 changes incurred cost at these same absolute budgets.
Controls use old packets; original/new-context variants share the full locked
order but may select different sets due only to serialized cost. Selection
retains the original scan-and-defer behavior, so a budget selection is a
subsequence, not necessarily a prefix. Both selected sets receive matched
original/new-context comparisons on exactly the same targets.

Renderer and scaffold are unchanged. Existing context `reasons`, IDs, hint
status and role are transmitted and counted; context audits, reference
resolution details, policy/rank/KOS metrics are host-only and excluded from
cost. Repeated context is billed per request. Tokens are ceil(UTF-8 bytes /
divisor), not actual tokenizer/billing. No semantic dependency, speaker
interpretation, qualified-evidence acceptance or model quality is asserted.

Testable APIs: `priority_order(inventory)`, `rank_reason(row)`,
`schedule_order(inventory, ordered_ids, budget=..., bytes_per_token=...)`,
`expand_context(inventory)`, `verify_order_report(path, inventory, lock)`,
`run(stage=..., output_root=..., order_report=...)`. Tester owns test files and
independent reviewer probes. JSON includes inventory, locks, full ranks,
frozen selections, per-AU first-open events, per-case/category coverage,
NA denominators, cost residuals and input-only reference delivery proxies.

## Executed local checkpoint

Current code reports are `order/revision01/report.json` and
`context/revision01/report.json` under the default output parent. First
snapshots remain immutable. The revision fixes an ownership guard omission:
present-tense external reporting (`says`) and parenthesized citation years
cannot silently establish current-case ownership. Ranking/features were not
changed or tuned. Stage 2 refuses the older code fingerprint.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_region_priority_variants -v
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.region_priority_variants --stage order --output-root knowledge_base/pipeline_v1/outputs/region_priority_variants_20261013/order/revision01
.\.venv\Scripts\python.exe -m knowledge_base.pipeline_v1.region_priority_variants --stage context --order-report knowledge_base/pipeline_v1/outputs/region_priority_variants_20261013/order/revision01/report.json --output-root knowledge_base/pipeline_v1/outputs/region_priority_variants_20261013/context/revision01
```

Executed: 14/14 regression tests OK (0.007 seconds). Both revision CLI runs
exit 0; protocol gates pass, at 9.799/31.801 seconds respectively. Stale lock
negative check exits 1 as intended. Main's eight preservation hashes match.
No inference/network calls; independent tester acceptance remains separate.

At budgets 10/25/50/75/100%, global-order full TARGET reference counts are
7/11/17/18/18 of 18. Cue-control is 9/13/15/16/18. Thus the global order does
not dominate cue-control at every budget. Changed context gives
6/9/16/18/18 TARGET and 6/7/14/17/18 CONTEXT. Exhaustive new packet cost is
277098 versus baseline 247339 estimated tokens/4. At the 50% baseline-selected
target set, added context costs 18581 estimated tokens/74311 bytes; repeated
context rises from 42274 to 70329 characters. These are delivery/cost facts,
not model quality or qualified-evidence improvement.

Known probe gap: original `045155` paragraph `[21]` supplies only the trailing
suppression atom of `[20]` at `[25693,25718)`, not its paragraph-5 reference
at `[25662,25673)`. Existing target features have no qualification/reporting/
open-quote trigger, so frozen expansion does not reach `[5]` from that packet.
This contradicts the assumption that the original packet already supplied
the reference sentence. No case-specific rule or additional cue was added
after evaluation. Ownership hint counts are 2 resolved, 0 open, 269 unresolved;
unannotated dependencies and semantic completeness remain unknown.
