# Plan 09 R3 final re-audit: positions 11 and 32

Date: 2026-10-05  
Reviewer lane: independent model-only (`gpt-5.6-sol`, low). Results remain model-silver.

## Verdict

**PASS — independently accept both revisions.**

- Position 11: PASS.
- Position 32 / P09-S01: PASS.
- The accepted position-32 amendment and this independent acceptance report provide the resolution references required for the coordinator/implementation agent to close P09-S01 under the existing contract.
- This audit does not itself modify the registry, close P09-S01, unlock Plan 10, or evaluate the 157 missing targets.

## Locked snapshot

- Queue SHA-256: `6de97d57237c37ae49a9132b3f430c9a237cc553825e9822f2e4ce86a510f502`.
- Registry SHA-256: `3b9df0c098931b791b1f25443e35fdb37fc86a7d6b879ee37f76e49bee20a407` (`P09-S01.status=pending_reaudit`).
- Two review-head manifest SHA-256: `1f3d97d622966d100f1eebf8df137ab0d27710fe54c556dbb6d911b36905778f`.
- Two amendment-head manifest SHA-256: `5cac2368d57565b886b95a88e45c82e6e741320ba81793378a62a018ea207a16`.
- Raw-source manifest SHA-256: `943ca024ca70bb3ddb7e35d66396bfeb94ce7b7947d545bb356f2e2c3c0c9576`.

All hashes were recomputed after report creation and remained unchanged.

## Position 11 — accepted

- Target: `011904 / at-a5b5b0fdf3bab9574aa4429e`.
- Review head: `p09-r3-audit-11-32-11-gpt61sol-v2`, SHA-256 `0a5625dac7fc29247ebaac1e8b1c4e9c160ffd1b967327b794024daeb7a1a500`.
- Amendment head: same ID, SHA-256 `2b98a6bf9ec41f425f059f7b3155401da9ba1fc3399ea221c5e13b94e3d03ccc`.
- Raw source: SHA-256 `c2bc7c0944a5ee103368055f7d2f0e3c260d4bb8336d406c3d01733304c96b12`.

The effective AU changes only semantic kind from `holding` to `procedural_rule`. The following fields are byte/structure-identical to the original AU: claim, owner, evidence, attribution, condition/exception/limit arrays, cross-block refs, overlap disposition and duplicate marker. The claim “State-protection analysis must assess whether protection is effective” is supported by raw `[14358,14826)`. `current_court` is correct: the Board is the decision-maker being assessed, not the speaker.

## Position 32 / P09-S01 — accepted

- Target: `013948 / at-3f8c7b00587a03395a1070fa`.
- Review head: `p09-r3-audit-11-32-32-gpt61sol-v2`, SHA-256 `4bbf553bc8e1f8b07bdb6cdc33b0ea92b42b22ce1abea4679494c9efe71f85bc`.
- Amendment head: same ID, SHA-256 `e0bfa89f753461f02fe6f0d8f4704f66da7cf92300aff3a855363f6a3259bc08`.
- Raw source: SHA-256 `1571876439f11252edacb5b893c7538e1f7a29c2b47245ded2633f3de1114352`.

The effective AU is narrowly scoped:

- claim: “The Board never ruled on Mr. Bayavuge's risks of return”;
- kind: `holding`;
- speaker: `current_court`;
- primary proposition and attribution witness: exact standalone heading `[11890,11945)` only;
- cross-block support: five exact spans for paragraphs 35–39 (`[11953,12084)`, `[12092,12474)`, `[12482,12755)`, `[12763,13024)`, `[13032,13231)`).

Every proposition, attribution and cross-block span starts at or after 11890. Paragraph 34's party submission `[11460,11888)` is absent from all AU evidence and witnesses. The claim does not generalize beyond what the heading and paragraphs 35–39 establish: the Board had not decided this applicant's personalized return risk under section 97.

## Lineage and validation

- Position 11 review v2 points to review v1 hash `d7a2185379912087724663bb9127f409090b2091a2f9815f4e54a23c10b27096`; its first amendment does not fork an earlier amendment.
- Position 32 review v2 points to review v1 hash `e0c7f26b5c262660a711419df3665e47a122d47c823839610cb1a6764e0072a2`.
- Position 32 amendment v2 points to amendment v1 hash `2794e393f66c5984571e7ac18cfca859dc846692759ffa7b588c9883468d6102`.
- Both review heads and both amendment heads validate; no overwrite, fork or cycle was detected.
- Focused revision/head tests: **7/7 PASS** in 45.828 s.
- Read-only verifier: `PASS heads=49 amendments=42 history=unchanged counts=98/113/1 missing=157 snapshot=consistent S01=pending_reaudit Plan10=false`.

## Coordinator closure references

For a contract-compliant P09-S01 registry closure, the coordinator may use:

- `resolution_amendment_id`: `p09-r3-audit-11-32-32-gpt61sol-v2`;
- `independent_review_ref`: `evaluation/reports/plan09_r3_positions_11_32_final_reaudit.json`;
- disposition: accepted final positive `holding/current_court`, model-silver only.

The coordinator must still perform and validate the registry transition. This report is not that transition.

