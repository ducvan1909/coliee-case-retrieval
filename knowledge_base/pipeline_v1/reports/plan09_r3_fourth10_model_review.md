# P09-R3 model review: queue positions 31–40

Reviewer: `gpt-6.1-sol`, model-only/model-silver. Scope: exactly the next ten pending risk items after thirty reviewed items; all ten are case `013948`. No prior risk-review head is reprocessed and none of the 157 missing targets is annotated. Raw UTF-8 source was reopened with `open_source`; complete targets and 850 characters of context on each side were reviewed without character normalization.

| Position | Exact target ID | Decision | Source evidence / refinement |
|---|---|---|---|
| 31 | at-726483a83077ee92addf3aff | amendment | Paragraph 28 explains written-assessment process. Set procedural_rule, preserve positive-risk gate and negative-risk rejection limit; separate court explanation from quoted Manual voice. Paragraphs 25–30 supply regulatory/application context. |
| 32 | at-3f8c7b00587a03395a1070fa | unresolved | P09-S01: paragraph 34 party submission is followed by a court-response heading. Paragraphs 32–39 confirm a speaker boundary but not a single clean AU for the combined target. Preserve unresolved using a new v2 amendment linked to the existing unresolved head/hash. Do not close quarantine. |
| 33 | at-286fc0f30a53d4bce2eeb5c3 | amendment | Paragraph 20 states the evidence-record rule, then introduces an issue question. Remove the question from the claim/evidence, set procedural_rule and preserve the evidence-before-decision-maker limit. |
| 34 | at-329c7590de0a0f2cb690f50c | amendment → hard negative | Paragraph 18 under PRRA OFFICER’S DECISION reports the administrative rejection reasons. The entire target is procedural history, not a reviewing-court holding; ANALYSIS starts only afterward. Full-target `procedural_history_only` is recorded. |
| 35 | at-3afd82f9ffea744294fd4624 | amendment | Paragraph 41 is a case-specific consequence of no Board inclusion finding. Set holding, record that condition, and exclude the following missing-evidence heading from the AU. |
| 36 | at-7544c78cf589f672a909022b | amendment | Paragraph 42 specifies an evidentiary obligation, with burden explained in paragraph 43. Set procedural_rule rather than citation-driven statutory_hook; record the section-97-risk purpose condition. |
| 37 | at-4b45893be1af385679d8c79a | amendment | Paragraph 50 is court reasoning about this applicant onus to submit prior Board evidence in PRRA. Preserve holding and exact If condition. Paragraphs 48–51 explain the missing submission. |
| 38 | at-a323323de17b57ed9f104642 | keep | Paragraph 51 expressly states the court conclusion that this officer need not search this applicant immigration file. Paragraphs 49–52 distinguish unsubmitted evidence from awareness of the Board decision. |
| 39 | at-ba8ab2cc049d5dbf250b0516 | amendment | Paragraph 49 supports court reasoning on evidence not submitted in PRRA. Preserve holding; add submission condition and no-proof-of-file-availability qualification. |
| 40 | at-3d0be6036210c5ff292aecc6 | amendment | Paragraph 31 resolves written assessment, then appends the next issue heading. Narrow holding/evidence to the resolved point, remove the question and preserve paragraph 30 negative-risk premise as an exact condition witness. |

Review refs: `outputs/plan09_au_gold_v1/risk_reviews/p09-r3-fourth10-{position}-gpt61sol-v1.json`. Changed decisions link matching immutable files in `model_amendments/`. Their exact source/proposal hashes, target offsets, reasons and ten concrete refs are in `outputs/plan09_au_gold_v1/remediation_r3_fourth10_validation.json`.

Item 32 is the first risk-review checkpoint for that pending target, not a re-review of one of the prior thirty risk heads. Its pre-existing P09-S01 amendment is superseded explicitly by ID/hash using amendment schema v2; the old amendment bytes and severe registry finding remain unchanged. No acceptance or closure is inferred from the new checkpoint. All other prior proposal, review and amendment bytes are preserved.

Batch outcomes: **1 keep, 8 amendments, 1 unresolved**. Of the eight amendments, one replaces a positive AU with a reviewed hard negative. The unresolved item was already unresolved in the effective overlay, so it is not a newly unresolved target.

State: **40 model-reviewed pending independent audit / 9 pending model review**, 49 queue items total. Effective counts: **97 AU / 113 hard negatives / 2 unresolved**. Coverage remains **212/369**, with the same **157 missing IDs**. P09-S01 remains quarantined; Plan 10 remains locked.

No independent semantic audit is run in this batch. Model decisions, exact-span validation and regression tests do not establish semantic gold or independent acceptance.

Verification: **27/27 related tests PASS** in 102.687 seconds across fourth-batch, revision-history, risk-review, remediation and Plan 09 tests. All ten new records and nine linked amendments pass validation, including P09-S01 v2 lineage. Effective queue/progress reproduce exactly; old proposal/review/amendment bytes and all missing IDs remain unchanged. CLI validation of item 32 passes and is recorded in `remediation_r3_fourth10_cli_validation.json`. No new independent semantic audit or full unrelated pipeline test run was performed.
