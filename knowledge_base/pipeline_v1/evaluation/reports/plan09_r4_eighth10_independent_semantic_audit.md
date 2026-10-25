# Plan 09 R4 eighth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-5.6-sol` low. Producer: `gpt-6.1-sol` low.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-eighth10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 6 AUs, 3 hard negatives and 1 unresolved. Items 1, 4, 5, 7 and 8 have low-severity qualifications. **No severe findings** and no canonical correction are required.

These artifacts remain model-silver, not human gold. R5=false and Plan 10 remains locked. No target outside eighth10 was audited and no canonical/global artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-77795080c5c4a12d616c23fb` | agree / **low** | Commissioner compulsion is supported, but refusal only *can* lead to contempt/prosecution. Exact conditions and fair-play/testimony safeguards must remain attached. |
| 2 | `at-7ae2ae96e98fe1711c0bb0c8` | agree / none | Paragraph 20 is agency investigation history, not a court guilt finding. |
| 3 | `at-7c2438bcce27682cdd68ac16` | agree / none | Paragraph 105 states the court norm for this Commission fraud/compulsion context; scope is not all investigations. |
| 4 | `at-7ca139c74013a440ec1f9b58` | agree / **low** | Paragraph 174 confirms paragraph 173 but has no distinct formulation. Unresolved avoids duplicate AU and false editorial no-AU. |
| 5 | `at-7d8a081b1e141c63b05c04f0` | agree / **low** | Appointment-stage consequences and `could lead` modality are exact. The following `requires investigate` paraphrase is correctly excluded because raw section 69 says `may investigate`. |
| 6 | `at-7e7fcd55dcd3ac2c48651d45` | agree / none | Paragraph 44 conditionally permits objective explanation, not unrestricted merits/fairness advocacy. |
| 7 | `at-80dd855d64256453a585304d` | agree / **low** | Complete list and timing exceptions are correct, but attribution must stay Commission Policy and factors are considerations rather than mandatory cumulative gates. |
| 8 | `at-82b9a66eda69a6ecd5efa988` | agree / **low** | The defensible-in-facts-and-law inquiry is conditional on actual third-party jurisdiction and limited to this fraud finding. It is not a final jurisdiction/reasonableness outcome. |
| 9 | `at-848aa7019c8e57579343e4c6` | agree / none | Paragraph 138 is actual process history, not a universal two-report or compulsion rule. |
| 10 | `at-84d29312a5bc05be38261afa` | agree / none | Paragraph 171 is internal approval/report history, not a general finality or draft-comment rule. |

## Technical checks and snapshot

- Frozen batch SHA256: `75abea00a0b5812726b6c4732f3511ff984801923606bb83a4c3b93b6b7e5a77`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; exact source, spans/quotes, region identity and trace checksums revalidated.
- All ten sidecars exactly equal recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per frozen target; duplicate guards remain active.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `9b9746a0657d0f18ecf3c12aa8ff5b25d87f1b56ec45155966a0a6563e7704c7` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `0994192891152a6f22163f90058932d991f434beef1c1a70c994235603d2970a` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `506623305e25455941e7ea29d1fe93a47721a6d1b275625f8541e9c62b0c31e1` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `d8d873fbc1e17219b209d75a30fa2920c720f5e68c9c8392eb447e27abf6f9f4` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |
| 5 | `9e025613c4d0c32a51ae3fbc30f633d06afef9ae0fab57ab141c3ffbfeb38afd` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `dae47ba1a49ed5290114fe66e7c91a83f13cab3dc7c8c60ca1c85631c5a1dc38` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 7 | `e18ed9e1957447b98fece1bb0ae805823971972556bae966356e4f94c2fcc890` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 8 | `49cc717fd438b8f90cc104cc103ad1523a621d521fae9cd3141114c93045e89a` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 9 | `f141dddb42518844ad22d1553e5bb3c5c5fc532b5be5e9497c5ee94a19207381` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 10 | `a68cbbaa0b289741c03adcda4ea95a219e1ed799e0e78e083c67b933f889e096` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |

## Concurrency boundary

Mutable global progress and global R4/model-proposal manifest were not hash-locked. Registry access was limited to ownership verification. Later appends elsewhere do not alter this frozen snapshot.
