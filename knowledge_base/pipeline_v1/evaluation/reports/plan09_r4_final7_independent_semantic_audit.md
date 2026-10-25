# Plan 09 R4 final7 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-6.1-sol` low. Producer: `gpt-6.1-sol` low; independence here means a separate review against frozen inputs and raw source, not a different model family.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-final7-sol-v1`: **7 agree, 0 disagree, 0 insufficient**; 5 AUs, 4 hard negatives and 0 unresolved. Items 1, 5 and 7 have low-severity qualifications. **No severe findings** and no canonical correction are required.

These records remain model-silver, not human gold. Final7 completes mechanical R4 coverage, but R5=false and Plan 10 remains locked. No target outside final7 was audited and no canonical/global artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-ee2e12aeef17269d91410e7e` | agree / **low** | Greater protection is cited-court authority under a differently worded former scheme similar to sections 66/67, not a universal section 69 hearing entitlement. |
| 2 | `at-f71923e1a0ac847eaf65fdcc` | agree / none | Counsel praise/institution criticism is editorial, not immunity or professional-liability law. |
| 3 | `at-f84bcbf2e61c72f291935ac4` | agree / none | Other agency decision/order history is not judicial validation or a sanction rule. |
| 4 | `at-f9b94a5e5fb3e05554f4c167` | agree / none | Applicant arguments and conditional consequences are not adopted holdings in this target. |
| 5 | `at-f9be712086516d8fe612b889` | agree / **low** | Regulation 19 description comes from investigator correspondence. Disclosure remains discretionary and conditioned on public-interest/privacy balancing plus consultation if contemplated. |
| 6 | `at-fefd2e4233313a501663cb35` | agree / none | Report transmittal and an expressly reserved mother-interview question establish no universal interview rule. |
| 7 | `at-ffb5c4acb13eda43b742abd3` | agree / **low** | Three adjacent, non-overlapping PSDPA duties correctly preserve distinct actors and scopes: Minister, Treasury Board and chief executives. |

## Coverage completion check

- Frozen batch `before_progress` contained exactly these seven missing IDs in the same order: reviewed 362, missing 7.
- Hash-locked `r4_coverage_completion.json` reports expected 369, reviewed 369, missing 0 and canonical duplicates 0.
- Exact expected case-target set and all-case completion flags are true.
- The artifact remains model-only: `semantic_gold=false`, `independent_acceptance=false`, `r5_pass=false`, `plan10_allowed=false`.
- Therefore 369/369 proves coverage completeness, not semantic gold or R5 acceptance.

## Technical checks and snapshot

- Frozen batch SHA256: `346f17e0d97eed5f93fb1ea4a3c750b49549ce9b62a13c00e07107e78c511eb2`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- R4 coverage artifact SHA256: `43589294d6b273aa777f1be49f364fda51aab1555462155cc3d4031c61b2868a`.
- All seven proposals pass `validate_model_proposal`; all seven sidecars exactly equal recomputed checks.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `e48ea521c27e3de64a230b07f3780a12983454a5013e66eefa741f24deb94ef9` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `8e263b7bb90a98e1bdd04adaa525c50937805f96de10adb0cf34fac31d0444ec` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `616ff5cccc78d0d23100ed6c773ff1fad80052f5ffa71de07885ed93db7a6729` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 4 | `f6886f8563a8c26258b4acc669562d0b9795ed7c741361dea6d14f65fb0608ce` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 5 | `916cd28bc2caed6751f4b4d6e42d1077e7eca72bbefac5e46d0147121a9770f6` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `60dcd9b256a0b8920bf9f9ae1a0fd7bbc3092eae5943132ca7dac22b478c1b82` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 7 | `114719541d990fa3371601a314700706c428238b3e92d9678b36b331dfeba061` | `903964f2b8a6da32dd144614d70a94ae236f63c0c83ee9a5d9b8e9617b78be38` |

## Concurrency boundary

Only the frozen batch, seven proposal/sidecar pairs, raw source and R4 coverage artifact are hash-locked. Mutable global progress and manifest are not. Later unrelated appends do not alter this audit snapshot.
