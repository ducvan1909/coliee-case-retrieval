# Plan 09 R4 eleventh10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-06. Independent reviewer: `gpt-6.1-sol` low. Producer: `gpt-6.1-sol` low; independence here means a separate review against frozen inputs and raw source, not a different model family.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-eleventh10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 3 AUs, 6 hard negatives and 1 unresolved. Items 2, 5, 8 and 10 have low-severity scope qualifications. **No severe findings** and no canonical correction are required.

These records remain model-silver, not human gold. R5=false and Plan 10 remains locked. No target outside eleventh10 was audited and no canonical/global artifact was modified.

## Item findings

| # | Target | Verdict | Independent assessment |
|---:|---|---|---|
| 1 | `at-9da27af39832dc60e64122b4` | agree / none | Applicant-side no-practical-effect explanation is not a court rule that fraud requires an appointment effect. |
| 2 | `at-a41b1c3147bae9ad5c1f0e11` | agree / **low** | The holding is that this Court declined a final jurisdiction/reasonableness ruling. Strong doubts are not a lack-of-jurisdiction holding. |
| 3 | `at-a7039ffbcf81acfdf39a03bc` | agree / none | Rousseau's quotation is philosophical framing, not PSEA law or a fraud-elements test. |
| 4 | `at-a717d9e338c80464e87d585c` | agree / none | Employer/DNR participation history creates no general participation or report entitlement. |
| 5 | `at-a8d96590034d4f26937d6ac4` | agree / **low** | Merit and non-partisanship are correctly limited to PSEA federal staffing; the AU does not import the next sentence's generalized honesty expectation. |
| 6 | `at-aa407c31bddfef792959ec7e` | agree / none | Reference quality, authorship and e-mails are evidentiary facts, not a court fraud test or guilt finding. |
| 7 | `at-aad011c3eeb3d5201e016a63` | agree / none | The two comment opportunities are respondent argument, not an adopted fairness finding; paragraph 169 identifies what was omitted. |
| 8 | `at-affded0df7852c0f341cd3b6` | agree / **low** | “Can give the impression” and “one may wonder” are tentative. Paragraph 186 uses apprehension as a remedy factor but does not supply a complete or settled bias holding; unresolved is appropriate. |
| 9 | `at-b0d26b01c226af7bf286f860` | agree / none | Corrective-action chronology and agency inflexibility are not judicial confirmation of guilt or a universal no-cure rule. |
| 10 | `at-b16418abd94e0e3822932535` | agree / **low** | Commissioner/Tribunal roles are correctly confined to the PSDPA framework and cannot be transferred to the PSEA Commission or applicant. |

## Key semantic boundaries

- **Bias:** paragraph 163 raises an appearance concern but does not resolve a complete reasonable-apprehension-of-bias test. Paragraph 186 confirms relevance to remedy without converting the concern into a definitive bias adjudication.
- **Jurisdiction:** paragraphs 183-184 expressly reserve jurisdiction and reasonableness. The Court's doubts and earlier inclination cannot be relabelled as a final lack-of-jurisdiction holding.
- **Staffing values:** the merit/non-partisanship AU ends before the broader honesty sentence. It is not a generalized legal fraud rule.
- **Source roles:** respondent memorandum, investigator findings, procedural history and philosophical quotation remain distinct from current-court propositions.

## Technical checks and snapshot

- Frozen batch SHA256: `03cee1d416041c6a4a047ccb866ecb64dd43d3455209e2f9efa5d05877f8d1f8`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten proposals pass `validate_model_proposal`; exact source, spans/quotes, region identity and trace checksums revalidated.
- All ten sidecars exactly equal recomputed validation results.
- All producers are exactly `model:gpt-6.1-sol` / `gpt-6.1-sol` / `low`, prompt `r4-au-annotation-prompt-v1`.
- Current registry read found one owner per target; duplicate guards remain active.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `3bc0bbc9dddfbc3698a6a7cb047e598a888efe4f48117a142c159c8b1ac8bc59` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 2 | `2a8467895d1cb773e13d1ab585aa043e64d51af7e2f77f54f91ac7eee07648cf` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 3 | `ad68bdb90c2f809831c2199b12108c7dcf2af2e6cd6e74ee49a8cbbe03cde312` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 4 | `f581cb7b31c5fd85947f4525c6a849f22d9eee211ca3b095e71fa6afd9cf450c` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 5 | `6e30b253ee6dfe1f55b977ab9d840501c1602cd5a54efcc2e394437dcaa80432` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 6 | `c0416fc1ee959bcf032014fd7eea6fbabe9e3db34107e76c7d80f1edd8036ed8` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 7 | `c5746975a86953c8df81fbdb3369a23237b8bd1df83b99d8abeb6525f7b20528` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 8 | `3399bc5145fc7ace09211553ee83d13968f8dfc4df0be9321285787ce8f0ef1d` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |
| 9 | `e9b183cdf8febc8cfe33c63757de77214a4f116a889c03213b81ba5340fdb878` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 10 | `a594c99947c70ad6f835cb74de1471cca335a1fb08ca334af24efb209d3579bb` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |

## Concurrency boundary

Mutable global progress and global R4/model-proposal manifest were not hash-locked. Registry access was limited to ownership verification. Later appends elsewhere do not alter this frozen snapshot.
