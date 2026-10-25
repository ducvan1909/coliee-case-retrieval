# Plan 09 R4 sixth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-5.6-sol` low. Producer: `gpt-6.1-sol` low.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-sixth10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 7 AUs, 2 hard negatives and 1 unresolved. Items 2, 3, 4 and 9 have low-severity qualifications. **No severe findings** and no canonical correction are required.

These artifacts remain model-silver, not human gold. R5 remains false and Plan 10 remains locked. No target outside sixth10 was audited and no canonical artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-4d1f2de7b9825c4769503ecd` | agree / none | Paragraph 97 directly states that fairness content varies with context. The exact limit is retained and the Baker list is not duplicated. |
| 2 | `at-53b9e5a98f7f48d4d0b6edeb` | agree / **low** | Paragraph 116 supports the case-specific holding. Qualification: this concerns the final June 10 analysis/findings report before approval, not every investigative document. Exact limits and paragraphs 173-174 confirmation are present. |
| 3 | `at-5504fe5bd31f8b96cf578894` | agree / **low** | The Baker-factor list is correctly captured. Qualification: the list alone does not establish speaker/adoption; the preceding court introduction is an indispensable exact attribution witness and is recorded. |
| 4 | `at-5ae776a11ff4273a21d10c5e` | agree / **low** | Paragraph 25 assumes non-representation and states only a hypothetical conflict. `fact_only` is plausible, but unresolved safely avoids inventing actual concurrent representation or an adjudicated conflict. |
| 5 | `at-5b314a4af85452a367b6930c` | agree / none | Paragraph 84 accurately paraphrases paragraph 69(a)'s appointment remedy. It does not decide independent third-party corrective-action power. |
| 6 | `at-5d005ab7046f40f4effbf4c6` | agree / none | Paragraph 96 explicitly applies correctness to procedural fairness. It is not a jurisdiction/reasonableness standard. |
| 7 | `at-5e5b91a4b13687e831ba0418` | agree / none | Paragraph 181 is judicial rhetoric, not an operative remedy or reusable test. |
| 8 | `at-5ec7836e659f3030d36f47ac` | agree / none | Paragraph 190 is a current-court increased-costs holding. Exceptional circumstances, ordinary default and discretion factors are preserved. |
| 9 | `at-604adea56602fb87307c1f7d` | agree / **low** | The section 69 text, thresholds and remedies are exact. Qualification: attribution must remain `statutory_text`; it is not a holding validating independent sanctions against this third party. |
| 10 | `at-61be17d6a14ab52741a7c2a4` | agree / none | Paragraph 165 is factual investigation incompleteness, not a universal interview duty. |

## Technical checks and snapshot

- Frozen batch SHA256: `329398b85606d874645d91e7528c6c9a930aac050ce8e94b89cee8fc31f047ab`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; exact source, half-open spans/quotes, region identity and trace checksums revalidated.
- All ten sidecars exactly equal freshly recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found exactly one owner per target. Checkpoint and rebuild paths reject duplicate ownership with `checkpoint_duplicate_target`.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `36dbed25c2a77b273c533f1ac1b6f2372a094ee0d31e38e7ada9cc1b58ca7ec0` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `f8354407e24f6ebb937fe49883eb0e6a0c66836254097f6e0a09de7544b216ec` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 3 | `4eb7ddc884ca21074b5c169a1dd1ec4a18ae61886054396bf95ecc17a9cd5648` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `541615014ad760455204a04543b0977572e1daca9ae00574d54163a76e2d9912` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |
| 5 | `56cb8eb572d76753feb04610b74950aac1daa202e10cc8dfac10ccac50204d4d` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `733d19f8947098d93621a35cdea5fac46522a06a58bd2af3a12559bc7246ce5a` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 7 | `db993025e203a550d33e2cfda403ccc64fffaa7a480219e16f7a45afb7f99f2a` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 8 | `05b4d979232af983c4fc833a519b73c7968769d1501e2aa81eadc65ada62e28b` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 9 | `f8ffe4db5e60973d926df17fef1ddb4b78c11541f8e745d261c9d5a7d474b748` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 10 | `a28c8af943556a2277b2c822f50aebb9665032cab73aba0bcd3ab87aa2a1701e` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |

## Concurrency boundary

Mutable global progress and global R4/model-proposal manifest were not hash-locked. The registry was read only for ownership. Later appends elsewhere do not alter this frozen batch/checkpoint/sidecar/source snapshot.
