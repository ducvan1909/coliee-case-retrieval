# Plan09 R4 fifteenth10 model review

Date2026-10-06. Producer `model:gpt-6.1-sol`, reasoning `low`, model_silver only; not Terra output or independent human gold. Exactly first10 of17 missing099980 in frozen progress order; no target11. Raw source SHA256 `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.

## Raw-source decisions

| # | Target | Full raw target [start,end) | Decision and scope |
|---|---|---|---|
| 1 | at-de62131bac8ca4625cb79fa8 | [69909,70045) | Hard-negative fact_only, para114 adverse effects summary, no legal harm/damages test. |
| 2 | at-df0473b2880f2404b1ca88a9 | [99777,100403) | Hard-negative fact_only, para166 applicant affidavit manager-contact/evidentiary complaint, not adopted general duty to interview managers. |
| 3 | at-df4dc4c2e982e08f238790d3 | [42535,42834) | AU standard_of_review, para75 legal standard determination/no deference to trial judge in this area. No selection of correctness versus reasonableness for agency;183–184 reserve final outcome. |
| 4 | at-e1f04c1bf82c16c2655d1a17 | [60946,61498) | AU statutory_hook, para101 contrast section69 statutory finality/no appeal with section67 internal-revocation complaint under74. Section21 context preserves judicial review; excludes next heading. |
| 5 | at-e214e0f6df0f336908001e71 | [95539,95785) | AU holding, para161 case-specific legitimate expectation after finished sworn testimony not directly contradicted in revised report. No immunity or absolute rule against reopening. |
| 6 | at-e297aa3d761f69aa6a477a62 | [31687,32221) | Hard-negative procedural_history_only, para59 report-production request and respondent objections, not adopted Rule317 production threshold. |
| 7 | at-e37c726311667f70ed6bc96a | [95794,98115) | Hard-negative fact_only, para162 Cousineau late email/disputed recollections, not Court adoption of facts or general admissibility rule. |
| 8 | at-e72eaee9971b824c3f1eeb46 | [77458,78103) | Hard-negative fact_only, para130 credibility and delayed-knowledge findings, not reusable legal rule or innocence adjudication;196 context expressly disclaims innocence ruling. |
| 9 | at-ea2ca4b59d16cea823f1ead2 | [547,1026) | Two statutory_hook AUs, para2 section29 in-principle appointment authority and sections66–73 supervisory jurisdiction. Historical delegation read but excluded from primaries; no final independent third-party sanction power. |
| 10 | at-eab531eaedf6a1d8fdd7899c | [120094,120755) | Two holding AUs, para199 fee exclusions and $12,000 case-specific costs with conditional unpaid-$650 deduction/payable forthwith. No universal tariff; award reiterated in formal judgment, not semantically deduplicated proof. |

Read all full targets and neighboring raw context ±1200 chars; #3 extra183–184, #4 extra21, #8 extra196, #10 extra190. Five positive targets contain7AUs due disjoint #9/#10 propositions;5N/0U. Detailed JSON stores exact source/speaker/condition/limit/cross-block witnesses, contexts and trace/checksums.

Exact primary witnesses: #3 [42535,42834), section69-jurisdiction scope [42613,42695), trial-judge scope [42802,42833); #4 [60946,61448), section67 internal-revocation condition [61096,61190), section69 limit [61013,61029), Tribunal scope [61268,61300); #5 [95539,95785), finished-testimony condition [95656,95693), no-direct-contradiction condition [95694,95784), circumstances qualifier [95539,95562); #9 appointment [547,728), in-principle qualifier [547,559), public-service scope [654,690), supervision [839,1026), sections66–73 witness [884,925), appointment scope [960,1025); #10 exclusions [120094,120464), not-this-application limit [120213,120283), dismissed-motion limit [120367,120446), award [120465,120755), unpaid650 condition [120701,120754), case-specific reasonableness [120529,120552),650-deduction witness [120639,120699).

## Checkpoints and verification

Frozen before source review: `outputs/plan09_au_gold_v1/r4_batches/p09-r4-099980-fifteenth10-sol-v1.json`,531 preserved artifact hashes. Exactly10 immutable individual proposals plus sidecars. Resume `python -m knowledge_base.pipeline_v1.review_plan09_r4_fifteenth10` reuses existing proposals, no relabeling/next-batch selection.

Pre-checkpoint decision test PASS1/1 (0.260s). Detailed validation `outputs/plan09_au_gold_v1/r4_fifteenth10_validation.json`. Checkpoint coverage352→362/369, missing17→7; effective182AU/181N/10U. Manifest rebuild PASS150records, `manifest_rebuild_changed=false`; preservation531/531; exact primary duplicates of old AU spans0. Focused R4 batches + R3 completion PASS36/36 (125.531s); full Plan09 PASS72/72 (444.917s), command: `python -m unittest discover -s knowledge_base/pipeline_v1/tests -p "test_plan09*.py"`. Completion verification and bound hashes: `outputs/plan09_au_gold_v1/r4_fifteenth10_completion_verification.json`.

Contract/test PASS is not semantic correctness, human gold or retrieval proof. R3 acceptance remains prior cohort only. R4 incomplete; R5=false; Plan10 locked.
