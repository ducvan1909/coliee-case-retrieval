# Plan09 R4 twelfth10 model review

Date: 2026-10-06. Producer: `model:gpt-6.1-sol`, reasoning `low`; model_silver only, not Terra output or independently accepted human gold. Scope: exactly first 10 of 47 missing targets for 099980 in frozen progress order, no eleventh target. Source SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.

## Source-grounded decisions

| # | Target | Full raw target [start,end) | Decision and boundary |
|---|---|---|---|
| 1 | at-b414c5f923125d9ffbb13318 | [115807,116258) | Hard-negative fact_only: para192 reputational harm/distress in costs context; no damages test or actual Web dissemination finding. |
| 2 | at-b4be11ef36bb42c7a0602c1c | [23369,23797) | AU holding: para46 considers respondent arguments because no applicant objection, with possible remedy/cost consequences reserved. Not universal waiver. |
| 3 | at-b50c20d6fac5a5ff45581b48 | [66109,69004) | Two cited_court procedural-rule AUs from Sopinka majority quote, para112: delegation/investigator extension; CHRC filtering rather than merits hearing, with procedural fairness still required. Disjoint primary witnesses; CHRA context, not PSEA exemption. |
| 4 | at-b69ad45bcc2f35fe4e2f2a4a | [82506,83296) | Hard-negative fact_only: para139 interview chronology, representative and oath facts; no legal oath entitlement/jurisdiction holding, heading excluded. |
| 5 | at-bb0fadd7519f573da9eaaf9e | [48582,49418) | Two statutory_hook AUs, para85: PSDPA9 appropriate discipline if wrongdoing, independently of punishment; FAA12 deputy-head discipline/termination power for public servants under authority. No automatic dismissal or Commission jurisdiction. |
| 6 | at-bcacdc4982d12ca435892d57 | [117382,118250) | AU holding: para195 public-confidence goals cannot justify unfair means used by investigator in this case. Primary only I-repeat sentence; para196 explicitly does not declare applicant innocent. No categorical email-interception prohibition. |
| 7 | at-bed335129a82eef9211c598b | [11138,11808) | AU procedural_rule: intact Rule303(2) naming of AG when no person can be named under (1), excludes earlier suppressed list. Para24 preserves conditional subsection3 substitution; no never-name-Commission rule. |
| 8 | at-bee7bffa49507d9907ed2c9b | [18439,18987) | Hard-negative party_argument_only: para37 respondent's quoted positions from another case, not court adoption of guilt/finality/reasonableness. |
| 9 | at-befd32410e3f601906b6e19a | [9440,10158) | Hard-negative fact_only: para19 other appointment-process reference facts and investigator fraud finding; not current-court applicant guilt or fraud test. |
| 10 | at-c027337ac756114775dcabdb | [64715,65101) | AU procedural_rule: para109 greater legitimate expectations for persons suspected of fraud in PSEA69 investigations than in discrimination case. Second sentence primary, no automatic specified hearing entitlement. |

All full targets and raw neighboring context ±1200 chars reviewed. #3 extra paragraphs109–113; #6 extra190–196. Conditions, limits, speaker attribution and cross-block witnesses stored as exact raw-source spans with quote/checksum. Counts distinguish 6 positive targets from 8 AUs (two each in #3 and #5); 4 hard-negatives, 0 unresolved.

Exact primary witnesses: #2 [23369,23797), condition [23380,23526), reserved-consequence limit [23639,23796); #3 delegation [66203,66790), filtering/fairness [67863,69004), threshold [68223,68307), function/statutory limit [68618,68726); #5 PSDPA [48972,49203), wrongdoing condition [49169,49202), appropriate-discipline limit [49099,49130), independent-punishment limit [49017,49066), FAA [49204,49418), authority limit [49371,49417); #6 [117910,118096), public-confidence context [117920,118006), case limit [118048,118095); #7 [11566,11721), no-person condition [11582,11647), Rule303(2) witness [11741,11767); #10 [64899,65101), PSEA69 person scope [64943,65053), comparison limit [65071,65100).

## Checkpoint and verification

Frozen batch: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-twelfth10-sol-v1.json`, frozen before raw source review; 459 prior artifacts hashed. Ten individual immutable proposal/sidecar pairs. Resume command: `python -m knowledge_base.pipeline_v1.review_plan09_r4_twelfth10` reuses existing checkpoints, not relabeling or selecting another batch.

Pre-checkpoint decision tests PASS 1/1 (0.276s). Detailed validation: `outputs/plan09_au_gold_v1/r4_twelfth10_validation.json`. Checkpoint complete: reviewed322→332/369, missing47→37; effective157AU/169N/10U. Manifest rebuild PASS, 120 records, `manifest_rebuild_changed=false`; preservation459/459; exact primary duplicates of old AU spans0. Focused R4 batches + R3 completion PASS30/30 (85.639s); full Plan09 PASS66/66 (382.778s), command: `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Completion verification and bound hashes: `outputs/plan09_au_gold_v1/r4_twelfth10_completion_verification.json`.

Contract/test PASS is not semantic correctness, human gold or retrieval-quality proof. R3 acceptance covers only its prior cohort; new R4 proposals require independent semantic review. R4 incomplete; R5=false; Plan10 locked.
