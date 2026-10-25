# Plan 09 R4 thirteenth10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-6.1-sol` low. Producer: `gpt-6.1-sol` low; independence here means a separate review against frozen inputs and raw source, not a different model family.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-thirteenth10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 9 AUs, 4 hard negatives and 0 unresolved. Items 1, 3, 4, 6, 9 and 10 have low-severity qualifications. **No severe findings** and no canonical correction are required.

These records remain model-silver, not human gold. R5=false and Plan 10 remains locked. No target outside thirteenth10 was audited and no canonical/global artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-c1baab4b25dbdf81279b1402` | agree / **low** | Late rule-changing harmed fairness/legitimate hopes in this investigation. The awkward notice phrase cannot become a general no-notice rule. |
| 2 | `at-c1cc43ba1d61581499bf96ef` | agree / none | Revised-report purpose and allegations are procedural history, not fraud or jurisdiction adjudication. |
| 3 | `at-c346a3add188a66127ed9fb5` | agree / **low** | Advantage evidence supports an intent inference; it creates neither a conclusive presumption nor applicant guilt. |
| 4 | `at-c41bd6c6fd1528e62af858c6` | agree / **low** | Two disjoint AUs correctly preserve cited-Commission source for bad faith and appointment-process nexus; they are not current-court holdings. |
| 5 | `at-c45b12bb6a6e0ed072ba48ac` | agree / none | Candidate notice and suspected authorship are allegations, not established fraud or a court test. |
| 6 | `at-c4bae0c79c06c92fb4b2d5a9` | agree / **low** | Two disjoint Justice Stratas AUs preserve optional remittal and “may disable” modality; aggressive advocacy is not automatic disqualification. |
| 7 | `at-c60115e01538c3e186265929` | agree / none | Impugned corrective order/transmittals are agency history, not judicial approval of sanction powers. |
| 8 | `at-c9c5a308ac656af5df34017b` | agree / none | Case-specific hearsay reliability and nondisclosure facts create no general hearsay ban, corroboration test or innocence finding. |
| 9 | `at-cc3ed060180327fc9de7fa85` | agree / **low** | Two disjoint current-court rules distinguish error/fraud and civil/criminal proof burdens; subsequent agency history is excluded. |
| 10 | `at-cdff3df736823759bcfd28d9` | agree / **low** | The qualified court view concerns accused public servants before the Commission's final verdict; it specifies no hearing form or innocence result. |

## Key semantic boundaries

- **Modality:** gained advantage `supports` an intent inference; merits advocacy `may` disable impartial redetermination. Neither is automatic.
- **Source role:** Personnel Psychology Centre propositions are `cited_commission_decision`; Justice Stratas is `cited_court`. Commission/investigator findings and notices remain procedural/factual material.
- **Fairness:** the holdings remain tied to this investigation or expressly qualified court language. They are not converted into universal procedure prescriptions.
- **Multi-AU splits:** items 4, 6 and 9 contain two semantically distinct AUs with pairwise non-overlapping primary spans.

## Technical checks and snapshot

- Frozen batch SHA256: `10e9829bb55f073d05bcc91496a4118682e9c3f5eabe813a2c8d8935c39f6d03`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; exact source, spans/quotes, region identity and trace checksums revalidated.
- All ten sidecars exactly equal recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target; duplicate guards remain active.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `05578cac3dae20509efdbb52015dd5b899397ba2eaea36559a92287067d4a47a` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 2 | `09ea871342eb79089dd73fb279a0a20d2f234b5abc420128135f7007b81dd4da` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `ace4acacc7463171637fea0235d19071817d2c52d26d903de69fe004073fd276` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 4 | `33795e5503f78da3063701394ca2e60ac56e6feeed2af0e712ef36a97dc6f2c9` | `cf4d0f507764d4e8868ee9aac052048b9fa892084a8c82b43beb0e647a7b68b4` |
| 5 | `1f973cb170483beb98ae25d1364f03fcb04f23f60dcea6f43055bd16e5851e67` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 6 | `a6dd036df3133b8554a0f60f1cb8b0914620ad86f48171bf466c0e0bc3a2aaac` | `cf4d0f507764d4e8868ee9aac052048b9fa892084a8c82b43beb0e647a7b68b4` |
| 7 | `6d7845c9779efbc6d703cb497434b891b0efa5997d5f5c43f89bb8240975f57f` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 8 | `75b2eea6027aa0379b4a26dd9f077631bd211b7c72db3e788e7400565dc9a7a8` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 9 | `3d53fc10988720d81ee5ed9fd3f35a26a49ef4cad644c7296df8cf47e5ead092` | `cf4d0f507764d4e8868ee9aac052048b9fa892084a8c82b43beb0e647a7b68b4` |
| 10 | `44962986e949b4c035078e374d1f47fa6c760d428500fd60359b7bef1f25a85e` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |

## Concurrency boundary

Mutable global progress and global R4/model-proposal manifest were not hash-locked. Registry access was limited to ownership verification. Later appends elsewhere do not alter this frozen snapshot.
