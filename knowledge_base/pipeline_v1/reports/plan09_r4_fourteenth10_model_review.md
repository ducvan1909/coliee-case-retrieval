# Plan09 R4 fourteenth10 model review

Date2026-10-06. Producer `model:gpt-6.1-sol`, reasoning `low`, model_silver only. Not Terra output or independent human gold. Exactly first10 of27 missing for099980, frozen order before raw source review; no target11. Source SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.

## Decisions

| # | Target | Full raw target [start,end) | Outcome and scope |
|---|---|---|---|
| 1 | at-cf6fca31c74537f0ecac83c6 | [28486,28968) | Hard-negative fact_only, para56: alleged plagiarism and agency credibility findings; next paragraph judicial confirmation not imported. |
| 2 | at-cfec9b9748dc2d026558f94e | [65110,65714) | Two procedural-rule AUs, para110: current_court post-investigation section69 satisfaction threshold; cited_court balance-of-probabilities for candidate fraud determination. Distinct speakers and non-overlapping primary spans. |
| 3 | at-d13565be34b60a161deff6f7 | [3814,4255) | Hard-negative fact_only, para9: scope of application and investigation origins, not immunity or adjudication of others' fraud allegations. |
| 4 | at-d3a8f76f09003c1f2e1b21e0 | [11816,12308) | AU procedural_rule, para24: Rule303(3) may substitute on AG motion and Court satisfaction of inability/unwillingness after naming under(2). No automatic tribunal substitution; no-motion fact excluded from primary. |
| 5 | at-d539ff9328a73bb8ffbb82cd | [64087,64706) | Two AUs, para108: procedural notice/document access; statutory protection under Canada Evidence Act5 if applicable, with tentative Charter13 observation. No blanket refusal-to-answer right, next heading excluded. |
| 6 | at-da684466af6b7841e1098b51 | [56166,56723) | AU holding, para93: reservation of definitive jurisdiction/reasonableness ruling and basis for judgment today, confirmed183–184. Not final jurisdiction failure or innocence finding. Reiterates later case-specific reservation, not a new independent legal test. |
| 7 | at-dc72e90c34d89d936cac1c43 | [61618,61968) | AU statutory_hook, para103: PSEA70(2) informal/expeditious investigations with PartII Inquiries Act powers; no exemption from fairness. |
| 8 | at-dc744de9dbcd9a3cc38eb32e | [101317,101645) | AU holding, para169: determinative omission of applicant chance to comment on final fraud analysis/conclusions before approval;173–174 confirm draft-comment issue. No universal every-draft disclosure rule. |
| 9 | at-dd5c27c6731b40e09175035c | [59368,60057) | AU statutory_hook, para98: section72 right to submissions when person's appointment/proposed appointment at issue; primary last sentence, not every investigation/third-party sanction entitlement. |
| 10 | at-ddda333f10704998d2b8ac59 | [93867,94332) | Hard-negative procedural_history_only, para158: factual-report comments/deadline and phase transition; not cure for withheld final analysis. |

All full targets and neighboring raw context ±1200 chars read; #6 expanded183–184, #8 expanded171–174. Seven positive targets contain9AUs because #2/#5 each split two disjoint propositions;3N/0U. Exact evidence, attributions, conditions, limits, cross-block refs, context and trace/checksums are persisted in detailed validation JSON.

Exact primary witnesses: #2 threshold [65195,65411), order-after-investigation condition [65195,65244), section69 scope [65136,65170), cited proof [65412,65714), candidate/investigator scope [65581,65685); #4 [11816,12238), AG-motion condition [11885,11930), inability/unwillingness-after-naming condition [11932,12070), permissive-may [11870,11883); #5 notice/access [64087,64281), summoned-person condition [64117,64150), relevant-documents limit [64241,64280), protection [64282,64602), if-applicable [64309,64322), tentative-Charter13 qualifier [64432,64501); #6 [56166,56481), today [56271,56276), Seck1 appeal scope [56449,56480); #7 [61618,61968), informal/expeditious [61729,61772), PartII scope [61881,61901); #8 [101317,101645), case fraud scope [101598,101644); #9 [59904,60057), appointment-at-issue condition [59975,60043), section72 witness [60045,60055).

## Checkpoints and verification

Frozen batch `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-fourteenth10-sol-v1.json`,507 prior hashes; frozen before raw source review. Ten immutable individual proposals plus sidecars. Resume `python -m knowledge_base.pipeline_v1.review_plan09_r4_fourteenth10` reuses checkpoints, no next batch selection/relabeling.

Pre-checkpoint decisions PASS1/1 (0.353s). Detailed validation `outputs/plan09_au_gold_v1/r4_fourteenth10_validation.json`. Checkpoint coverage342→352/369, missing27→17; effective175AU/176N/10U. Manifest rebuild PASS140records, `manifest_rebuild_changed=false`; preservation507/507; exact primary duplicates of old AU spans0. Focused R4 batches + R3 completion PASS34/34 (111.689s); full Plan09 PASS70/70 (418.396s), command: `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Completion verification and bound hashes: `outputs/plan09_au_gold_v1/r4_fourteenth10_completion_verification.json`.

Contract/test PASS is not semantic correctness, human gold or retrieval-quality proof. R3 acceptance covers prior cohort only; new R4 remains pending independent semantic review. R4 incomplete, R5=false, Plan10 locked.
