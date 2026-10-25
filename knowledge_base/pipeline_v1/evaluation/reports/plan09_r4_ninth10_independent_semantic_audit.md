# Plan 09 R4 ninth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-5.6-sol` low. Producer: `gpt-6.1-sol` low.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-ninth10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 7 AUs, 3 hard negatives and 0 unresolved. Items 1, 3, 7, 8 and 9 have low-severity qualifications. **No severe findings** and no canonical correction are required.

These records remain model-silver, not human gold. R5=false and Plan 10 remains locked. No target outside ninth10 was audited and no canonical/global artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-85da5a3bc284d68445e19c26` | agree / **low** | Precedent sufficiency is conditional on evidence-analysis/PSEA interpretation without a genuine jurisdiction issue. The target does not name the exact standard and does not resolve the live dispute. |
| 2 | `at-85f5879a84c34e2201fc207f` | agree / none | Paragraph 197 is institutional/costs rhetoric, not a duty to consent or automatic costs rule. |
| 3 | `at-867e2531fb535451e4d16e4d` | agree / **low** | Amicus-like objective guidance is supported, but it is not literal appointment or unrestricted advocacy. All role conditions and later constraints are preserved. |
| 4 | `at-86db1baf17aae56596742d23` | agree / none | Paragraph 64 is notice and appointment history, not jurisdiction or fraud adjudication. |
| 5 | `at-8733e4b4d14fe59b3f2f3eec` | agree / none | Paragraph 167 directly rejects no prejudice for this approach/applicant. |
| 6 | `at-889ec63c9b2044652d7bc22f` | agree / none | Mission-statement values are not independently enforceable court law; paragraph 105 owns the legal norm. |
| 7 | `at-89b21721fd80d67c69db253b` | agree / **low** | Deputy-head investigation/hearing and applicable procedures are supported. A grievance only may be referred; adjudication is not guaranteed. |
| 8 | `at-8e0a98db1c36c55a5caa9a12` | agree / **low** | “Too little, too late” is a case-specific cure finding constrained by date, groundwork and circumstances. |
| 9 | `at-8edbbc3df5180b14d919415d` | agree / **low** | Attribution is correctly `cited_court`; this is historic Dunsmuir recitation, not a 2026-current-law claim or final case standard. |
| 10 | `at-8f23d518e0197e14ac57c53f` | agree / none | The even-if assumption is preserved; the court does not adopt the respondent's unchanged-mandate assertion. |

## Technical checks and snapshot

- Frozen batch SHA256: `eb223c0ad465b7f5398c0af5e562979c3a0d5acef4fd191a64d89f6be2c4e55e`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; exact source, spans/quotes, region identity and trace checksums revalidated.
- All ten sidecars exactly equal recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target; duplicate guards remain active.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `e260aed1caea7debfae65f468f1d3e811893b2444642158157ce4863f101c7b8` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `d8fb22bc92c9a073497732dedc2fda55df18235a11cf36f144e8db6dda344b49` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `ae1f2672af62b7065b3dbab0a92824f323f5735ebfc30f3a5556d68f3baebcef` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `d36182e47d0894190f5de5938dd4ff03cb27357adfb0e8726c804836d886c44c` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 5 | `9a07b7e629eb6a03465a1afb2a6ed7440633bc8d9ab9922da79a4c4eab21e145` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `64347586d0533a829efdc2c0d94467179ab281a0355ab3450798d8d45b35572d` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 7 | `0558fca0709864552baca4cd64e39e8d16f9b50b5d8fd4cdae84cd06e5dfad6a` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 8 | `c1fc740bbbe2e32739be28723c182fee0f02909ce7a4d0c691f6b6fa05d03c81` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 9 | `df3d0ece4b5dbd9b720b8291b16df2d2d455ca7566e75ca503abe928c68c7292` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 10 | `70a53ff5ab4d703aae46628ff96bb245f2c25dc447e2e4841c3ed16270aded08` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |

## Concurrency boundary

Mutable global progress and global R4/model-proposal manifest were not hash-locked. Registry access was limited to ownership verification. Later appends elsewhere do not alter this frozen snapshot.
