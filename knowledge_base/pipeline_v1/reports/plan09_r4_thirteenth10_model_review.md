# Plan09 R4 thirteenth10 model review

Date: 2026-10-06. Producer `model:gpt-6.1-sol`, reasoning `low`; model_silver only, not Terra output, human gold or independent acceptance. Scope: exactly first10 of37 missing for099980 in frozen progress order. No target11. Source SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.

## Decisions from raw source

| # | Target | Full raw target [start,end) | Decision and boundary |
|---|---|---|---|
| 1 | at-c1baab4b25dbdf81279b1402 | [81003,81446) | AU holding, para136: late change in investigation treatment harmed fairness/legitimate hopes and warrants intervention. Does not hold applicant legally had no notice right; citation tail/next heading excluded. |
| 2 | at-c1cc43ba1d61581499bf96ef | [94341,95028) | Hard-negative procedural_history_only, para159: report purpose and allegations, not court fraud finding or jurisdiction test. |
| 3 | at-c346a3add188a66127ed9fb5 | [26768,27420) | AU fact_pattern_rule, para53: Court analysis of deception/advantage/intent, good-faith error, and advantage-supported inference. Excludes dictionary quotation; inference not conclusive presumption or applicant guilt. |
| 4 | at-c41bd6c6fd1528e62af858c6 | [29433,31679) | Two cited_commission_decision AUs, para58: false third-party references alone do not establish candidate fraud absent bad-faith evidence; section69 quoted appointment-process nexus. Exact source credit retained, no binding current-court outcome or invented suppressed reasoning. |
| 5 | at-c45b12bb6a6e0ed072ba48ac | [79635,80349) | Hard-negative procedural_history_only, para134: notice and suspicions against candidate, not proved fraud or court legal test. |
| 6 | at-c4bae0c79c06c92fb4b2d5a9 | [20694,21572) | Two cited_court procedural-rule AUs, para42 Stratas quote: broad remedy discretion/possible remittal; impartial open-minded redetermination if remitted and possible impairment by excessive merits advocacy. May disable, not automatic disqualification; remittal not mandatory. |
| 7 | at-c60115e01538c3e186265929 | [8275,8919) | Hard-negative procedural_history_only, para17: impugned agency order/transmittals, not court endorsement of general third-party sanction power. Excludes next heading. |
| 8 | at-c9c5a308ac656af5df34017b | [78592,79053) | Hard-negative fact_only, para132: case-specific hearsay/reliability/nondisclosure facts; no general hearsay ban or mandatory corroboration test. Para157 supplies separately formulated fairness rule. |
| 9 | at-cc3ed060180327fc9de7fa85 | [28041,28478) | Two procedural-rule AUs, para55: distinguish error/fraud; civil balance-of-probabilities not criminal burden. Candidate-only historical agency practice excluded, not jurisdictional limit. Para110 confirms proof context. |
| 10 | at-cdff3df736823759bcfd28d9 | [116786,117373) | AU procedural_rule, para194: Court expresses view of accused public servants knowing suspicions/defending before Commission final verdict. Preserve It-seems-to-me qualifier, fraud/Commission scope; no specified hearing form or innocence holding. |

Full targets + raw neighboring context ±1200 chars reviewed. #4 expanded51–61; #8 extra157; #9 extra110; #10 extra196. Detailed JSON persists exact primary/attribution/condition/limit/context witnesses and review trace hashes. Six positive targets contain9 AUs because #4/#6/#9 each contain two disjoint propositions;4N/0U. Raw newline-sensitive selector was corrected during preflight, before any checkpoint; no source normalization or old-artifact relabeling.

Exact primary witnesses: #1 [81003,81347), late-change limit [81176,81220), fairness/legitimate-hopes witness [81222,81301); #3 [26974,27420), good-faith condition [27204,27227), gain-evidence condition [27284,27353), inference qualifier [27354,27376); #4 badfaith [29433,29713), no-bad-faith-evidence condition [29673,29712), candidate scope [29642,29671), nexus [29765,29920), appointment-link condition [29849,29917); #6 remedies [20769,21008), allowed-review condition [20769,20823), one-remedy limit [20918,20942), impartiality [21009,21572), remittal condition [21009,21024), excessive-advocacy condition [21130,21262), may-disable qualifier [21297,21321); #9 distinction [28041,28101), proof [28102,28285); #10 [117181,117373), tentative qualifier [117181,117195), accused-fraud scope [117201,117233), final-Commission-verdict limit [117328,117372).

## Checkpoints and verification

Frozen before source review: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-thirteenth10-sol-v1.json`,483 prior artifact hashes. Exactly10 individual immutable proposal/sidecar pairs. Resume: `python -m knowledge_base.pipeline_v1.review_plan09_r4_thirteenth10`, persisted proposals reused, not next batch selection.

Pre-checkpoint decision test PASS1/1 (0.287s). Detailed validation `outputs/plan09_au_gold_v1/r4_thirteenth10_validation.json`. Checkpoint coverage332→342/369, missing37→27; effective166AU/173N/10U. Manifest rebuild PASS130records, `manifest_rebuild_changed=false`; preservation483/483; exact primary duplicates of old AU spans0. Focused R4 batches + R3 completion PASS32/32 (94.993s); full Plan09 PASS68/68 (397.945s), command: `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Completion verification and bound hashes: `outputs/plan09_au_gold_v1/r4_thirteenth10_completion_verification.json`.

Tests/contracts do not establish semantic correctness, human gold or retrieval quality. R3 acceptance remains its previous cohort only. R4 incomplete; R5=false; Plan10 locked.
