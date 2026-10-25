# Plan 09 R4 fourth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-6.1-sol` low. Producer: `gpt-6.1-sol` low; independence here means a separate review against frozen inputs and raw source, not a different model family.

## Verdict

**REJECT PENDING REVISIONS** for exactly frozen batch `p09-r4-099980-fourth10-sol-v1`: **8 agree, 2 disagree, 0 insufficient**. There are two moderate semantic disposition errors, no high/severe finding, and two required canonical changes.

The eight accepted proposal decisions contain 3 AUs and 5 hard negatives. After the recommended two corrections, the batch should contain **4 AUs, 6 hard negatives and 0 unresolved**. This remains model-silver; R5=false and Plan 10 remains locked. No canonical/global artifact was modified.

## Required corrections

1. `at-36d2799e80bf0e3f5421c6cf`: change `unresolved` to a narrowly scoped `standard_of_review` AU attributed to `current_court`. Paragraph 35 expressly characterizes third-party section 69 authority as jurisdictional, or at least a vital legal question, meriting correct PSEA interpretation. Later reservation blocks a final merits result, not this characterization.
2. `at-3bf2d5382a3dbb34d161b87b`: change `unresolved` to `hard_negative: party_argument_only`. Paragraph 62 expressly says “the applicant argues”; the court postpones assessment in paragraph 63 and does not adopt a universal personal-gain requirement.

## Other item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-2c1bd134149633afd4376e74` | agree / none | Result/roadmap is procedural history, not a reasoned authority proposition. |
| 2 | `at-2ee52523f9ffaed8ef6d78a9` | agree / none | Commission notification of judicial-review rights is reported agency speech, not current-court interpretation. |
| 3 | `at-30fcb7387e01828cdc463add` | agree / **low** | Procedural choice is non-determinative, not irrelevant or exempt from fairness. |
| 4 | `at-31fb5ee31ba428e383f369cf` | agree / none | DNR/e-mail/transmittal events do not decide interception legality. |
| 5 | `at-322488d8d16a073136576e8a` | agree / none | Potential discipline is an impact fact, not a disciplinary rule or power endorsement. |
| 6 | `at-34095952cc8f4531057b05a3` | agree / **low** | Revised report is the minimum only if the new evidence was not directly supplied, and is case-specific. |
| 8 | `at-397a79d4d287d795fed0e818` | agree / none | Employer participation facts create no universal entitlement. |
| 9 | `at-3b322354b56dc150db0ef7af` | agree / **low** | Reliance on Commission interpretation is case/definition-gap specific, not universal deference or non-reviewability. |

## Technical checks and snapshot

- Frozen batch SHA256: `ae35f022c21f8eb78a4a3cad0e881ddd98156b384e1740ffc40b88aaad5a274a`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass structural `validate_model_proposal`; all ten sidecars exactly equal recomputed checks.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target. Structural validity does not cure the two semantic disposition errors.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `f46240338ef36ad2cb6cb1fe7c44554c2ce8ff067e89e19f7849f2f72c4b06fb` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 2 | `52732d664a09606603e2573915057fbbc5ecdcac679a9f539efa729f7907bb5b` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `927499f15b7db2ba45d9e71bfbbfdd2edac0e0dee00a528dd313cebaeacd3b9e` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `da23716ed15db5462587291a2895937a1e20a4335d709a3acc4e358fe82b0da7` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 5 | `5b221d5dcb2a1cfba29e6f0035ba220fbdef4502c81271d4d2cdd4f2078a736a` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 6 | `b0668453d77374d0b44fdb2d86a5e3166fa9660939bbdb0cbdafecf0c85a8037` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 7 | `8dbdeac90041bf39e5fbc459ce1b32c201daf2ac0eca994813af682b6a804e08` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |
| 8 | `89786562d3e5529c0db488558736b77f6b423bf8f0b191ddac43a749259f9946` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 9 | `509be6d5595816c63526415604e2a043f24d022392c472681424629e8248ac04` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 10 | `2561bca425ec29a6d8a0ce441959c31a5159acdca6a7becfe975a638d6ae6a23` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |

## Concurrency boundary

Only the frozen batch, ten proposal/sidecar pairs and raw source are hash-locked. Mutable global progress and manifest are not. No canonical mutation was made.
