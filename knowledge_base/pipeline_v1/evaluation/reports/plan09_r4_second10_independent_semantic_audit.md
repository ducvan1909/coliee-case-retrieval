# Plan 09 R4 second10 — independent semantic audit

Report revision: **1** (initial; supersedes none). Audit date: 2026-10-05. Independent reviewer lane: `gpt-5.6-sol` low. Producer under audit: `gpt-6.1-sol` low.

## Verdict

**PASS WITH QUALIFICATIONS** for exactly frozen batch `p09-r4-099980-second10-sol-v1`: **10 agree, 0 disagree, 0 insufficient**; 2 positive AUs, 7 hard negatives and 1 unresolved. Eight items have no finding; items 6 and 9 have low-severity consumption qualifications. No canonical correction is required.

This is not semantic gold, not R5 completion, and does not unlock Plan 10. No target outside this batch was audited. No progress, manifest, proposal, sidecar or canonical label was changed.

## Independent findings

| # | Target | Verdict | Evidence-based assessment |
|---:|---|---|---|
| 1 | `at-0c041e93ec332ab4eaa1354a` | agree / none | Paragraph 92 contains court analysis and tentative agreement; paragraph 93 expressly declines a definitive jurisdiction/reasonableness opinion. `unresolved` avoids both a false final holding and a false party-only negative. |
| 2 | `at-10bb35c0b238a53d984dfdf8` | agree / none | Paragraph 189 is the respondent's costs concession and proposed treatment. The court ruling begins at paragraph 190. |
| 3 | `at-143c4e018a2c0568cdf11a72` | agree / none | Paragraph 16 is case history plus the investigator's finding/presumption. It does not establish a current-court duty to correct references. |
| 4 | `at-14a2c80dde4ce6c302eded10` | agree / none | Paragraph 160 assesses testimony and investigation purpose as facts. The legitimate-expectation proposition starts in paragraph 161 and belongs to another target. |
| 5 | `at-14ff8ed5bd6fc2b9d2b9cff5` | agree / none | Paragraph 74 reports the respondent's Seck 1/plenary-powers position. The court's analysis follows and later distances itself from Seck 1. |
| 6 | `at-169450a12e07bd505d8d2dab` | agree / **low** | Paragraph 196 disclaims innocence and uses emphatic current-court rhetoric. `editorial` hard-negative is acceptable because it supplies no new test or operative disposition beyond the earlier fairness holding. Qualification: the label must not be interpreted as non-court speech. |
| 7 | `at-174a2f0bbfd0b2d0d0ee2608` | agree / none | Paragraph 95 attributes the admission and procedural-sufficiency defence to the respondent. Court analysis begins at paragraph 96. |
| 8 | `at-188b314c4f3fc2293a2a3f9e` | agree / none | Paragraph 54 is a current-court `fact_pattern_rule`: intent is essential and material fact alone is insufficient. Paragraph 53 correctly supplies fraud context and the good-faith/error exception. |
| 9 | `at-19699b1ac79c9676fcc00a6d` | agree / **low** | Paragraph 61 supplies current-court analytical guidance on checking relevant false-reference jurisprudence. Qualification: it is not a final jurisdiction/reasonableness holding. The exact jurisdiction assumption and paragraph-93 reservation are indispensable and are both preserved. |
| 10 | `at-1f0c7e3838ca599ebd75ae72` | agree / none | Paragraph 90 recounts three Commission corrective actions; it does not endorse general authority to impose them. |

## Technical validation and immutable snapshot

- Frozen batch SHA256: `b480e669e1160664ab7271c1357a0d9eb54fc2d99ce0d0ffc16a5a0c3b9d8b37`.
- Raw source computed/declared SHA256: `49d56b1477fed32e9c45e52582884818f7632735542b22388911fccd602f2319`.
- All ten checkpoints pass `validate_model_proposal`; exact quotes, half-open spans, source identity, trace checksums and region identity revalidated against raw source.
- Every validation sidecar exactly equals the freshly recomputed result.
- Every producer is exactly `model:gpt-6.1-sol`, model `gpt-6.1-sol`, reasoning `low`; every prompt is `r4-au-annotation-prompt-v1`.
- Current registry read found exactly one owner for each frozen target. `r4.checkpoint` and `r4.rebuild_manifest` both reject duplicate target ownership with `checkpoint_duplicate_target`.

| # | Proposal SHA256 | Sidecar SHA256 |
|---:|---|---|
| 1 | `8e129f43fbe18df9c9dc2bbceace58a1acd83dfa0de9bac9826152067f84d83d` | `708dcb8b0f0fd734f24940fea1aca2e6195190bfd8573af26510491352c012bc` |
| 2 | `1a723cce3d58e1be8acb92dbd8886a8921a241ce19532e1273682c9f0f18a978` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 3 | `e96e55f3ec297e1fdb0b482a0d4c445265bfef6f9067a469ed033aa5bf3396c4` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 4 | `bef4be71a825cf296a45164f8c2cfc754bab7620875a57f894fc0e74426e776f` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 5 | `b3aadbb68ec74581bed07576d64c8fa12b4ed92bfdbf43b5c4eacf001d017306` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 6 | `e41d14e86f80342f31b129ec3180c7bc75c82471cc93906f52abbf54653da436` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 7 | `ac2f71d50df807ceec43b508e49faaa2594f3029df4e46235846d58b7d7b413c` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |
| 8 | `9a5f3813d5c358d3e7e3b6f5707cd09036c618f0c2fb41ed79cb64473dbb1d65` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 9 | `a31c86649bd18bc2ab33d361ea4846486ddaf000087f40be5880022aaac28d6a` | `a8d651f4b76b1bf246e53c75c2eb3bb78688d350cf9be25d25801dbd24a731ac` |
| 10 | `1d41160ae4e043d9cec9651932c9d39936dfbd95fd9ba57579fa5413ecb6e7b7` | `b7eccd02cc3428c47d844a599dc0e5be7971b2b6403d126a519053fb20ad5f9c` |

## Concurrency boundary

The mutable global progress and R4/model-proposal manifest were deliberately not hash-locked. The registry was read only for ownership at audit time. Later appends to other batches do not alter this frozen batch + ten checkpoint + ten sidecar + raw-source audit snapshot.
