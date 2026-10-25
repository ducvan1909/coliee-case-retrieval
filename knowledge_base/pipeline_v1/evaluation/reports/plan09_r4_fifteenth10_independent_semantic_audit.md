# Plan 09 R4 fifteenth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-6.1-sol` low. Producer: `gpt-6.1-sol` low; independence here means a separate review against frozen inputs and raw source, not a different model family.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-fifteenth10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 7 AUs, 5 hard negatives and 0 unresolved. All five positive targets have low-severity scope qualifications. **No severe findings** and no canonical correction are required.

These records remain model-silver, not human gold. R5=false and Plan 10 remains locked. No target outside fifteenth10 was audited and no canonical/global artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-de62131bac8ca4625cb79fa8` | agree / none | Adverse-effects summary is factual, not a legal harm or damages test. |
| 2 | `at-df0473b2880f2404b1ca88a9` | agree / none | Applicant affidavit is witness evidence, not a universal manager-interview duty or proof rule. |
| 3 | `at-df4dc4c2e982e08f238790d3` | agree / **low** | No deference is owed to the trial judge on this legal standard question; the passage does not finally choose the agency's review standard. |
| 4 | `at-e1f04c1bf82c16c2655d1a17` | agree / **low** | Section 69 lacks the statutory appeal/Staffing Tribunal route contrasted here; judicial review remains available. |
| 5 | `at-e214e0f6df0f336908001e71` | agree / **low** | Legitimate expectation is tied to finished sworn testimony and no direct contradiction in the revised report, not immunity or an absolute anti-reopening rule. |
| 6 | `at-e297aa3d761f69aa6a477a62` | agree / none | Production-request history does not establish a Rule 317 threshold. |
| 7 | `at-e37c726311667f70ed6bc96a` | agree / none | Late e-mail and recollections are quoted facts, not adopted truth or an admissibility rule. |
| 8 | `at-e72eaee9971b824c3f1eeb46` | agree / none | Credibility/delayed-knowledge findings remain case facts and do not decide innocence. |
| 9 | `at-ea2ca4b59d16cea823f1ead2` | agree / **low** | Two disjoint statutory AUs preserve the in-principle and appointment-scope limits; broad supervision does not resolve third-party sanctions. |
| 10 | `at-eab531eaedf6a1d8fdd7899c` | agree / **low** | Two adjacent non-overlapping costs AUs preserve exclusions, case-specific $12,000 award, immediate payment and conditional unpaid-$650 deduction. |

## Technical checks and snapshot

- Frozen batch SHA256: `f233b80a8db43ecd42ad9b4df7f3f09a6a7b4c507ce4542e2832677d8ae2b3f0`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; all sidecars exactly equal recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target; duplicate guards remain active.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `15af98a2cf86523f7c7047a1aa88519d2856fe6997141ec26b1a695f27d0cca3` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 2 | `67ed4f3d7c95f52b28fa6c8e99e9ca229b5bf3127f9721fb6de210b9e7447ee8` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `9825ca5579f633fca7c1d45ceb3f7a465e44bad6196ddfea81b285cc302d4fe8` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `410732e065289d08e64233470b47942a1dda829de3636abe623ea3b400aabce6` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 5 | `ba3dafc73b632ad889ccbb4192a758e65fa3704afd08eb07952c0bd8aa46c7d3` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `92d8166b310ad686d6ce49481cc0c892d571faf4a96d44dcceed0c10ed09760b` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 7 | `1639eceaea7f59237e25b60cfe0413cf2f235444e9f85c49dfd32167c8a398e0` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 8 | `64bc74412b9edca4d5c5beee3a8ec8ef9a627df77628c45e4bf2ee0d7d29d9b4` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 9 | `dde94ea8fb77892599a1804ebc3653d94571fd040b5b1fefb7128d0244fae86a` | `cf4d0f507764d4e8868ee9aac052048b9fa892084a8c82b43beb0e647a7b68b4` |
| 10 | `3bedf8e499dd3e58e799bd4cf0685042397e9cf227ca55bdd6d15e477d91453e` | `cf4d0f507764d4e8868ee9aac052048b9fa892084a8c82b43beb0e647a7b68b4` |

## Concurrency boundary

Mutable global progress and global R4/model-proposal manifest were not hash-locked. Registry access was limited to ownership verification. Later appends elsewhere do not alter this frozen snapshot.
