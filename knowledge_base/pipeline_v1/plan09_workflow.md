# Plan 09 workflow

Build blank packets and readiness artifacts:

```powershell
python -m knowledge_base.pipeline_v1.au_gold build
```

Render one target from exact source:

```powershell
python -m knowledge_base.pipeline_v1.au_gold render-task --case-id 013009 --target-id <target-id> --output review-task.html
```

The CLI also provides `validate-submission`, `compare-submissions`, `create-adjudication`, `apply-adjudication`, `lock-gold`, `validate-model-proposal`, `lock-silver`, `score`, and `select-few-shot`. Mutating commands write JSON/HTML files; terminal output is only a short path/status notice.

Current readiness is intentionally split:

- `structural_ready`: blank KOS-5 packets and tools are ready;
- `silver_ready`: false until real Terra proposals are executed and host-validated;
- `gold_awaiting_independent_adjudication`: no independent human gold exists;
- held-out source contract: dependency missing for the pilot 60-case corpus;
- Historical structural readiness and frozen R3/R4 progress keep their original closed gates.

Terra execution is batch/checkpoint based. Do not write a whole-packet abstention merely to mark work complete: each target record needs the source/region review trace and a concrete decision or unresolved reason. Report actual reviewed/proposed/unresolved counts from completed checkpoints only.

Semantic remediation is specified in `../design/pipeline_redesign_lynx/12_plan09_semantic_remediation.md`. The required order is quarantine known severe findings, build an attribution-risk queue offline, review through immutable amendments, resume missing targets, and run independent semantic audit. A complete target count or schema-valid output does not by itself unlock Plan 10.

## Revisioned R5 acceptance and P09-R6 use decision

`reports/plan09_model_silver_progress.latest.json` is a frozen historical structural
snapshot referenced by coverage hashes, not the current development authorization.
Do not overwrite it to change a gate. The current R5/R6 revision is
`reports/plan09_model_silver_progress.r5_r6.v2.json`; consumers must first call
`au_gold.r5_acceptance.validate_development_gate()` (fail closed on changed data,
audit, implementation or test evidence). It binds `r5_acceptance.v1.json` and
`r6_use_decision.v1.json` in `outputs/plan09_au_gold_v1`.

Publish only after local focused and full Plan09 tests PASS:

```powershell
python -m knowledge_base.pipeline_v1.accept_plan09_r5 tests
python -m knowledge_base.pipeline_v1.accept_plan09_r5 publish
python -m knowledge_base.pipeline_v1.accept_plan09_r5 verify
```

The accepted scope is `plan10_allowed=true` for **baseline development only**,
with `evaluation_against=model_silver`, `semantic_gold=false`, `human_gold=false`.
This is not authorization to execute Plan10, not an independent retrieval-quality
estimate and not a mixed-model silver lock/export implementation. Keep all eight
unresolved items and disclose all 17 historical Terra missing validation sidecars.
Historical audit findings, proposals, tests/results and closed gates are preserved.
